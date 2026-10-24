from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api.models.enums import JobStatus
from api.schemas.scoring import ScoringConfig, TierCounts


class JobCreate(BaseModel):
    """A new job, as the service decides it should be saved."""

    model_config = ConfigDict(frozen=True)

    upload_id: UUID
    total_tasks: int
    status: JobStatus


class JobUpdate(BaseModel):
    """Changes to a job. Only the fields that are passed are written, so a field
    can still be set to None on purpose."""

    model_config = ConfigDict(frozen=True)

    status: JobStatus | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    scoring_config: dict[str, Any] | None = None
    scored_at: datetime | None = None


class TaskCounts(BaseModel):
    """A job's tasks per status. Statuses with no tasks are 0."""

    model_config = ConfigDict(frozen=True)

    pending: int = 0
    in_progress: int = 0
    retrying: int = 0
    succeeded: int = 0
    failed: int = 0


class JobListItem(BaseModel):
    """One job in `GET /api/jobs`."""

    model_config = ConfigDict(frozen=True)

    job_id: int
    upload_id: UUID
    status: JobStatus
    total_tasks: int
    created_at: datetime
    finished_at: datetime | None


class JobResponse(BaseModel):
    """`GET /api/jobs/{job_id}`: the job and its progress."""

    model_config = ConfigDict(frozen=True)

    job_id: int
    upload_id: UUID
    status: JobStatus
    # Why the job FAILED; null otherwise.
    error: str | None
    total_tasks: int
    tasks: TaskCounts
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ScoringSummary(BaseModel):
    """The job's latest scoring: when, with which settings, and the result."""

    model_config = ConfigDict(frozen=True)

    scored_at: datetime
    config: ScoringConfig
    tiers: TierCounts


class JobSummary(BaseModel):
    """`GET /api/jobs/{job_id}/summary`: task counts and the latest scoring."""

    model_config = ConfigDict(frozen=True)

    job_id: int
    status: JobStatus
    total_tasks: int
    tasks: TaskCounts
    # Null until the job is first scored.
    scoring: ScoringSummary | None
