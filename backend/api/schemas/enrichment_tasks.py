from pydantic import BaseModel, ConfigDict

from api.models.enums import TaskStatus


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
