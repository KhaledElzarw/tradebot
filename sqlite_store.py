import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "tradebot.sqlite3"
SCHEMA_VERSION = "1"

SNAPSHOT_KEYS = {
    "state.json": "state",
    "runtime_state.json": "runtime_state",
    "engine_status.json": "engine_status",
    "cumulative.json": "cumulative",
    "ai_signal.json": "ai_signal",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_path() -> Path:
    return Path(os.getenv("TRADEBOT_DB_PATH") or DEFAULT_DB_PATH)


def snapshot_key_for_path(path: str | Path) -> str | None:
    return SNAPSHOT_KEYS.get(Path(path).name)


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    target = Path(path) if path is not None else db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(path: str | Path | None = None) -> Path:
    target = Path(path) if path is not None else db_path()
    with connect(target) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kv (
                key TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT,
                event_type TEXT,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts_id ON events(ts_utc, id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL UNIQUE,
                price REAL,
                equity REAL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_history_ts ON history(ts_utc)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (SCHEMA_VERSION,),
        )
    return target


def _decode_payload(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def read_snapshot(key: str, default: dict | None = None, *, path: str | Path | None = None) -> dict:
    init_db(path)
    with connect(path) as conn:
        row = conn.execute("SELECT payload_json FROM kv WHERE key = ?", (key,)).fetchone()
    if not row:
        return dict(default or {})
    payload = _decode_payload(row["payload_json"])
    return payload if payload else dict(default or {})


def has_snapshot(key: str, *, path: str | Path | None = None) -> bool:
    init_db(path)
    with connect(path) as conn:
        row = conn.execute("SELECT 1 FROM kv WHERE key = ?", (key,)).fetchone()
    return row is not None


def write_snapshot(key: str, payload: dict, *, path: str | Path | None = None) -> dict:
    init_db(path)
    body = dict(payload or {})
    with connect(path) as conn:
        conn.execute(
            """
            INSERT INTO kv(key, payload_json, updated_at_utc)
            VALUES(?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                payload_json=excluded.payload_json,
                updated_at_utc=excluded.updated_at_utc
            """,
            (key, json.dumps(body, sort_keys=True), utc_now()),
        )
    return body


def update_snapshot(key: str, updater: Callable[[dict], dict], *, path: str | Path | None = None) -> dict:
    init_db(path)
    with connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT payload_json FROM kv WHERE key = ?", (key,)).fetchone()
        current = _decode_payload(row["payload_json"]) if row else {}
        updated = dict(updater(dict(current)) or {})
        conn.execute(
            """
            INSERT INTO kv(key, payload_json, updated_at_utc)
            VALUES(?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                payload_json=excluded.payload_json,
                updated_at_utc=excluded.updated_at_utc
            """,
            (key, json.dumps(updated, sort_keys=True), utc_now()),
        )
        conn.commit()
    return updated


def append_event(event: dict, *, path: str | Path | None = None) -> int:
    init_db(path)
    payload = dict(event or {})
    with connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO events(ts_utc, event_type, payload_json) VALUES(?, ?, ?)",
            (
                payload.get("tsUtc") or payload.get("ts_utc"),
                payload.get("event"),
                json.dumps(payload, sort_keys=True),
            ),
        )
        return int(cur.lastrowid)


def list_events(*, limit: int | None = None, path: str | Path | None = None, include_ids: bool = False) -> list[dict]:
    init_db(path)
    if limit is None:
        sql = "SELECT id, payload_json FROM events ORDER BY id ASC"
        params: tuple = ()
    else:
        sql = "SELECT id, payload_json FROM events ORDER BY id DESC LIMIT ?"
        params = (int(limit),)
    with connect(path) as conn:
        rows = conn.execute(sql, params).fetchall()
    events = []
    for row in rows:
        event = _decode_payload(row["payload_json"])
        if event and include_ids:
            event["_eventId"] = int(row["id"])
        events.append(event)
    if limit is not None:
        events.reverse()
    return [event for event in events if event]


def upsert_history_item(ts_utc: str, price: float | None, equity: float | None, *, path: str | Path | None = None) -> None:
    init_db(path)
    with connect(path) as conn:
        conn.execute(
            """
            INSERT INTO history(ts_utc, price, equity) VALUES(?, ?, ?)
            ON CONFLICT(ts_utc) DO UPDATE SET
                price=excluded.price,
                equity=excluded.equity
            """,
            (ts_utc, price, equity),
        )


def read_history(*, limit: int = 5000, path: str | Path | None = None) -> dict:
    init_db(path)
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT ts_utc, price, equity FROM history ORDER BY ts_utc DESC, id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    items = [
        {"ts": row["ts_utc"], "price": row["price"], "equity": row["equity"]}
        for row in reversed(rows)
    ]
    return {"items": items}


def import_history_items(items: list[dict], *, path: str | Path | None = None) -> int:
    count = 0
    for item in items:
        ts = item.get("ts") or item.get("tsUtc") or item.get("ts_utc")
        if not ts:
            continue
        upsert_history_item(ts, item.get("price"), item.get("equity"), path=path)
        count += 1
    return count


def compact(*, event_keep: int = 5000, history_keep: int = 5000, path: str | Path | None = None) -> dict:
    init_db(path)
    event_keep = max(0, int(event_keep))
    history_keep = max(0, int(history_keep))
    with connect(path) as conn:
        event_deleted = conn.execute(
            """
            DELETE FROM events
            WHERE id NOT IN (
                SELECT id FROM events ORDER BY id DESC LIMIT ?
            )
            """,
            (event_keep,),
        ).rowcount
        history_deleted = conn.execute(
            """
            DELETE FROM history
            WHERE id NOT IN (
                SELECT id FROM history ORDER BY ts_utc DESC, id DESC LIMIT ?
            )
            """,
            (history_keep,),
        ).rowcount
        conn.execute("PRAGMA optimize")
    return {"eventsDeleted": int(event_deleted or 0), "historyDeleted": int(history_deleted or 0)}
