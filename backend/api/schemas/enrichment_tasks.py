from datetime import datetime
from decimal import Decimal
from enum import StrEnum, auto

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
    lease_expires_at: datetime | None = None


class ClaimedTask(BaseModel):
    """A task the worker has claimed (IN_PROGRESS), with what it needs to enrich
    the store and record the outcome."""

    model_config = ConfigDict(frozen=True)

    task_id: int
    job_id: int
    # Attempts recorded before this one (429s aren't counted); this call's
    # outcome is saved as attempt_count + 1, unless it's a 429.
    attempt_count: int
    # The claim's lease: the outcome is only written while the task still has it.
    lease_expires_at: datetime
    request: EnrichRequest


class ClaimStatus(StrEnum):
    """What came of trying to claim a task, and so what to do with its message."""

    CLAIMED = auto()  # this handler owns the task now: enrich the store
    # Someone else holds it (IN_PROGRESS under a live lease): keep the message,
    # so it comes back and the task is recovered if that handler dies.
    BUSY = auto()
    # Nothing left to do (SUCCEEDED, FAILED, or its job FAILED): drop the message.
    DONE = auto()


class ClaimResult(BaseModel):
    """The outcome of a claim; `task` is set only when CLAIMED."""

    model_config = ConfigDict(frozen=True)

    status: ClaimStatus
    task: ClaimedTask | None = None


class TaskMetrics(BaseModel):
    """The saved metrics of one SUCCEEDED task: what scoring reads."""

    model_config = ConfigDict(frozen=True)

    task_id: int
    estimated_monthly_footfall: int
    estimated_monthly_revenue: Decimal
    store_size_sqft: int
