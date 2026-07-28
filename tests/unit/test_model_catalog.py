from __future__ import annotations

from cofer_u_pass.domain.models import ProviderModel
from cofer_u_pass.persistence.model_catalog import ModelCatalogStore


def test_model_catalog_round_trip_is_rebuildable_outside_sqlite(config):
    store = ModelCatalogStore(config)
    saved = store.save("chatgpt-main", "chatgpt", [ProviderModel(
        id="gpt-5.6-sol",
        provider="chatgpt",
        display_name="GPT-5.6 Sol",
        supported_efforts=["medium", "high"],
    )])
    loaded = store.load("chatgpt-main")
    assert loaded is not None
    assert loaded.profile_id == saved.profile_id
    assert loaded.provider == "chatgpt"
    assert loaded.error is None
    assert loaded.models[0].id == "gpt-5.6-sol"


def test_model_catalog_refresh_error_replaces_stale_models(config):
    store = ModelCatalogStore(config)
    store.save("chatgpt-main", "chatgpt", [ProviderModel(
        id="gpt-old",
        provider="chatgpt",
        display_name="GPT Old",
    )])
    store.save_error("chatgpt-main", "chatgpt", "AdapterMismatch: picker changed")
    loaded = store.load("chatgpt-main")
    assert loaded is not None
    assert loaded.models == []
    assert loaded.error == "AdapterMismatch: picker changed"
