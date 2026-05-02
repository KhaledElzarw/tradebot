import ai_sidecar


def test_build_payload_includes_grid_and_risk_context():
    payload = ai_sidecar._build_payload(
        {
            "symbol": "BTCUSDT",
            "interval": "1m",
            "feeBps": 10,
            "gridMaxExposurePct": 0.35,
            "maxDailyLossPct": 0.1,
        },
        {
            "market": {
                "price": 100.0,
                "candle": {"open": 99.0, "high": 101.0, "low": 98.0, "close": 100.0},
            },
            "paper": {"usdt": 50.0, "btc": 0.5},
            "grid": {
                "active": True,
                "spacing_pct": 0.01,
                "levels": 12,
                "max_exposure_pct": 0.35,
                "cost_basis_usdt": 45.0,
                "orders": [{"side": "BUY"}, {"side": "SELL"}],
            },
            "stats": {"trades": 2, "max_drawdown_pct": 0.03},
        },
    )

    assert payload["equityUsdt"] == 100.0
    assert payload["openBuyOrders"] == 1
    assert payload["openSellOrders"] == 1
    assert payload["riskLimits"]["maxDailyLossPct"] == 0.1


def test_fallback_decision_is_not_stale_and_has_source():
    payload = {"symbol": "BTCUSDT", "interval": "1m", "price": 100.0, "atrPct": 0.001, "trendStrength": 0.001}
    cfg = {"provider": "local", "model": "m", "quick_model": "q", "deep_model": "d"}

    decision = ai_sidecar._fallback_decision(
        state={"gridMaxExposurePct": 0.35},
        payload=payload,
        cfg=cfg,
        started=0.0,
        error=RuntimeError("down"),
        persist=False,
    )

    assert decision["source"] == "deterministic_fallback"
    assert decision["enabled"] is True
    assert "stale" not in decision
