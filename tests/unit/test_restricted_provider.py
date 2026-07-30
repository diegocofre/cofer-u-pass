from __future__ import annotations

import json

import pytest

from cofer_u_pass.application.service import ApplicationService
from cofer_u_pass.domain.errors import ProtocolError
from cofer_u_pass.domain.models import InferenceSelection, ProviderModel
from cofer_u_pass.provider.service import RestrictedProviderService


@pytest.fixture
def provider(config):
    return RestrictedProviderService(ApplicationService(config))


@pytest.mark.asyncio
async def test_provider_keeps_profile_id_as_unadvertised_legacy_capability_alias(config):
    service = ApplicationService(config)
    await service.start(execute_queued=False)
    try:
        await service.create_profile("chatgpt-main", "chatgpt")
        provider = RestrictedProviderService(service)
        caps = await provider.model_capabilities("chatgpt-main")
        assert caps["legacy_profile_alias"] is True
        assert caps["capabilities"]["text_input"] is True
        assert caps["capabilities"]["file_input"] is True
        assert caps["capabilities"]["tools"] is False
        assert caps["exchange_protocol"] == "cofer-u-pass.exchange/1"
        assert await provider.list_models() == []
    finally:
        await service.shutdown(cooperative=True)


def test_provider_rejects_tools(provider):
    with pytest.raises(ProtocolError, match="do not support tools"):
        provider.compile_request({"model": "chatgpt-main", "input": "hello", "tools": [{"type": "function"}]})


def test_provider_parses_reasoning_effort(provider):
    compiled = provider.compile_request({
        "model": "gpt-5.6-sol",
        "reasoning": {"effort": " High "},
        "input": "hello",
    })
    assert compiled.model == "gpt-5.6-sol"
    assert compiled.effort == "high"


def test_provider_rejects_unknown_public_reasoning_effort(provider):
    with pytest.raises(ProtocolError, match="unsupported reasoning.effort"):
        provider.compile_request({
            "model": "gpt-5.6-sol",
            "reasoning": {"effort": "extreme"},
            "input": "hello",
        })


def test_provider_rejects_reasoning_fields_it_cannot_honor(provider):
    with pytest.raises(ProtocolError, match="unsupported reasoning fields"):
        provider.compile_request({
            "model": "gpt-5.6-sol",
            "reasoning": {"effort": "high", "summary": "auto"},
            "input": "hello",
        })


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


@pytest.mark.asyncio
async def test_discovered_model_catalog_is_advertised_and_resolved_to_profile(config):
    service = ApplicationService(config)
    await service.start(execute_queued=False)
    try:
        await service.create_profile("chatgpt-main", "chatgpt")
        await service.db.update_profile("chatgpt-main", authenticated=True, status="ready")
        provider = RestrictedProviderService(service)
        provider.catalog.save("chatgpt-main", "chatgpt", [ProviderModel(
            id="gpt-5.6-sol",
            provider="chatgpt",
            display_name="GPT-5.6 Sol",
            supported_efforts=["medium", "high", "xhigh"],
        )])

        models = await provider.list_models()
        assert [item["id"] for item in models] == ["gpt-5.6-sol"]
        assert models[0]["metadata"]["reasoning_efforts"] == ["medium", "high", "xhigh"]
        assert models[0]["metadata"]["routing_ambiguous"] is False

        route = await provider.resolve_model("gpt-5.6-sol", "high", allow_refresh=False)
        assert route.profile_id == "chatgpt-main"
        assert route.provider == "chatgpt"
        assert route.selection == InferenceSelection(model="gpt-5.6-sol", effort="high")
        assert route.legacy_profile_alias is False
    finally:
        await service.shutdown(cooperative=True)


@pytest.mark.asyncio
async def test_unsupported_effort_fails_before_run_creation(config):
    service = ApplicationService(config)
    await service.start(execute_queued=False)
    try:
        await service.create_profile("chatgpt-main", "chatgpt")
        await service.db.update_profile("chatgpt-main", authenticated=True, status="ready")
        provider = RestrictedProviderService(service)
        provider.catalog.save("chatgpt-main", "chatgpt", [ProviderModel(
            id="gpt-5.6-sol",
            provider="chatgpt",
            display_name="GPT-5.6 Sol",
            supported_efforts=["medium", "high"],
        )])
        with pytest.raises(ProtocolError, match="does not advertise reasoning effort"):
            await provider.resolve_model("gpt-5.6-sol", "xhigh", allow_refresh=False)
        assert await service.db.list_runs() == []
    finally:
        await service.shutdown(cooperative=True)


@pytest.mark.asyncio
async def test_duplicate_model_routes_fail_as_ambiguous(config):
    service = ApplicationService(config)
    await service.start(execute_queued=False)
    try:
        provider = RestrictedProviderService(service)
        for profile_id in ("chatgpt-a", "chatgpt-b"):
            await service.create_profile(profile_id, "chatgpt")
            await service.db.update_profile(profile_id, authenticated=True, status="ready")
            provider.catalog.save(profile_id, "chatgpt", [ProviderModel(
                id="gpt-5.6-sol",
                provider="chatgpt",
                display_name="GPT-5.6 Sol",
                supported_efforts=["medium", "high"],
            )])
        with pytest.raises(ProtocolError, match="ambiguous"):
            await provider.resolve_model("gpt-5.6-sol", "high", allow_refresh=False)
    finally:
        await service.shutdown(cooperative=True)


def test_internal_provider_protocol_configures_inference_before_send(provider):
    protocol = provider._internal_protocol(
        has_attachments=False,
        wants_artifacts=False,
        selection=InferenceSelection(model="gpt-5.6-sol", effort="high"),
    )
    assert [operation.type for operation in protocol.operations] == [
        "open_conversation",
        "configure_inference",
        "send_message",
        "capture_response",
        "finalize",
    ]
    assert "inference.model.select" in protocol.required_capabilities
    assert "inference.effort.select" in protocol.required_capabilities
    assert "inference.state.verify" in protocol.required_capabilities


@pytest.mark.asyncio
async def test_legacy_profile_alias_rejects_new_reasoning_control(config):
    service = ApplicationService(config)
    await service.start(execute_queued=False)
    try:
        await service.create_profile("chatgpt-main", "chatgpt")
        await service.db.update_profile("chatgpt-main", authenticated=True, status="ready")
        provider = RestrictedProviderService(service)
        with pytest.raises(ProtocolError, match="legacy profile-id model alias"):
            await provider.resolve_model("chatgpt-main", "high", allow_refresh=False)
    finally:
        await service.shutdown(cooperative=True)
