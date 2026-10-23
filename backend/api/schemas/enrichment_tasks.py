from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from api.models.enums import TaskStatus
from api.schemas.enrichment import EnrichRequest


class EnrichmentTaskCreate(BaseModel):
    """A new task: one store within one job."""

    model_config = ConfigDict(frozen=True)

    job_id: int
    store_id: int
    status: TaskStatus


class EnrichmentTaskUpdate(BaseModel):
    """Changes to a task. Only the fields that are passed are written, so a field
    can still be set to None on purpose."""

    model_config = ConfigDict(frozen=True)

    status: TaskStatus | None = None
    attempt_count: int | None = None
    last_error: str | None = None
    estimated_monthly_footfall: int | None = None
    estimated_monthly_revenue: Decimal | None = None
    store_size_sqft: int | None = None
    finished_at: datetime | None = None


class ClaimedTask(BaseModel):
    """A task the worker has claimed (IN_PROGRESS), with what it needs to enrich
    the store and record the outcome."""

    model_config = ConfigDict(frozen=True)

    task_id: int
    job_id: int
    # Calls made before this one; the outcome is saved as attempt_count + 1.
    attempt_count: int
    request: EnrichRequest


class TaskMetrics(BaseModel):
    """The saved metrics of one SUCCEEDED task: what scoring reads."""

    model_config = ConfigDict(frozen=True)

    task_id: int
    estimated_monthly_footfall: int
    estimated_monthly_revenue: Decimal
    store_size_sqft: int
