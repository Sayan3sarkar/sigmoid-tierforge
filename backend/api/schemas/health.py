from enum import StrEnum, auto
from typing import Any

from pydantic import BaseModel


class HealthStatus(StrEnum):
    OK = auto()
    ERROR = auto()


class CheckResult(BaseModel):
    status: HealthStatus
    details: dict[str, Any] = {}
    error: str | None = None


class HealthResponse(BaseModel):
    status: HealthStatus
    checks: dict[str, CheckResult]
