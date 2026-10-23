from fastapi import APIRouter, Response, status

from api.schemas.health import HealthResponse, HealthStatus
from api.services.health_check import HealthCheckServiceDep

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "A check failed"}},
)
async def health(service: HealthCheckServiceDep, response: Response) -> HealthResponse:
    """Server and Postgres health. Returns 503 if any check fails."""
    result = await service.check()
    if result.status != HealthStatus.OK:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
