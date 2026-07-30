from __future__ import annotations

import pytest

from cofer_u_pass.application.service import ApplicationService
from cofer_u_pass.domain.models import ProviderModel
from cofer_u_pass.provider.service import RestrictedProviderService


@pytest.mark.asyncio
async def test_discovered_model_wins_if_public_id_collides_with_legacy_profile_alias(config):
    service = ApplicationService(config)
    await service.start(execute_queued=False)
    try:
        # Deliberately use the same string as a legacy profile id and a real
        # discovered model id. The real model route must win.
        await service.create_profile("gpt-collision", "chatgpt")
        await service.db.update_profile("gpt-collision", authenticated=True, status="ready")
        provider = RestrictedProviderService(service)
        provider.catalog.save("gpt-collision", "chatgpt", [ProviderModel(
            id="gpt-collision",
            provider="chatgpt",
            display_name="GPT Collision",
            supported_efforts=["medium", "high"],
        )])

        route = await provider.resolve_model("gpt-collision", "high", allow_refresh=False)
        assert route.legacy_profile_alias is False
        assert route.profile_id == "gpt-collision"
        assert route.selection.model == "gpt-collision"
        assert route.selection.effort == "high"
    finally:
        await service.shutdown(cooperative=True)
