from __future__ import annotations

import pytest

from cofer_u_pass.application.service import ApplicationService
from cofer_u_pass.domain.models import ProviderModel
from cofer_u_pass.provider.worker import BridgeWorker, _file_ids


def test_worker_discovers_nested_file_ids():
    body = {"input": [{"content": [{"type": "input_file", "file_id": "file-a"}]}], "other": {"file_id": "file-b"}}
    assert _file_ids(body) == {"file-a", "file-b"}


def test_worker_publishes_machine_readable_artifact_marker():
    body = {
        "output_text": "done",
        "output": [{"content": [{"type": "output_text", "text": "done"}]}],
        "metadata": {},
    }
    artifacts = [{"id": "file-out", "filename": "result.zip"}]
    BridgeWorker._publish_artifact_refs(body, artifacts)
    assert "<cofer_artifacts>" in body["output_text"]
    assert "file-out" in body["output"][0]["content"][0]["text"]


def test_file_ids_include_protocol_file_reference():
    assert _file_ids({"metadata": {"cofer_protocol_file": "file-protocol123"}}) == {"file-protocol123"}


@pytest.mark.asyncio
async def test_worker_profile_registration_adds_models_without_removing_legacy_fields(config):
    service = ApplicationService(config)
    await service.start(execute_queued=False)
    try:
        await service.create_profile("chatgpt-main", "chatgpt")
        await service.db.update_profile("chatgpt-main", authenticated=True, status="ready")
        worker = BridgeWorker(
            service,
            bridge_url="http://127.0.0.1:4011",
            token="test-key",
            profiles=["chatgpt-main"],
            worker_id="worker-test",
        )
        worker.provider.catalog.save("chatgpt-main", "chatgpt", [ProviderModel(
            id="gpt-5.6-sol",
            provider="chatgpt",
            display_name="GPT-5.6 Sol",
            supported_efforts=["medium", "high", "xhigh"],
        )])

        payload = await worker._profile_registration("chatgpt-main")
        assert payload["profile_id"] == "chatgpt-main"
        assert payload["provider"] == "chatgpt"
        assert payload["status"] == "ready"
        assert payload["capabilities"]["tools"] is False
        assert payload["models"] == [{
            "id": "gpt-5.6-sol",
            "display_name": "GPT-5.6 Sol",
            "reasoning_efforts": ["medium", "high", "xhigh"],
        }]
        assert payload["catalog_updated_at"]
        assert payload["catalog_error"] is None
    finally:
        await service.shutdown(cooperative=True)


@pytest.mark.asyncio
async def test_worker_profile_capabilities_do_not_route_through_colliding_model_id(config):
    service = ApplicationService(config)
    await service.start(execute_queued=False)
    try:
        await service.create_profile("gpt-collision", "chatgpt")
        await service.db.update_profile("gpt-collision", authenticated=True, status="ready")
        worker = BridgeWorker(
            service,
            bridge_url="http://127.0.0.1:4011",
            token="test-key",
            profiles=["gpt-collision"],
            worker_id="worker-test",
        )
        worker.provider.catalog.save("gpt-collision", "chatgpt", [ProviderModel(
            id="gpt-collision",
            provider="chatgpt",
            display_name="GPT Collision",
            supported_efforts=["high"],
        )])

        payload = await worker._profile_registration("gpt-collision")
        assert payload["profile_id"] == "gpt-collision"
        assert payload["capabilities"]["tools"] is False
        assert payload["models"][0]["id"] == "gpt-collision"
    finally:
        await service.shutdown(cooperative=True)


@pytest.mark.asyncio
async def test_worker_registration_surfaces_catalog_error_without_stale_models(config):
    service = ApplicationService(config)
    await service.start(execute_queued=False)
    try:
        await service.create_profile("chatgpt-main", "chatgpt")
        await service.db.update_profile("chatgpt-main", authenticated=True, status="ready")
        worker = BridgeWorker(
            service,
            bridge_url="http://127.0.0.1:4011",
            token="test-key",
            profiles=["chatgpt-main"],
            worker_id="worker-test",
        )
        worker.provider.catalog.save_error("chatgpt-main", "chatgpt", "AdapterMismatch: picker changed")
        payload = await worker._profile_registration("chatgpt-main")
        assert payload["models"] == []
        assert payload["catalog_error"] == "AdapterMismatch: picker changed"
    finally:
        await service.shutdown(cooperative=True)
