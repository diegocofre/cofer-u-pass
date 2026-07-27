from __future__ import annotations

import pytest

from cofer_u_pass.adapters.registry import AdapterRegistry


class FakeLocator:
    def __init__(self, visible: bool):
        self._visible = visible

    async def count(self) -> int:
        return 1 if self._visible else 0

    @property
    def first(self):
        return self

    async def is_visible(self) -> bool:
        return self._visible


class FakePage:
    def __init__(self, visible_selectors: set[str], visible_roles: set[tuple[str, str | None]] | None = None):
        self.visible_selectors = visible_selectors
        self.visible_roles = visible_roles or set()

    def locator(self, value: str) -> FakeLocator:
        return FakeLocator(value in self.visible_selectors)

    def get_by_role(self, value: str, *, name=None, exact=False) -> FakeLocator:
        return FakeLocator((value, name) in self.visible_roles)

    def get_by_label(self, value: str, *, exact=False) -> FakeLocator:
        return FakeLocator(False)

    def get_by_placeholder(self, value: str, *, exact=False) -> FakeLocator:
        return FakeLocator(False)

    def get_by_text(self, value: str, *, exact=False) -> FakeLocator:
        return FakeLocator(False)


@pytest.mark.asyncio
async def test_chatgpt_guest_composer_is_not_treated_as_authenticated():
    adapter = AdapterRegistry().create("chatgpt")
    page = FakePage({"#prompt-textarea", "a[href*='/auth/login']"})
    assert await adapter.is_authenticated(page) is False


@pytest.mark.asyncio
async def test_chatgpt_composer_without_explicit_logged_out_signal_can_authenticate():
    adapter = AdapterRegistry().create("chatgpt")
    page = FakePage({"#prompt-textarea"})
    assert await adapter.is_authenticated(page) is True


@pytest.mark.asyncio
async def test_wait_until_authenticated_handles_delayed_provider_shell(monkeypatch):
    adapter = AdapterRegistry().create("chatgpt")
    calls = 0

    async def delayed(_page):
        nonlocal calls
        calls += 1
        return calls >= 3

    monkeypatch.setattr(adapter, "is_authenticated", delayed)
    assert await adapter.wait_until_authenticated(object(), timeout_seconds=0.2, poll_seconds=0.01) is True
    assert calls == 3


@pytest.mark.asyncio
async def test_ensure_authenticated_uses_bounded_wait(monkeypatch):
    adapter = AdapterRegistry().create("chatgpt")

    async def never(_page):
        return False

    monkeypatch.setattr(adapter, "is_authenticated", never)
    from cofer_u_pass.domain.errors import AuthenticationRequired

    with pytest.raises(AuthenticationRequired):
        await adapter.ensure_authenticated(object(), timeout_seconds=0.02, poll_seconds=0.01)
