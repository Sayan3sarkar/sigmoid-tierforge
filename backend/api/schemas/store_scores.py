from datetime import datetime

from pydantic import BaseModel, ConfigDict

from api.models.enums import Tier


class StoreScoreCreate(BaseModel):
    """A computed score and tier for one store (task) in one job."""

    model_config = ConfigDict(frozen=True)

    job_id: int
    task_id: int
    score: int
    tier: Tier
    scored_at: datetime
