from api.schemas.health import CheckResult, HealthStatus
from api.services.health_check import HealthCheckService


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
