import pytest

from cofer_u_pass.adapters.registry import AdapterRegistry


@pytest.mark.parametrize("provider", ["generic", "chatgpt", "gemini", "deepseek"])
def test_adapter_contract_metadata(provider):
    adapter = AdapterRegistry().create(provider)
    assert adapter.provider == provider
    assert adapter.adapter_version == adapter.manifest.adapter_version
    assert adapter.manifest.schema_version == "1.0"
    assert adapter.rules.schema_version == "1.0"
    assert adapter.rules.home_url.startswith(("http://", "https://"))
    assert adapter.allowed_origins
    for required in ["conversation.new", "message.send", "response.stream"]:
        assert required in adapter.capabilities
    assert adapter.rules.authenticated
    assert adapter.rules.message_input
    assert adapter.rules.response
    assert isinstance(adapter.supports_headless_execution, bool)
    assert isinstance(adapter.supports_headless_authentication_check, bool)
