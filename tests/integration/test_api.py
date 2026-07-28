from fastapi.testclient import TestClient

from cofer_u_pass.api.app import create_app


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
