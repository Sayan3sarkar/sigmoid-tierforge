from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MetricBars(BaseModel):
    """The minimum value of each metric that counts as strong. A store meets a
    bar when its value is greater than or equal to it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    footfall: int = Field(ge=0)
    revenue: float = Field(ge=0)
    size_sqft: int = Field(ge=0)


class MetricWeights(BaseModel):
    """Points a store earns for meeting each bar. Each is 0–100 and the three add
    up to exactly 100, so a score is always 0–100."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    footfall: int = Field(ge=0, le=100)
    revenue: int = Field(ge=0, le=100)
    size_sqft: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def add_up_to_100(self) -> Self:
        total = self.footfall + self.revenue + self.size_sqft
        if total != 100:
            raise ValueError(f"weights must add up to 100, not {total}")
        return self


class TierThresholds(BaseModel):
    """Minimum scores for the Large and Medium tiers; anything below Medium is
    Small. 0 <= medium_min <= large_min <= 100."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    large_min: int = Field(ge=0, le=100)
    medium_min: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def medium_not_above_large(self) -> Self:
        if self.medium_min > self.large_min:
            raise ValueError(
                f"medium_min ({self.medium_min}) must not be above "
                f"large_min ({self.large_min})"
            )
        return self


class ScoringConfig(BaseModel):
    """Body of `POST /api/jobs/{job_id}/scoring`: the user's scoring settings.

    Also saved on the job (`jobs.scoring_config`) as the settings its stores
    were last scored with.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    bars: MetricBars
    weights: MetricWeights
    tiers: TierThresholds


class TierCounts(BaseModel):
    """Number of scored stores in each tier."""

    model_config = ConfigDict(frozen=True)

    large: int = 0
    medium: int = 0
    small: int = 0


class ScoringResponse(BaseModel):
    """The result of scoring a job: how many stores were scored, and how they
    split across tiers."""

    model_config = ConfigDict(frozen=True)

    job_id: int
    # Stores scored: the job's SUCCEEDED tasks. Failed stores get no score.
    scored_count: int
    tiers: TierCounts
    config: ScoringConfig
    scored_at: datetime
