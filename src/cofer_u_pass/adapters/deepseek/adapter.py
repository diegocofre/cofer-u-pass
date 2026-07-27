import re
from cofer_u_pass.adapters.base import ProviderAdapter


class DeepSeekAdapter(ProviderAdapter):
    adapter_version = "1.0.0"

    def extract_conversation_id(self, url: str) -> str | None:
        m = re.search(r"/a/chat/s/([A-Za-z0-9_-]+)", url)
        return m.group(1) if m else None
