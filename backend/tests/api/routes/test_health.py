from api.repositories.health import HealthRepository
from config import cfg


class TestHealthEndpoint:
    def test_returns_200_when_server_and_postgres_are_healthy(self, client):
        response = client.get("/api/health")

        body = response.json()
        assert response.status_code == 200
        assert body["status"] == "ok"
        assert body["checks"]["server"]["status"] == "ok"
        assert body["checks"]["server"]["details"]["app"] == cfg.app_name
        assert body["checks"]["postgres"]["status"] == "ok"
        assert "latency_ms" in body["checks"]["postgres"]["details"]

    def test_returns_503_when_postgres_is_unreachable(self, app, client, mocker):
        repository = mocker.AsyncMock(spec=HealthRepository)
        repository.ping.side_effect = ConnectionRefusedError("Connection refused")
        app.dependency_overrides[HealthRepository] = lambda: repository

        response = client.get("/api/health")

        body = response.json()
        assert response.status_code == 503
        assert body["status"] == "error"
        assert body["checks"]["server"]["status"] == "ok"
        assert body["checks"]["postgres"] == {
            "status": "error",
            "details": {},
            "error": "ConnectionRefusedError: Connection refused",
        }
