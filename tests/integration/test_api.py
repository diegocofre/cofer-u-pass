from fastapi.testclient import TestClient

from cofer_u_pass.api.app import create_app


def test_api_requires_bearer_token(config):
    with TestClient(create_app(config)) as client:
        assert client.get("/api/v1/health").status_code == 401
        response = client.get("/api/v1/health", headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
