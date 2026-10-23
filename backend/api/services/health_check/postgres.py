from asyncio import timeout
from logging import getLogger
from time import perf_counter
from typing import Annotated

from fastapi import Depends

from api.repositories.health import HealthRepositoryDep
from api.schemas.health import CheckResult, HealthStatus
from config import ConfigDep

logger = getLogger(__name__)


class PostgresHealthCheck:
    """Postgres reachability: a `SELECT 1` round trip, bounded by a timeout."""

    name = "postgres"

    def __init__(self, repository: HealthRepositoryDep, config: ConfigDep) -> None:
        self._repository = repository
        self._timeout = config.health.postgres_timeout_seconds

    async def check(self) -> CheckResult:
        started = perf_counter()
        try:
            async with timeout(self._timeout):
                await self._repository.ping()
        except TimeoutError:
            logger.warning("Postgres health check timed out after %ss", self._timeout)
            return CheckResult(
                status=HealthStatus.ERROR,
                error=f"Timed out after {self._timeout}s",
            )
        except Exception as e:
            logger.warning("Postgres health check failed", exc_info=e)
            return CheckResult(
                status=HealthStatus.ERROR, error=f"{type(e).__name__}: {e}"
            )

        latency_ms = (perf_counter() - started) * 1000
        return CheckResult(
            status=HealthStatus.OK, details={"latency_ms": round(latency_ms, 2)}
        )


PostgresHealthCheckDep = Annotated[PostgresHealthCheck, Depends()]
