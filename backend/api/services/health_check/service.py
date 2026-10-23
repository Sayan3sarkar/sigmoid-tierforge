from typing import Annotated

from fastapi import Depends

from api.schemas.health import HealthResponse, HealthStatus
from api.services.health_check.postgres import PostgresHealthCheckDep
from api.services.health_check.server import ServerHealthCheckDep


class HealthCheckService:
    """Runs every health check; the overall status is OK only if all of them are."""

    def __init__(
        self, server: ServerHealthCheckDep, postgres: PostgresHealthCheckDep
    ) -> None:
        self._checks = [server, postgres]

    async def check(self) -> HealthResponse:
        results = {check.name: await check.check() for check in self._checks}
        all_ok = all(result.status == HealthStatus.OK for result in results.values())
        return HealthResponse(
            status=HealthStatus.OK if all_ok else HealthStatus.ERROR, checks=results
        )


HealthCheckServiceDep = Annotated[HealthCheckService, Depends()]
