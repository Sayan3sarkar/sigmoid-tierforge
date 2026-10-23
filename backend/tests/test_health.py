from asyncio import sleep

from pytest import fixture

from api.repositories.health import HealthRepository
from api.schemas.health import CheckResult, HealthStatus
from api.services.health_check import (
    HealthCheckService,
    PostgresHealthCheck,
    ServerHealthCheck,
)
from config import cfg
from config.settings import HealthConfig


class TestServerHealthCheck:
    async def test_reports_ok_with_app_details(self, mocker):
        mocker.patch("api.services.health_check.server.monotonic", return_value=110.0)
        request = mocker.Mock()
        request.app.state.started_at = 100.0

        result = await ServerHealthCheck(request, cfg).check()

        assert result.status == HealthStatus.OK
        assert result.details == {
            "app": cfg.app_name,
            "environment": cfg.environment,
            "uptime_seconds": 10.0,
        }


class TestPostgresHealthCheck:
    @fixture
    def repository(self, mocker):
        return mocker.AsyncMock(spec=HealthRepository)

    async def test_reports_ok_with_latency_when_ping_succeeds(self, repository):
        result = await PostgresHealthCheck(repository, cfg).check()

        assert result.status == HealthStatus.OK
        assert result.details["latency_ms"] >= 0
        assert result.error is None
        repository.ping.assert_awaited_once()

    async def test_reports_error_when_ping_raises(self, repository):
        repository.ping.side_effect = ConnectionRefusedError("Connection refused")

        result = await PostgresHealthCheck(repository, cfg).check()

        assert result.status == HealthStatus.ERROR
        assert result.error == "ConnectionRefusedError: Connection refused"

    async def test_reports_error_when_ping_times_out(self, repository):
        async def slow_ping():
            await sleep(1)

        repository.ping.side_effect = slow_ping
        config = cfg.model_copy(
            update={"health": HealthConfig(postgres_timeout_seconds=0.01)}
        )

        result = await PostgresHealthCheck(repository, config).check()

        assert result.status == HealthStatus.ERROR
        assert result.error == "Timed out after 0.01s"


class TestHealthCheckService:
    @staticmethod
    def make_check(mocker, name: str, status: HealthStatus):
        check = mocker.Mock()
        check.name = name
        check.check = mocker.AsyncMock(return_value=CheckResult(status=status))
        return check

    async def test_overall_ok_when_every_check_is_ok(self, mocker):
        server = self.make_check(mocker, "server", HealthStatus.OK)
        postgres = self.make_check(mocker, "postgres", HealthStatus.OK)

        result = await HealthCheckService(server, postgres).check()

        assert result.status == HealthStatus.OK
        assert set(result.checks) == {"server", "postgres"}

    async def test_overall_error_when_any_check_fails(self, mocker):
        server = self.make_check(mocker, "server", HealthStatus.OK)
        postgres = self.make_check(mocker, "postgres", HealthStatus.ERROR)

        result = await HealthCheckService(server, postgres).check()

        assert result.status == HealthStatus.ERROR
        assert result.checks["server"].status == HealthStatus.OK
        assert result.checks["postgres"].status == HealthStatus.ERROR


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
