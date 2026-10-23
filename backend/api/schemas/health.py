from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class HealthStatus(StrEnum):
    OK = "ok"
    ERROR = "error"


class CheckResult(BaseModel):
    status: HealthStatus
    details: dict[str, Any] = {}
    error: str | None = None


class HealthResponse(BaseModel):
    status: HealthStatus
    checks: dict[str, CheckResult]
