"""Health checks behind GET /api/health: one module per checked component."""

from api.services.health_check.health_check_service import (
    HealthCheckService,
    HealthCheckServiceDep,
)
from api.services.health_check.postgres import PostgresHealthCheck
from api.services.health_check.server import ServerHealthCheck

__all__ = [
    "HealthCheckService",
    "HealthCheckServiceDep",
    "PostgresHealthCheck",
    "ServerHealthCheck",
]
