from __future__ import annotations

import pytest

from cofer_u_pass.browser.runtime import ManagedBrowser, _is_already_closed_error


class _FakeContext:
    def __init__(self, error: BaseException | None = None):
        self.error = error
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1
        if self.error is not None:
            raise self.error


class _FakePlaywright:
    def __init__(self, error: BaseException | None = None):
        self.error = error
        self.stop_calls = 0

    async def stop(self) -> None:
        self.stop_calls += 1
        if self.error is not None:
            raise self.error


class _FakePage:
    pass


def test_already_closed_error_recognizes_live_driver_disconnect():
    assert _is_already_closed_error(
        Exception("BrowserContext.close: Connection closed while reading from the driver")
    )
    assert _is_already_closed_error(
        Exception("Target page, context or browser has been closed")
    )
    assert not _is_already_closed_error(Exception("permission denied"))


@pytest.mark.asyncio
async def test_managed_browser_close_ignores_already_closed_driver_and_stops_playwright():
    context = _FakeContext(
        Exception("BrowserContext.close: Connection closed while reading from the driver")
    )
    playwright = _FakePlaywright(
        Exception("Playwright connection closed")
    )
    browser = ManagedBrowser(playwright, context, _FakePage())

    await browser.close()

    assert context.close_calls == 1
    assert playwright.stop_calls == 1


@pytest.mark.asyncio
async def test_managed_browser_close_propagates_unexpected_cleanup_error_after_stop():
    context_error = RuntimeError("unexpected context cleanup failure")
    context = _FakeContext(context_error)
    playwright = _FakePlaywright()
    browser = ManagedBrowser(playwright, context, _FakePage())

    with pytest.raises(RuntimeError, match="unexpected context cleanup failure") as exc_info:
        await browser.close()

    assert exc_info.value is context_error
    assert context.close_calls == 1
    assert playwright.stop_calls == 1
