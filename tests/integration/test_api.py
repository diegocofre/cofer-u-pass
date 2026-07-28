import asyncio

from fastapi.testclient import TestClient

from cofer_u_pass.api.app import create_app
from cofer_u_pass.domain.models import ProviderModel
from cofer_u_pass.provider.service import RestrictedProviderService


def test_api_requires_bearer_token(config):
    with TestClient(create_app(config)) as client:
        assert client.get("/api/v1/health").status_code == 401
        response = client.get("/api/v1/health", headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_openai_files_surface_and_tool_rejection(config):
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(create_app(config)) as client:
        uploaded = client.post(
            "/v1/files",
            headers=headers,
            data={"purpose": "user_data"},
            files={"file": ("context.txt", b"hello", "text/plain")},
        )
        assert uploaded.status_code == 200
        file_id = uploaded.json()["id"]
        assert client.get(f"/v1/files/{file_id}", headers=headers).json()["filename"] == "context.txt"
        content = client.get(f"/v1/files/{file_id}/content", headers=headers)
        assert content.status_code == 200
        assert content.content == b"hello"

        rejected = client.post(
            "/v1/responses",
            headers=headers,
            json={"model": "chatgpt-main", "input": "hello", "tools": [{"type": "function"}]},
        )
        assert rejected.status_code == 400
        assert "do not support tools" in rejected.json()["detail"]

        deleted = client.delete(f"/v1/files/{file_id}", headers=headers)
        assert deleted.json()["deleted"] is True


def test_openai_models_surface_advertises_discovered_models_and_rejects_invalid_effort(config):
    headers = {"Authorization": "Bearer test-token"}
    app = create_app(config)
    with TestClient(app) as client:
        service = app.state.service
        asyncio.run(service.create_profile("chatgpt-main", "chatgpt"))
        asyncio.run(service.db.update_profile("chatgpt-main", authenticated=True, status="ready"))
        provider = RestrictedProviderService(service)
        provider.catalog.save("chatgpt-main", "chatgpt", [ProviderModel(
            id="gpt-5.6-sol",
            provider="chatgpt",
            display_name="GPT-5.6 Sol",
            supported_efforts=["medium", "high", "xhigh"],
        )])

        models = client.get("/v1/models", headers=headers)
        assert models.status_code == 200
        assert [item["id"] for item in models.json()["data"]] == ["gpt-5.6-sol"]
        assert models.json()["data"][0]["metadata"]["reasoning_efforts"] == ["medium", "high", "xhigh"]

        capabilities = client.get("/v1/models/gpt-5.6-sol/capabilities", headers=headers)
        assert capabilities.status_code == 200
        assert capabilities.json()["capabilities"]["reasoning_efforts"] == ["medium", "high", "xhigh"]

        invalid = client.post(
            "/v1/responses",
            headers=headers,
            json={
                "model": "gpt-5.6-sol",
                "reasoning": {"effort": "banana"},
                "input": "THIS MUST NOT BE SENT",
            },
        )
        assert invalid.status_code == 400
        assert "unsupported reasoning.effort" in invalid.json()["detail"]
