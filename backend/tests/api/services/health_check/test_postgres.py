from asyncio import sleep

from pytest import fixture

from api.repositories.health import HealthRepository
from api.schemas.health import HealthStatus
from api.services.health_check import PostgresHealthCheck
from config import cfg
from config.settings import HealthConfig


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
