from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base


class StoreScore(Base):
    """The score and tier of one successfully enriched store in one job.

    Computed from the task's saved metrics by scoring; every scoring run of a job
    deletes and rewrites all of that job's rows in one transaction.
    """

    __tablename__ = "store_scores"

    job_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("jobs.id", ondelete="CASCADE")
    )
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("enrichment_tasks.id", ondelete="CASCADE")
    )
    score: Mapped[int] = mapped_column(Integer)
    tier: Mapped[str] = mapped_column(Text)
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # One score per store per job; also serves "all scores of a job".
        PrimaryKeyConstraint("job_id", "task_id"),
        # Tier counts per job, and the store list filtered by tier.
        Index("ix_store_scores_job_id_tier", "job_id", "tier"),
    )
