import dashboard_orchestrator


def test_orchestrator_status_queries_all_runtime_services(monkeypatch):
    calls = []

    def fake_run(service, command):
        calls.append((service, command))
        return f"{service}-pid"

    monkeypatch.setattr(dashboard_orchestrator, "_run", fake_run)

    assert dashboard_orchestrator.status() == {
        "engine": "engine-pid",
        "dashboard": "dashboard-pid",
        "ai": "ai-pid",
    }
    assert calls == [("engine", "status"), ("dashboard", "status"), ("ai", "status")]


def test_orchestrator_restart_stops_before_starting(monkeypatch):
    calls = []

    def fake_run(service, command):
        calls.append((service, command))
        return f"{service}-{command}"

    monkeypatch.setattr(dashboard_orchestrator, "_run", fake_run)

    assert dashboard_orchestrator.restart() == {
        "engine": "engine-start",
        "dashboard": "dashboard-start",
        "ai": "ai-start",
    }
    assert calls == [
        ("ai", "stop"),
        ("engine", "stop"),
        ("dashboard", "stop"),
        ("engine", "start"),
        ("dashboard", "start"),
        ("ai", "start"),
    ]
