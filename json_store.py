import json
import os
from pathlib import Path
from typing import Callable

import fcntl


def atomic_write_json(path: str | Path, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(target)


def update_json_locked(path: str | Path, updater: Callable[[dict], dict]) -> dict:
    target = Path(path)
    lock_path = target.with_suffix(target.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            try:
                current = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
            except Exception:
                current = {}
            updated = updater(dict(current))
            atomic_write_json(target, updated)
            return updated
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
