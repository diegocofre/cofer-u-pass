from __future__ import annotations

import json

import pytest

from cofer_u_pass.application.service import ApplicationService
from cofer_u_pass.domain.errors import ProtocolError
from cofer_u_pass.provider.service import RestrictedProviderService


@pytest.fixture
def provider(config):
    return RestrictedProviderService(ApplicationService(config))


@pytest.mark.asyncio
async def test_provider_lists_profiles_with_restricted_capabilities(config):
    service = ApplicationService(config)
    await service.start(execute_queued=False)
    try:
        await service.create_profile("chatgpt-main", "chatgpt")
        provider = RestrictedProviderService(service)
        caps = await provider.model_capabilities("chatgpt-main")
        assert caps["capabilities"]["text_input"] is True
        assert caps["capabilities"]["file_input"] is True
        assert caps["capabilities"]["tools"] is False
        assert caps["exchange_protocol"] == "cofer-u-pass.exchange/1"
    finally:
        await service.shutdown(cooperative=True)


def test_provider_rejects_tools(provider):
    with pytest.raises(ProtocolError, match="do not support tools"):
        provider.compile_request({"model": "chatgpt-main", "input": "hello", "tools": [{"type": "function"}]})


def test_provider_parses_protocol_and_file_ids(provider, config, tmp_path):
    uploaded = provider.files.put_stream(__import__("io").BytesIO(b"hello"), filename="notes.txt")
    protocol = {
        "schema": "cofer-u-pass.exchange/1",
        "output": {"kind": "bundle", "filename": "architecture.zip", "required_files": ["SPEC.md"]},
    }
    compiled = provider.compile_request({
        "model": "chatgpt-main",
        "metadata": {"cofer_protocol": json.dumps(protocol)},
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Design this"},
                {"type": "input_file", "file_id": uploaded.id},
            ],
        }],
    })
    assert compiled.prompt.endswith("Design this")
    assert compiled.input_paths == [provider.files.content_path(uploaded.id)]
    assert compiled.protocol.output.filename == "architecture.zip"


def test_output_instruction_is_mechanical_only(provider):
    protocol = provider._parse_protocol({"cofer_protocol": json.dumps({
        "schema": "cofer-u-pass.exchange/1",
        "output": {"kind": "bundle", "filename": "review.zip", "required_files": ["CODE_REVIEW.md"]},
    })})
    text = provider._output_instruction(protocol)
    assert "CODE_REVIEW.md" in text
    assert "review the code" not in text.lower()


def test_compile_request_rejects_non_object_metadata(provider):
    with pytest.raises(ProtocolError, match="metadata must be a JSON object"):
        provider.compile_request({"model": "chatgpt-main", "input": "hello", "metadata": "bad"})


def test_protocol_can_be_loaded_from_file_id(provider, tmp_path):
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(
        json.dumps({
            "schema": "cofer-u-pass.exchange/1",
            "output": {"kind": "bundle", "filename": "result.zip", "required_files": ["SPEC.md"]},
        }),
        encoding="utf-8",
    )
    compiled = provider.compile_request(
        {
            "model": "chatgpt-main",
            "input": "design it",
            "metadata": {"cofer_protocol_file": "file-protocol"},
        },
        resolved_files={"file-protocol": protocol_path},
    )
    assert compiled.protocol.output.kind == "bundle"
    assert compiled.protocol.output.required_files == ["SPEC.md"]


def test_protocol_rejects_inline_and_file_at_once(provider, tmp_path):
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text('{"schema":"cofer-u-pass.exchange/1"}', encoding="utf-8")
    with pytest.raises(ProtocolError, match="either"):
        provider.compile_request(
            {
                "model": "chatgpt-main",
                "input": "design it",
                "metadata": {
                    "cofer_protocol": '{"schema":"cofer-u-pass.exchange/1"}',
                    "cofer_protocol_file": "file-protocol",
                },
            },
            resolved_files={"file-protocol": protocol_path},
        )
