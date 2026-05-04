import os
import subprocess
from pathlib import Path


def get_python_executable(default_python: str) -> str:
    return os.getenv("TRADEBOT_PYTHON") or default_python


def start_detached(
    python: str,
    target: str,
    base_dir: Path,
    log_path: Path,
) -> int:
    with open(log_path, "ab", buffering=0) as log:
        proc = subprocess.Popen(
            [python, target],
            cwd=str(base_dir),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            env=os.environ.copy(),
        )
    return proc.pid


def write_pid(pid_path: Path, pid: int) -> None:
    pid_path.write_text(str(pid))


def unlink_pid(pid_path: Path) -> None:
    if pid_path.exists():
        pid_path.unlink()
