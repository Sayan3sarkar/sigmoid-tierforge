from api.schemas.health import HealthStatus
from api.services.health_check import ServerHealthCheck
from config import cfg


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
