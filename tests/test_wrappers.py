import run_dashboard_detached
import run_engine_detached
import run_ai_sidecar_detached


def test_engine_status_is_observational(monkeypatch, tmp_path):
    pid_path = tmp_path / "engine.pid"
    pid_path.write_text("1", encoding="utf-8")
    monkeypatch.setattr(run_engine_detached, "PID_PATH", pid_path)
    monkeypatch.setattr(run_engine_detached, "_all_engine_pids", lambda: [10, 20])

    assert run_engine_detached.status() == 20
    assert pid_path.read_text(encoding="utf-8") == "1"


def test_dashboard_status_is_observational(monkeypatch, tmp_path):
    pid_path = tmp_path / "dashboard.pid"
    pid_path.write_text("1", encoding="utf-8")
    monkeypatch.setattr(run_dashboard_detached, "PID_PATH", pid_path)
    monkeypatch.setattr(run_dashboard_detached, "_listening_pid_on_port", lambda: 99)
    monkeypatch.setattr(run_dashboard_detached, "_live_dashboard_pids", lambda: [10, 20])

    assert run_dashboard_detached.status() == 99
    assert pid_path.read_text(encoding="utf-8") == "1"


def test_ai_sidecar_status_is_observational(monkeypatch, tmp_path):
    pid_path = tmp_path / "ai_sidecar.pid"
    pid_path.write_text("1", encoding="utf-8")
    monkeypatch.setattr(run_ai_sidecar_detached, "PID_PATH", pid_path)
    monkeypatch.setattr(run_ai_sidecar_detached, "_live_pids", lambda: [30, 40])

    assert run_ai_sidecar_detached.status() == 40
    assert pid_path.read_text(encoding="utf-8") == "1"
