from datetime import datetime
from decimal import Decimal
from enum import StrEnum, auto
from typing import Annotated, TypeAlias

from fastapi import Query
from pydantic import BaseModel, ConfigDict

from api.models.enums import TaskStatus, Tier


class StoreRow(BaseModel):
    """One validated store from an uploaded CSV, before it is saved."""

    model_config = ConfigDict(frozen=True)

    store_id: str
    store_name: str
    address: str
    city: str
    state: str
    country: str


class JobStoreFilters(BaseModel):
    """Query filters of `GET /api/jobs/{job_id}/stores`. Both are optional and
    combine with AND."""

    # No extra="forbid": several query models share one query string, and
    # each would reject the others' parameters.
    model_config = ConfigDict(frozen=True)

    status: TaskStatus | None = None
    # Only scored stores have a tier, so this implies SUCCEEDED stores.
    tier: Tier | None = None


# FastAPI dependency: reads `status` and `tier` from the query string.
JobStoreFiltersDep: TypeAlias = Annotated[JobStoreFilters, Query()]


class JobStoreOrder(StrEnum):
    """How a job's store list is ordered; every order ends with `store_id`."""

    SCORE = auto()  # highest score first
    RECENTLY_FINISHED = auto()  # latest finished_at first
    STORE_ID = auto()  # store_id only


class JobStoreItem(BaseModel):
    """One store as it stands in one job, in `GET /api/jobs/{job_id}/stores`.

    Fields that don't apply are null: metrics until the store succeeds,
    `last_error` unless it failed, `score` and `tier` until the job is scored.
    """

    model_config = ConfigDict(frozen=True)

    task_id: int
    store_id: str
    store_name: str
    address: str
    city: str
    state: str
    status: TaskStatus
    attempt_count: int
    last_error: str | None
    estimated_monthly_footfall: int | None
    estimated_monthly_revenue: Decimal | None
    store_size_sqft: int | None
    score: int | None
    tier: Tier | None
    finished_at: datetime | None
