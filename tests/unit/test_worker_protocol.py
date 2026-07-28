from __future__ import annotations

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
    from cofer_u_pass.provider.worker import _file_ids

    assert _file_ids({"metadata": {"cofer_protocol_file": "file-protocol123"}}) == {"file-protocol123"}
