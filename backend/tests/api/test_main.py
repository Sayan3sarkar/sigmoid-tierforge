from fastapi.testclient import TestClient
from pytest import mark

from api.main import create_app
from config import cfg

PREFLIGHT_HEADERS = {
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "content-type",
}


def preflight(origins: list[str], origin: str):
    """Send a CORS preflight for POST /api/uploads to an app allowing `origins`.

    The middleware answers preflights itself, so no database is needed.
    """
    app = create_app(cfg.model_copy(update={"allowed_origins": origins}))
    return TestClient(app).options(
        "/api/uploads", headers={"Origin": origin, **PREFLIGHT_HEADERS}
    )


class TestCors:
    def test_allows_any_origin_by_default(self, client):
        response = client.get(
            "/api/health", headers={"Origin": "http://localhost:5173"}
        )

        assert cfg.allowed_origins == ["*"]
        assert response.headers["access-control-allow-origin"] == "*"

    def test_answers_a_preflight_from_any_origin_by_default(self):
        response = preflight(["*"], "https://anywhere.example.com")

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "*"
        assert "POST" in response.headers["access-control-allow-methods"]

    @mark.parametrize("origin", ["http://localhost:5173", "https://app.example.com"])
    def test_allows_each_configured_origin(self, origin):
        response = preflight(
            ["http://localhost:5173", "https://app.example.com"], origin
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin

    def test_rejects_an_origin_that_is_not_configured(self):
        response = preflight(["http://localhost:5173"], "https://evil.example.com")

        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers
