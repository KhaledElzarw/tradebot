import baserow_sync


def test_baserow_sync_disabled_without_token(monkeypatch):
    monkeypatch.setattr(baserow_sync, "TOKEN", "")

    syncer = baserow_sync.BaserowSync()

    assert syncer.enabled is False
