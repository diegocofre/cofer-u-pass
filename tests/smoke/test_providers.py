from __future__ import annotations

import os
from pathlib import Path

import pytest

from cofer_u_pass.application.service import ApplicationService
from cofer_u_pass.config.settings import load_config
from cofer_u_pass.provider.service import RestrictedProviderService


@pytest.mark.asyncio
@pytest.mark.smoke
async def test_supervised_provider_smoke():
    profile = os.environ.get("COFER_U_PASS_SMOKE_PROFILE")
    provider = os.environ.get("COFER_U_PASS_SMOKE_PROVIDER")
    if not profile or provider not in {"chatgpt", "gemini", "deepseek"}:
        pytest.skip("set COFER_U_PASS_SMOKE_PROFILE and COFER_U_PASS_SMOKE_PROVIDER for supervised smoke")
    service = ApplicationService(load_config())
    await service.start()
    try:
        actual = await service.db.get_profile(profile)
        if not actual or actual.provider != provider:
            pytest.skip("configured smoke profile/provider does not exist or does not match")
        root = Path(__file__).parents[2]
        run = await service.create_run(
            root / "examples" / "ask.yaml",
            profile_id=profile,
            inputs={"prompt": "Reply exactly with COFER_U_PASS_SMOKE_OK"},
        )
        done = await service.wait(run.run_id)
        await service.wait_for_execution_cleanup(run.run_id)
        assert done.state.value == "completed", done.error_message
        result = await service.db.get_result(run.run_id)
        assert result and "COFER_U_PASS_SMOKE_OK" in result.text
    finally:
        await service.shutdown(cooperative=True)


@pytest.mark.asyncio
@pytest.mark.smoke
async def test_supervised_chatgpt_model_effort_smoke():
    profile = os.environ.get("COFER_U_PASS_SMOKE_PROFILE")
    provider_name = os.environ.get("COFER_U_PASS_SMOKE_PROVIDER")
    model = os.environ.get("COFER_U_PASS_SMOKE_MODEL")
    effort = os.environ.get("COFER_U_PASS_SMOKE_EFFORT")
    if not profile or provider_name != "chatgpt" or not model or not effort:
        pytest.skip(
            "set COFER_U_PASS_SMOKE_PROFILE, COFER_U_PASS_SMOKE_PROVIDER=chatgpt, "
            "COFER_U_PASS_SMOKE_MODEL, and COFER_U_PASS_SMOKE_EFFORT for inference smoke"
        )

    service = ApplicationService(load_config())
    await service.start()
    try:
        actual = await service.db.get_profile(profile)
        if not actual or actual.provider != "chatgpt" or not actual.authenticated:
            pytest.skip("configured ChatGPT smoke profile does not exist or is not authenticated")

        web_provider = RestrictedProviderService(service)
        snapshot = await web_provider.profile_catalog(profile)
        if snapshot is None or snapshot.error:
            pytest.skip("ChatGPT model catalog is missing or invalid; refresh it before smoke")
        advertised = next((item for item in snapshot.models if item.id == model), None)
        if advertised is None or effort not in advertised.supported_efforts:
            pytest.skip("requested smoke model/effort is not advertised by the selected profile")

        response = await web_provider.execute({
            "model": model,
            "reasoning": {"effort": effort},
            "input": "Respond exactly with COFER_U_PASS_MODEL_EFFORT_OK",
        })
        assert "COFER_U_PASS_MODEL_EFFORT_OK" in response["output_text"]
        assert response["metadata"]["cofer_effective_model"] == model
        assert response["metadata"]["cofer_effective_effort"] == effort
    finally:
        await service.shutdown(cooperative=True)
