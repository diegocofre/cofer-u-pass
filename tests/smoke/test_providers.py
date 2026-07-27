from __future__ import annotations

import os
from pathlib import Path

import pytest

from cofer_u_pass.application.service import ApplicationService
from cofer_u_pass.config.settings import load_config


@pytest.mark.asyncio
@pytest.mark.smoke
async def test_supervised_provider_smoke():
    profile = os.environ.get("COFER_U_PASS_SMOKE_PROFILE")
    provider = os.environ.get("COFER_U_PASS_SMOKE_PROVIDER")
    if not profile or provider not in {"chatgpt", "gemini", "deepseek"}:
        pytest.skip("set COFER_U_PASS_SMOKE_PROFILE and COFER_U_PASS_SMOKE_PROVIDER for supervised smoke")
    service = ApplicationService(load_config())
    await service.start()
    actual = await service.db.get_profile(profile)
    if not actual or actual.provider != provider:
        pytest.skip("configured smoke profile/provider does not exist or does not match")
    root = Path(__file__).parents[2]
    run = await service.create_run(root / "examples" / "ask.yaml", profile_id=profile, inputs={"prompt": "Reply exactly with COFER_U_PASS_SMOKE_OK"})
    done = await service.wait(run.run_id)
    assert done.state.value == "completed", done.error_message
    result = await service.db.get_result(run.run_id)
    assert result and "COFER_U_PASS_SMOKE_OK" in result.text
