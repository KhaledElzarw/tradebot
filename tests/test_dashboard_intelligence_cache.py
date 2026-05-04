from datetime import datetime, timezone

import dashboard_server


def test_missing_dashboard_intelligence_cache_returns_fallback_without_writing(monkeypatch, tmp_path):
    missing_cache = tmp_path / "dashboard_intelligence.json"
    refresh_starts = []

    class FakeThread:
        def __init__(self, target=None, daemon=None):
            self.target = target
            self.daemon = daemon

        def start(self):
            refresh_starts.append(self.target)

    monkeypatch.setattr(dashboard_server, "INTELLIGENCE_PATH", missing_cache)
    monkeypatch.setattr(dashboard_server, "_fetch_news_items", lambda limit=12: [])
    monkeypatch.setattr(dashboard_server.threading, "Thread", FakeThread)
    monkeypatch.setattr(
        dashboard_server,
        "datetime",
        type(
            "FixedDateTime",
            (),
            {
                "now": staticmethod(lambda tz=None: datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc)),
                "fromtimestamp": staticmethod(datetime.fromtimestamp),
            },
        ),
    )
    monkeypatch.setattr(dashboard_server, "_intelligence_refreshing", False)

    status = {
        "symbol": "BTCUSDT",
        "price": 100.0,
        "equityUsdt": 1000.0,
        "btc": 0.1,
    }
    state = {"aiEnabled": False, "symbol": "BTCUSDT", "interval": "1m"}
    ohlcv = [{"open": 99.0, "high": 101.0, "low": 98.0, "close": 100.0}]

    payload = dashboard_server.get_intelligence(state, status, ohlcv)

    assert isinstance(payload, dict)
    assert {
        "source",
        "generatedAtUtc",
        "nextRefreshAtUtc",
        "finalRegime",
        "regimeSignals",
        "newsCards",
        "rawNews",
    }.issubset(payload)
    assert payload["source"] == "deterministic_fallback"
    assert isinstance(payload["finalRegime"], dict)
    assert isinstance(payload["regimeSignals"], list)
    assert isinstance(payload["newsCards"], list)
    assert isinstance(payload["rawNews"], list)
    assert payload["refreshing"] is True
    assert len(refresh_starts) == 1
    assert not missing_cache.exists()
