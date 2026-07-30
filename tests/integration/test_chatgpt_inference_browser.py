from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from cofer_u_pass.adapters.registry import AdapterRegistry
from cofer_u_pass.domain.errors import AdapterMismatch
from cofer_u_pass.domain.models import InferenceSelection


HTML = r'''<!doctype html>
<html>
<body>
  <div data-testid="composer"><textarea id="prompt-textarea"></textarea></div>

  <button data-testid="model-switcher-dropdown-button" aria-haspopup="menu">GPT-5.6 Sol</button>
  <div id="model-menu" hidden>
    <button role="menuitemradio" data-testid="model-switcher-gpt-5-6-sol" aria-checked="true">GPT-5.6 Sol</button>
    <button role="menuitemradio" data-testid="model-switcher-gpt-5-6-pro" aria-checked="false">GPT-5.6 Pro</button>
    <button role="menuitem">Configure</button>
  </div>

  <button data-testid="intelligence-picker" aria-haspopup="menu">Medium</button>
  <div id="effort-menu" hidden>
    <button role="menuitemradio" data-effort="medium" aria-checked="true">Medium</button>
    <button role="menuitemradio" data-effort="high" aria-checked="false">High</button>
    <button role="menuitemradio" data-effort="xhigh" aria-checked="false">Extra High</button>
  </div>

<script>
const modelButton = document.querySelector('[data-testid="model-switcher-dropdown-button"]');
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


async def _page_or_skip():
    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.launch(headless=True)
    except Exception:
        await playwright.stop()
        pytest.skip("Playwright Chromium is not installed")
    page = await browser.new_page()
    await page.set_content(HTML)
    return playwright, browser, page


@pytest.mark.asyncio
@pytest.mark.integration
async def test_chatgpt_discovers_models_efforts_and_restores_original_state():
    playwright, browser, page = await _page_or_skip()
    try:
        adapter = AdapterRegistry().create("chatgpt")
        models = await adapter.discover_models(page)
        assert [model.id for model in models] == ["gpt-5.6-sol", "gpt-5.6-pro"]
        assert models[0].supported_efforts == ["medium", "high", "xhigh"]
        assert models[1].supported_efforts == ["medium", "high", "xhigh"]

        restored = await adapter.read_inference_state(page)
        assert restored is not None
        assert restored.model == "gpt-5.6-sol"
        assert restored.effort == "medium"
        assert restored.verified is True
    finally:
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_chatgpt_configures_and_verifies_requested_inference_state():
    playwright, browser, page = await _page_or_skip()
    try:
        adapter = AdapterRegistry().create("chatgpt")
        evidence = await adapter.configure_inference(
            page, InferenceSelection(model="gpt-5.6-pro", effort="high")
        )
        assert evidence.data["verified"] is True
        assert evidence.data["effective_model"] == "gpt-5.6-pro"
        assert evidence.data["effective_effort"] == "high"

        state = await adapter.read_inference_state(page)
        assert state is not None
        assert state.model == "gpt-5.6-pro"
        assert state.effort == "high"
    finally:
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_chatgpt_unknown_model_fails_closed():
    playwright, browser, page = await _page_or_skip()
    try:
        adapter = AdapterRegistry().create("chatgpt")
        with pytest.raises(AdapterMismatch, match="not selectable"):
            await adapter.configure_inference(
                page, InferenceSelection(model="gpt-does-not-exist", effort="high")
            )
    finally:
        await browser.close()
        await playwright.stop()
