from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from cofer_u_pass.adapters.registry import AdapterRegistry
from cofer_u_pass.domain.errors import AdapterMismatch


HTML = r'''<!doctype html>
<html>
<body>
  <aside>
    <a data-sidebar-item="true" href="/c/secret-conversation">
      <button data-testid="model-switcher-dropdown-button">SECRET CHAT GPT-5.6 Pro</button>
    </a>
  </aside>

  <main style="margin-left: 360px; padding-top: 120px;">
    <div data-testid="composer" style="width: 620px; height: 80px;">
      <textarea id="prompt-textarea"></textarea>
    </div>
    <div
      id="mystery-picker"
      role="button"
      tabindex="0"
      data-testid="mystery-mode-control"
      aria-expanded="false"
      style="width: 180px; height: 40px; margin-top: 12px;"
    >Auto</div>
    <button id="attach" aria-label="Attach files">Attach</button>
  </main>
</body>
</html>'''


@pytest.mark.asyncio
@pytest.mark.integration
async def test_chatgpt_picker_failure_reports_nearby_controls_without_sidebar_data():
    playwright = await async_playwright().start()
    try:
        try:
            browser = await playwright.chromium.launch(headless=True)
        except Exception:
            pytest.skip("Playwright Chromium is not installed")
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 800})
            await page.set_content(HTML)
            adapter = AdapterRegistry().create("chatgpt")

            with pytest.raises(AdapterMismatch) as exc_info:
                await adapter._model_picker(page)

            message = str(exc_info.value)
            assert "ChatGPT model picker could not be located" in message
            assert "Nearby interactive controls" in message
            assert "mystery-mode-control" in message
            assert "Auto" in message
            assert "SECRET CHAT" not in message
            assert "/c/secret-conversation" not in message
            assert "href=" not in message
        finally:
            await browser.close()
    finally:
        await playwright.stop()
