from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from cofer_u_pass.adapters.registry import AdapterRegistry
from cofer_u_pass.domain.errors import AdapterMismatch


HTML = r'''<!doctype html>
<html>
<head>
<style>
  body { margin: 0; }
  aside { position: fixed; left: 0; top: 0; width: 280px; height: 100vh; }
  main { margin-left: 320px; padding-top: 180px; width: 760px; }
  #composer-shell { position: relative; width: 680px; height: 120px; }
  [data-testid="composer"] { position: absolute; left: 0; top: 40px; width: 680px; height: 80px; }
  #effort-trigger { position: absolute; right: 80px; top: 42px; width: 90px; height: 36px; }
  #effort-menu { position: absolute; right: 80px; top: 82px; width: 220px; }
</style>
</head>
<body>
  <aside>
    <a data-sidebar-item="true" href="/c/secret-conversation">
      <button>SECRET GPT-5.6 Pro CHAT</button>
    </a>
  </aside>

  <main>
    <div id="composer-shell">
      <div data-testid="composer"><textarea id="prompt-textarea"></textarea></div>
      <button
        id="effort-trigger"
        aria-haspopup="menu"
        aria-expanded="false"
        aria-controls="effort-menu"
      >High</button>
      <div id="effort-menu" role="menu" hidden>
        <button role="menuitemradio" data-value="low" aria-checked="false">Low</button>
        <button role="menuitemradio" data-value="high" aria-checked="true">High</button>
        <button role="menuitemradio" data-value="xhigh" aria-checked="false">Extra High</button>
      </div>
    </div>
    <div data-model="account-default" data-mode="auto-routing">Provider routing state</div>
    <div data-testid="model-response">PRIVATE CURRENT CHAT CONTENT</div>
  </main>

<script>
window.effortPickerClicks = 0;
window.effortOptionClicks = 0;
const picker = document.querySelector('#effort-trigger');
const menu = document.querySelector('#effort-menu');
picker.onclick = () => {
  window.effortPickerClicks += 1;
  menu.hidden = !menu.hidden;
  picker.setAttribute('aria-expanded', String(!menu.hidden));
};
document.querySelectorAll('#effort-menu [role="menuitemradio"]').forEach(item => {
  item.onclick = () => { window.effortOptionClicks += 1; };
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    menu.hidden = true;
    picker.setAttribute('aria-expanded', 'false');
  }
});
</script>
</body>
</html>'''


@pytest.mark.asyncio
@pytest.mark.integration
async def test_chatgpt_model_picker_failure_captures_effort_menu_without_selecting_options():
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
            assert "Effort picker/menu diagnostic" in message
            assert "low (label='Low'" in message
            assert "high (label='High'" in message
            assert "xhigh (label='Extra High'" in message
            assert "raw_visible_menu_items" in message
            assert "data-value='high'" in message
            assert "data-model='account-default'" in message
            assert "data-mode='auto-routing'" in message
            assert "SECRET GPT-5.6 Pro CHAT" not in message
            assert "/c/secret-conversation" not in message
            assert "PRIVATE CURRENT CHAT CONTENT" not in message
            assert await page.evaluate("window.effortPickerClicks") == 1
            assert await page.evaluate("window.effortOptionClicks") == 0
            assert await page.locator("#effort-menu").is_hidden()
        finally:
            await browser.close()
    finally:
        await playwright.stop()
