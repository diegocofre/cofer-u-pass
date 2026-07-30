from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from cofer_u_pass.adapters.registry import AdapterRegistry


HTML = r'''<!doctype html>
<html>
<body>
  <div data-testid="composer"><textarea id="prompt-textarea"></textarea></div>

  <aside id="sidebar">
    <button role="menuitem" class="history">Comparison GPT-5.6 Thinking vs Claude</button>
    <button role="menuitem" class="history">GPT-5.6 Pro migration notes</button>
    <button role="menuitem" class="history">High priority project</button>
  </aside>

  <button id="upgrade">Upgrade to GPT-5.6 Pro</button>
  <div id="model-trigger" role="button" tabindex="0">GPT-5.6 Sol</div>
  <div id="model-menu" hidden>
    <button role="menuitemradio" data-testid="model-switcher-gpt-5-6-sol" aria-checked="true">GPT-5.6 Sol</button>
    <button role="menuitemradio" data-testid="model-switcher-gpt-5-6-pro" aria-checked="false">GPT-5.6 Pro</button>
  </div>

  <button data-testid="intelligence-picker">Medium</button>
  <div id="effort-menu" hidden>
    <button role="menuitemradio" aria-checked="true">Medium</button>
    <button role="menuitemradio" aria-checked="false">High</button>
  </div>

<script>
window.sidebarClicks = 0;
document.querySelectorAll('#sidebar .history').forEach(item => {
  item.onclick = () => { window.sidebarClicks += 1; };
});

const modelButton = document.querySelector('#model-trigger');
const effortButton = document.querySelector('[data-testid="intelligence-picker"]');
const modelMenu = document.querySelector('#model-menu');
const effortMenu = document.querySelector('#effort-menu');

function closeMenus() { modelMenu.hidden = true; effortMenu.hidden = true; }
modelButton.onclick = () => { const was = modelMenu.hidden; closeMenus(); modelMenu.hidden = !was; };
effortButton.onclick = () => { const was = effortMenu.hidden; closeMenus(); effortMenu.hidden = !was; };

document.querySelectorAll('#model-menu [role="menuitemradio"]').forEach(item => {
  item.onclick = () => {
    document.querySelectorAll('#model-menu [role="menuitemradio"]').forEach(x => x.setAttribute('aria-checked','false'));
    item.setAttribute('aria-checked','true');
    modelButton.textContent = item.textContent;
    closeMenus();
  };
});

document.querySelectorAll('#effort-menu [role="menuitemradio"]').forEach(item => {
  item.onclick = () => {
    document.querySelectorAll('#effort-menu [role="menuitemradio"]').forEach(x => x.setAttribute('aria-checked','false'));
    item.setAttribute('aria-checked','true');
    effortButton.textContent = item.textContent;
    closeMenus();
  };
});

document.addEventListener('keydown', event => { if (event.key === 'Escape') closeMenus(); });
</script>
</body>
</html>'''


@pytest.mark.asyncio
@pytest.mark.integration
async def test_chatgpt_scopes_fallback_picker_options_to_newly_revealed_menu_items():
    playwright = await async_playwright().start()
    try:
        try:
            browser = await playwright.chromium.launch(headless=True)
        except Exception:
            pytest.skip("Playwright Chromium is not installed")
        try:
            page = await browser.new_page()
            await page.set_content(HTML)
            adapter = AdapterRegistry().create("chatgpt")

            picker = await adapter._model_picker(page)
            assert await picker.get_attribute("id") == "model-trigger"

            models = await adapter.discover_models(page)
            assert [model.id for model in models] == ["gpt-5.6-sol", "gpt-5.6-pro"]
            assert models[0].supported_efforts == ["medium", "high"]
            assert models[1].supported_efforts == ["medium", "high"]
            assert await page.evaluate("window.sidebarClicks") == 0
        finally:
            await browser.close()
    finally:
        await playwright.stop()
