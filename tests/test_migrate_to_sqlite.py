import json

import migrate_to_sqlite
import sqlite_store


def test_migrate_imports_runtime_files_idempotently(tmp_path, monkeypatch):
    base = tmp_path / "runtime"
    base.mkdir()
    db = tmp_path / "tradebot.sqlite3"

    files = {
        "state": base / "state.json",
        "runtime_state": base / "runtime_state.json",
        "engine_status": base / "engine_status.json",
        "cumulative": base / "cumulative.json",
        "ai_signal": base / "ai_signal.json",
    }
    files["state"].write_text(json.dumps({"paused": False}), encoding="utf-8")
    files["runtime_state"].write_text(json.dumps({"enginePid": 123}), encoding="utf-8")
    files["engine_status"].write_text(json.dumps({"price": 100.0}), encoding="utf-8")
    files["cumulative"].write_text(json.dumps({"trades": 1}), encoding="utf-8")
    files["ai_signal"].write_text(json.dumps({"enabled": True}), encoding="utf-8")

    trades = base / "trades.jsonl"
    trades.write_text(
        "\n".join([
            json.dumps({"tsUtc": "2026-01-01T00:00:00+00:00", "event": "ENTER"}),
            json.dumps({"tsUtc": "2026-01-01T00:00:01+00:00", "event": "EXIT"}),
        ]),
        encoding="utf-8",
    )
    history = base / "dashboard_history.json"
    history.write_text(
        json.dumps({"items": [{"ts": "2026-01-01T00:00:00+00:00", "price": 100.0, "equity": 1000.0}]}),
        encoding="utf-8",
    )

    monkeypatch.setattr(migrate_to_sqlite, "SNAPSHOT_FILES", files)
    monkeypatch.setattr(migrate_to_sqlite, "TRADES_PATH", trades)
    monkeypatch.setattr(migrate_to_sqlite, "HISTORY_PATH", history)

    first = migrate_to_sqlite.migrate(db_path=db)
    second = migrate_to_sqlite.migrate(db_path=db)

    assert first == {"snapshots": 5, "events": 2, "history": 1}
    assert second == {"snapshots": 5, "events": 0, "history": 1}
    assert sqlite_store.read_snapshot("state", path=db) == {"paused": False}
    assert [event["event"] for event in sqlite_store.list_events(path=db)] == ["ENTER", "EXIT"]
    assert sqlite_store.read_history(path=db)["items"][0]["price"] == 100.0
