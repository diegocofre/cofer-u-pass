from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from cofer_u_pass.adapters.registry import AdapterRegistry


HTML = r'''<!doctype html>
<html>
<head>
<style>
  body { margin: 0; min-height: 900px; }
  #left-rail {
    position: fixed;
    left: 0;
    top: 0;
    width: 260px;
    height: 100vh;
    overflow: auto;
  }
  main {
    margin-left: 520px;
    padding-top: 260px;
    width: 620px;
  }
  #model-menu, #effort-menu {
    margin-top: 8px;
    width: 260px;
  }
  .history, [role="menuitemradio"] {
    display: block;
    min-height: 32px;
  }
</style>
</head>
<body>
  <div id="left-rail">
    <button class="history">GPT-5.6 Pro</button>
    <button role="menuitem" class="history">Comparison GPT-5.6 Thinking vs Claude</button>
    <button role="menuitem" class="history">High priority project</button>
    <div id="virtualized-history"></div>
  </div>

  <main>
    <div data-testid="composer"><textarea id="prompt-textarea"></textarea></div>

    <button id="upgrade">Upgrade to GPT-5.6 Pro</button>
    <div id="model-trigger" role="button" tabindex="0">GPT-5.6 Sol</div>
    <div id="model-menu" hidden>
      <button role="menuitemradio" data-testid="model-switcher-gpt-5-6-sol" aria-checked="true">GPT-5.6 Sol</button>
      <button role="menuitemradio" data-testid="model-switcher-gpt-5-6-pro" aria-checked="false">GPT-5.6 Pro</button>
    </div>

    <button id="effort-trigger" aria-haspopup="menu">Medium</button>
    <div id="effort-menu" hidden>
      <button role="menuitemradio" aria-checked="true">Medium</button>
      <button role="menuitemradio" aria-checked="false">High</button>
    </div>
  </main>

<script>
window.sidebarClicks = 0;
document.querySelectorAll('#left-rail .history').forEach(item => {
  item.onclick = () => { window.sidebarClicks += 1; };
});

const modelButton = document.querySelector('#model-trigger');
const effortButton = document.querySelector('#effort-trigger');
const modelMenu = document.querySelector('#model-menu');
const effortMenu = document.querySelector('#effort-menu');
const virtualizedHistory = document.querySelector('#virtualized-history');

function closeMenus() { modelMenu.hidden = true; effortMenu.hidden = true; }
function materializeSidebarNoise() {
  virtualizedHistory.replaceChildren();

  const fakeMenu = document.createElement('div');
  fakeMenu.className = 'history-menu';
  fakeMenu.setAttribute('role', 'menu');

  const fakeModel = document.createElement('button');
  fakeModel.className = 'history';
  fakeModel.setAttribute('role', 'menuitemradio');
  fakeModel.textContent = 'GPT-5.6 Thinking';
  fakeModel.onclick = () => { window.sidebarClicks += 1; };

  const fakeEffort = document.createElement('button');
  fakeEffort.className = 'history';
  fakeEffort.setAttribute('role', 'menuitemradio');
  fakeEffort.textContent = 'High';
  fakeEffort.onclick = () => { window.sidebarClicks += 1; };

  fakeMenu.append(fakeModel, fakeEffort);
  virtualizedHistory.append(fakeMenu);
}

modelButton.onclick = () => {
  materializeSidebarNoise();
  const was = modelMenu.hidden;
  closeMenus();
  modelMenu.hidden = !was;
};

effortButton.onclick = () => {
  materializeSidebarNoise();
  const was = effortMenu.hidden;
  closeMenus();
  effortMenu.hidden = !was;
};

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
async def test_chatgpt_scopes_unowned_picker_options_away_from_virtualized_sidebar_noise():
    playwright = await async_playwright().start()
    try:
        try:
            browser = await playwright.chromium.launch(headless=True)
        except Exception:
            pytest.skip("Playwright Chromium is not installed")
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            await page.set_content(HTML)
            adapter = AdapterRegistry().create("chatgpt")

            picker = await adapter._model_picker(page)
            assert await picker.get_attribute("id") == "model-trigger"

            effort_picker = await adapter._effort_picker(page)
            assert effort_picker is not None
            assert await effort_picker.get_attribute("id") == "effort-trigger"

            models = await adapter.discover_models(page)
            assert [model.id for model in models] == ["gpt-5.6-sol", "gpt-5.6-pro"]
            assert models[0].supported_efforts == ["medium", "high"]
            assert models[1].supported_efforts == ["medium", "high"]
            assert await page.evaluate("window.sidebarClicks") == 0
        finally:
            await browser.close()
    finally:
        await playwright.stop()
