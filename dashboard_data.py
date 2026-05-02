from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import sqlite_store


class DashboardDataAdapter:
    """SQLite-first runtime adapter with JSON mirrors as compatibility files."""

    def read_json(self, path: Path) -> dict:
        key = sqlite_store.snapshot_key_for_path(path)
        if key and sqlite_store.has_snapshot(key):
            return sqlite_store.read_snapshot(key)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def write_json(self, path: Path, payload: dict) -> None:
        key = sqlite_store.snapshot_key_for_path(path)
        if key:
            sqlite_store.write_snapshot(key, payload)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)

    def update_state(self, state_path: Path, updater: Callable[[dict], dict]) -> dict:
        if not sqlite_store.has_snapshot("state") and state_path.exists():
            try:
                sqlite_store.write_snapshot("state", json.loads(state_path.read_text(encoding="utf-8")))
            except Exception:
                pass
        state = sqlite_store.update_snapshot("state", updater)
        self.write_json(state_path, state)
        return state

    def read_events(self, trades_path: Path, *, limit: int = 500) -> list[dict]:
        rows = sqlite_store.list_events(limit=limit, include_ids=True)
        if rows:
            return rows
        if not trades_path.exists():
            return []
        rows = []
        try:
            with trades_path.open("r", encoding="utf-8") as f:
                for line_number, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        if isinstance(event, dict):
                            event["_eventId"] = line_number
                            rows.append(event)
                    except Exception:
                        continue
        except Exception:
            return []
        return rows[-limit:]

    def compact(self, *, event_keep: int = 5000, history_keep: int = 5000) -> dict:
        return sqlite_store.compact(event_keep=event_keep, history_keep=history_keep)
