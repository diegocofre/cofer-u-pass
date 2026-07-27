from __future__ import annotations

import asyncio
import importlib.metadata
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from cofer_u_pass.config.settings import AppConfig
from cofer_u_pass.domain.errors import EnvironmentFailure


def playwright_version() -> str:
    try:
        return importlib.metadata.version("playwright")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def origin(url: str) -> str:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return ""
    default = (parts.scheme == "https" and parts.port in {None, 443}) or (parts.scheme == "http" and parts.port in {None, 80})
    netloc = parts.hostname or ""
    if parts.port and not default:
        netloc += f":{parts.port}"
    return f"{parts.scheme}://{netloc}"


class ManagedBrowser:
    def __init__(self, playwright: Playwright, context: BrowserContext, page: Page):
        self.playwright = playwright
        self.context = context
        self.page = page

    async def close(self) -> None:
        try:
            await self.context.close()
        finally:
            await self.playwright.stop()


class BrowserRuntime:
    def __init__(self, config: AppConfig):
        self.config = config

    async def launch_persistent(
        self,
        profile_dir: Path,
        *,
        headless: bool,
        allowed_origins: set[str],
    ) -> ManagedBrowser:
        try:
            pw = await async_playwright().start()
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=headless,
                accept_downloads=True,
                ignore_https_errors=False,
                no_viewport=True if not headless else False,
            )
            pages = context.pages
            page = pages[0] if pages else await context.new_page()
            page.set_default_timeout(self.config.browser.action_timeout_seconds * 1000)

            async def route_handler(route):
                request = route.request
                if request.is_navigation_request() and request.frame == page.main_frame:
                    requested_origin = origin(request.url)
                    if requested_origin and requested_origin not in allowed_origins:
                        await route.abort("blockedbyclient")
                        return
                await route.continue_()

            await page.route("**/*", route_handler)
            return ManagedBrowser(pw, context, page)
        except Exception as exc:
            raise EnvironmentFailure(f"could not start Playwright Chromium: {exc}") from exc

    async def chromium_executable(self) -> Path | None:
        pw = await async_playwright().start()
        try:
            value = pw.chromium.executable_path
            path = Path(value)
            return path if path.exists() else None
        finally:
            await pw.stop()

    async def detect_chromium_version(self) -> str:
        pw = await async_playwright().start()
        try:
            try:
                browser = await pw.chromium.launch(headless=True)
            except Exception as exc:
                raise EnvironmentFailure(f"Playwright-managed Chromium is unavailable or incompatible: {exc}") from exc
            try:
                return browser.version
            finally:
                await browser.close()
        finally:
            await pw.stop()
