from time import monotonic
from typing import Annotated

from fastapi import Depends, Request

from api.schemas.health import CheckResult, HealthStatus
from config import ConfigDep


class ServerHealthCheck:
    """The API process itself: if this runs, the server is up."""

    name = "server"

    def __init__(self, request: Request, config: ConfigDep) -> None:
        self._started_at: float = request.app.state.started_at
        self._config = config

    async def check(self) -> CheckResult:
        return CheckResult(
            status=HealthStatus.OK,
            details={
                "app": self._config.app_name,
                "environment": self._config.environment,
                "uptime_seconds": round(monotonic() - self._started_at, 1),
            },
        )


ServerHealthCheckDep = Annotated[ServerHealthCheck, Depends()]
