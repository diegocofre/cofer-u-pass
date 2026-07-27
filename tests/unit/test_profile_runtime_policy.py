from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from cofer_u_pass.application.service import ApplicationService
from cofer_u_pass.domain.models import ProfileRecord


class FakePage:
    pass


class FakeBrowser:
    def __init__(self):
        self.page = FakePage()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeAdapter:
    provider = "chatgpt"
    allowed_origins = {"https://chatgpt.com"}
    supports_headless_authentication_check = False

    async def navigate_home(self, page) -> None:
        return None

    async def is_authenticated(self, page) -> bool:
        return True

    async def wait_until_authenticated(self, page, *, timeout_seconds: float = 15.0, poll_seconds: float = 0.5) -> bool:
        for _ in range(10):
            if await self.is_authenticated(page):
                return True
        return False


@pytest.mark.asyncio
async def test_profile_verify_uses_visible_browser_when_adapter_does_not_support_headless_auth_check(config, monkeypatch):
    service = ApplicationService(config)
    await service.start(execute_queued=False)
    now = datetime.now(timezone.utc)
    profile_dir = config.profiles_path / "chatgpt-main"
    profile_dir.mkdir(parents=True, exist_ok=True)
    await service.db.create_profile(ProfileRecord(
        profile_id="chatgpt-main",
        provider="chatgpt",
        profile_dir=str(profile_dir),
        created_at=now,
        updated_at=now,
    ))

    adapter = FakeAdapter()
    monkeypatch.setattr(service.registry, "create", lambda provider: adapter)
    launched: dict[str, object] = {}

    async def fake_launch(profile_dir: Path, *, headless: bool, allowed_origins: set[str]):
        launched["headless"] = headless
        launched["allowed_origins"] = allowed_origins
        return FakeBrowser()

    monkeypatch.setattr(service.runtime, "launch_persistent", fake_launch)

    result = await service.profile_status("chatgpt-main", verify=True)

    assert launched["headless"] is False
    assert result.authenticated is True
    assert result.status == "ready"


@pytest.mark.asyncio
async def test_generic_adapter_declares_headless_verification(config):
    service = ApplicationService(config)
    adapter = service.registry.create("generic")
    assert adapter.supports_headless_authentication_check is True
    assert adapter.supports_headless_execution is True


@pytest.mark.asyncio
async def test_live_provider_adapters_default_to_visible_until_headless_is_validated(config):
    service = ApplicationService(config)
    for provider in ("chatgpt", "gemini", "deepseek"):
        adapter = service.registry.create(provider)
        assert adapter.supports_headless_authentication_check is False
        assert adapter.supports_headless_execution is False


class DelayedAuthAdapter(FakeAdapter):
    def __init__(self):
        self.calls = 0

    async def is_authenticated(self, page) -> bool:
        self.calls += 1
        return self.calls >= 3


@pytest.mark.asyncio
async def test_profile_verify_waits_for_delayed_authenticated_ui(config, monkeypatch):
    service = ApplicationService(config)
    await service.start(execute_queued=False)
    now = datetime.now(timezone.utc)
    profile_dir = config.profiles_path / "chatgpt-delayed"
    profile_dir.mkdir(parents=True, exist_ok=True)
    await service.db.create_profile(ProfileRecord(
        profile_id="chatgpt-delayed",
        provider="chatgpt",
        profile_dir=str(profile_dir),
        authenticated=True,
        status="ready",
        created_at=now,
        updated_at=now,
    ))

    adapter = DelayedAuthAdapter()
    monkeypatch.setattr(service.registry, "create", lambda provider: adapter)

    async def fake_launch(profile_dir: Path, *, headless: bool, allowed_origins: set[str]):
        return FakeBrowser()

    monkeypatch.setattr(service.runtime, "launch_persistent", fake_launch)

    result = await service.profile_status("chatgpt-delayed", verify=True)

    assert adapter.calls >= 3
    assert result.authenticated is True
    assert result.status == "ready"
