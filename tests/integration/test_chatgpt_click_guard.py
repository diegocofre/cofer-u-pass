from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from cofer_u_pass.adapters.registry import AdapterRegistry
from cofer_u_pass.domain.errors import AdapterMismatch


INTERCEPTED_HTML = r'''<!doctype html>
<html>
<head>
<style>
  body { margin: 0; }
  main { position: relative; margin-left: 320px; padding: 80px; width: 700px; }
  [data-testid="composer"] { width: 600px; height: 80px; }
  #model-trigger { position: absolute; left: 80px; top: 100px; width: 180px; height: 40px; }
  #model-menu { position: absolute; left: 80px; top: 144px; width: 240px; }
  #sidebar-interceptor {
    position: fixed;
    left: 400px;
    top: 100px;
    width: 180px;
    height: 40px;
    z-index: 100;
    display: block;
  }
</style>
</head>
<body>
  <main>
    <div id="model-trigger" role="button" tabindex="0">GPT-5.6 Sol</div>
    <div data-testid="composer"><textarea id="prompt-textarea"></textarea></div>
    <div id="model-menu" hidden>
      <button role="menuitemradio" data-testid="model-switcher-gpt-5-6-sol">GPT-5.6 Sol</button>
      <button role="menuitemradio" data-testid="model-switcher-gpt-5-6-pro">GPT-5.6 Pro</button>
    </div>
  </main>

  <a id="sidebar-interceptor"
     tabindex="0"
     data-fill=""
     draggable="true"
     data-discover="true"
     data-sidebar-item="true"
     aria-label="Modelo de conversación"
     href="/c/6a66d296-2f54-83e9-b4bc-9764a725f0ac">Modelo de conversación</a>

<script>
window.modelPickerClicks = 0;
const picker = document.querySelector('#model-trigger');
const menu = document.querySelector('#model-menu');
picker.onclick = () => {
  window.modelPickerClicks += 1;
  menu.hidden = false;
};
</script>
</body>
</html>'''


SIDEBAR_CANDIDATE_HTML = r'''<!doctype html>
<html>
<body>
  <div data-sidebar-item="true">
    <button id="sidebar-model">GPT-5.6 Pro</button>
  </div>
  <main>
    <div id="real-model" role="button" tabindex="0">GPT-5.6 Sol</div>
    <div data-testid="composer"><textarea id="prompt-textarea"></textarea></div>
  </main>
</body>
</html>'''


@pytest.mark.asyncio
@pytest.mark.integration
async def test_chatgpt_aborts_before_click_when_sidebar_item_intercepts_picker():
    playwright = await async_playwright().start()
    try:
        try:
            browser = await playwright.chromium.launch(headless=True)
        except Exception:
            pytest.skip("Playwright Chromium is not installed")
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 800})
            await page.set_content(INTERCEPTED_HTML)
            adapter = AdapterRegistry().create("chatgpt")

            with pytest.raises(AdapterMismatch) as exc_info:
                await adapter._model_options(page)

            message = str(exc_info.value)
            assert "refusing click" in message
            assert "Modelo de conversación" in message
            assert "sidebarItem" in message
            assert await page.evaluate("window.modelPickerClicks") == 0
        finally:
            await browser.close()
    finally:
        await playwright.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_chatgpt_rejects_weak_model_picker_inside_data_sidebar_item():
    playwright = await async_playwright().start()
    try:
        try:
            browser = await playwright.chromium.launch(headless=True)
        except Exception:
            pytest.skip("Playwright Chromium is not installed")
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 800})
            await page.set_content(SIDEBAR_CANDIDATE_HTML)
            adapter = AdapterRegistry().create("chatgpt")

            picker = await adapter._model_picker(page)
            assert await picker.get_attribute("id") == "real-model"
        finally:
            await browser.close()
    finally:
        await playwright.stop()
