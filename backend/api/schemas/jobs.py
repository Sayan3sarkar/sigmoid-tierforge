from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api.models.enums import JobStatus


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
