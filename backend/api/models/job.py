from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Integer, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base
from api.models.enums import JobStatus


class Job(Base):
    """One enrichment run over all stores of an upload. Created by the upload."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    upload_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    status: Mapped[str] = mapped_column(Text, default=JobStatus.PENDING)
    total_tasks: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # The settings the job's stores were last scored with (a ScoringConfig);
    # null until the job is first scored. Only the latest is kept.
    scoring_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # When the job was last scored; null until then.
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Failed enrichment calls in a row across the job's tasks; any success
    # resets it. The circuit breaker fails the job when it reaches the threshold.
    consecutive_failures: Mapped[int] = mapped_column(Integer, server_default="0")
