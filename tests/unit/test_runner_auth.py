from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import pytest

from cofer_u_pass.application.service import ApplicationService
from cofer_u_pass.domain.models import ConversationMode, ExecutionPlan, ProfileRecord, RunRecord, RunState


def _now():
    return datetime.now(timezone.utc)


class FakeBrowser:
    def __init__(self):
        self.page = object()
        self.closed = False

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_run_preflight_waits_for_delayed_authenticated_ui(config, monkeypatch):
    service = ApplicationService(config)
    await service.start(execute_queued=False)

    profile_dir = config.profiles_path / "generic-run"
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.chmod(0o700)
    await service.db.create_profile(ProfileRecord(
        profile_id="generic-run", provider="generic", profile_dir=str(profile_dir),
        authenticated=True, status="ready", chromium_version="test-chromium",
        created_at=_now(), updated_at=_now(),
    ))

    adapter = service.registry.create("generic")
    calls = 0

    async def delayed(_page):
        nonlocal calls
        calls += 1
        return calls >= 3

    async def no_navigation(_page):
        return None

    monkeypatch.setattr(adapter, "is_authenticated", delayed)
    monkeypatch.setattr(adapter, "navigate_home", no_navigation)
    monkeypatch.setattr(service.registry, "create", lambda _provider: adapter)
    monkeypatch.setattr(service.runtime, "detect_chromium_version", lambda: _async_value("test-chromium"))
    browser = FakeBrowser()

    async def fake_launch(profile_dir: Path, *, headless: bool, allowed_origins: set[str]):
        return browser

    monkeypatch.setattr(service.runtime, "launch_persistent", fake_launch)

    run = RunRecord(
        run_id="run-delayed-auth", protocol_id="test", protocol_version="1.0.0",
        protocol_hash="ph", input_values={}, input_hash="ih", profile_id="generic-run",
        provider="generic", conversation_mode=ConversationMode.NEW, config_hash="ch",
        config_snapshot={"browser": {"headless_default": False}}, component_versions={},
        state=RunState.QUEUED, plan=ExecutionPlan(actions=(), required_capabilities=()),
        created_at=_now(), updated_at=_now(),
    )
    await service.db.create_run(run)

    await service.executor.execute(run.run_id)

    stored = await service.get_run(run.run_id)
    assert stored.state == RunState.COMPLETED
    assert calls >= 3
    assert browser.closed is True


async def _async_value(value):
    return value
