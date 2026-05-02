import ai_schemas


def test_decision_low_confidence_cannot_force_risk_off_action():
    decision = ai_schemas.decision_from_parsed(
        state={"aiMinConfidence": 0.8, "gridMaxExposurePct": 0.35},
        payload={"symbol": "BTCUSDT", "interval": "1m", "price": 100.0, "atrPct": 0.001, "trendStrength": 0.001},
        parsed={
            "riskAction": "flatten",
            "confidence": 0.2,
            "gridAllowed": False,
            "recommendedSpacingPct": 0.01,
            "recommendedLevels": 12,
            "recommendedMaxExposurePct": 0.35,
            "recommendedMode": "scalpy",
        },
        provider="local",
        model="deep",
        quick_model="quick",
        deep_model="deep",
        reports={},
        prompt_hash_value="abc123",
        latency_seconds=0.1,
    )

    assert decision["riskAction"] == "allow_grid"
    assert decision["flattenRecommended"] is False


def test_decision_preserves_shadow_and_dry_run_flags():
    decision = ai_schemas.decision_from_parsed(
        state={"aiDryRun": True, "aiShadowMode": True},
        payload={"symbol": "BTCUSDT", "interval": "1m", "price": 100.0},
        parsed={"confidence": 0.9, "riskAction": "allow_grid"},
        provider="local",
        model="model",
        quick_model="model",
        deep_model="model",
        reports={},
        prompt_hash_value="abc123",
        latency_seconds=0.1,
    )

    assert decision["dryRun"] is True
    assert decision["shadowMode"] is True


def test_string_evidence_and_key_risks_are_accepted():
    report = ai_schemas.report_from_parsed(
        "grid_risk",
        {
            "summary": "ok",
            "confidence": 0.7,
            "riskScore": 0.2,
            "recommendation": "allow_grid",
            "evidence": "single evidence sentence",
        },
    )
    decision = ai_schemas.decision_from_parsed(
        state={},
        payload={"symbol": "BTCUSDT", "interval": "1m", "price": 100.0},
        parsed={
            "riskAction": "allow_grid",
            "confidence": 0.8,
            "keyRisks": "single risk sentence",
        },
        provider="ollama",
        model="qwen3.5:9b",
        quick_model="qwen3.5:9b",
        deep_model="qwen3.5:9b",
        reports={},
        prompt_hash_value="abc123",
        latency_seconds=0.1,
    )

    assert report.confidence == 0.7
    assert report.evidence == ["single evidence sentence"]
    assert decision["confidence"] == 0.8
    assert decision["keyRisks"] == ["single risk sentence"]
