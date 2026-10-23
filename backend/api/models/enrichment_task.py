from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base
from api.models.enums import TaskStatus


class EnrichmentTask(Base):
    """One store within one job: the unit of work the worker processes.

    Phase 3 adds the enrichment results (footfall, revenue, size) as columns here.
    """

    __tablename__ = "enrichment_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("jobs.id", ondelete="CASCADE")
    )
    store_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stores.id"))
    status: Mapped[str] = mapped_column(Text, default=TaskStatus.PENDING)
    attempt_count: Mapped[int] = mapped_column(Integer, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # One task per store per job; also serves "all tasks of a job" lookups.
        UniqueConstraint("job_id", "store_id"),
        # Progress counts: SELECT status, count(*) ... WHERE job_id = ? GROUP BY status
        Index("ix_enrichment_tasks_job_id_status", "job_id", "status"),
    )
