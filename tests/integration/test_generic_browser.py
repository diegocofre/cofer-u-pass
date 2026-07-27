from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from cofer_u_pass.application.service import ApplicationService

HTML = b'''<!doctype html><html><body data-cofer-authenticated="true">
<textarea data-cofer-message-input></textarea><button data-cofer-send>Send</button>
<input type="file" data-cofer-attachment><div data-cofer-attachment-ready></div>
<div id="messages"></div>
<script>
document.querySelector('[data-cofer-send]').onclick = () => {
  const input = document.querySelector('[data-cofer-message-input]');
  const u = document.createElement('div'); u.setAttribute('data-cofer-user-message',''); u.textContent=input.value;
  document.querySelector('#messages').appendChild(u); input.value='';
  const r = document.createElement('div'); r.setAttribute('data-cofer-response','');
  document.querySelector('#messages').appendChild(r); document.body.setAttribute('data-cofer-generating','true');
  const parts=['Hello ','from ','generic ','adapter.']; let i=0;
  const timer=setInterval(()=>{ r.textContent += parts[i++]; if(i===parts.length){clearInterval(timer);document.body.removeAttribute('data-cofer-generating');}},120);
};
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers(); self.wfile.write(HTML)
    def log_message(self, fmt, *args):
        pass


@pytest.mark.asyncio
@pytest.mark.integration
async def test_generic_adapter_end_to_end(config, tmp_path):
    service = ApplicationService(config)
    await service.start()
    executable = await service.runtime.chromium_executable()
    if executable is None:
        pytest.skip("Playwright Chromium is not installed")
    server = ThreadingHTTPServer(("127.0.0.1", 9876), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        await service.create_profile("generic-test", "generic")
        protocol = tmp_path / "protocol.yaml"
        protocol.write_text('''protocol_id: generic-test\nversion: 1.0.0\nrequired_capabilities: [conversation.new, message.send, response.stream]\ninput_schema:\n  type: object\n  required: [prompt]\noperations:\n  - type: open_conversation\n  - type: send_message\n    params: {text: "${input.prompt}"}\n  - type: capture_response\n    timeout_seconds: 10\n  - type: finalize\n''', encoding="utf-8")
        run = await service.create_run(protocol, profile_id="generic-test", inputs={"prompt": "hello"})
        done = await service.wait(run.run_id)
        assert done.state.value == "completed", done.error_message
        result = await service.db.get_result(run.run_id)
        assert result is not None
        assert "Hello from generic adapter." in result.text
        events = await service.db.get_events(run.run_id)
        assert any(e.type == "response.delta" for e in events)
    finally:
        server.shutdown(); server.server_close()
        await service.shutdown()
