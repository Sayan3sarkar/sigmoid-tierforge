from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Exists, Select, func, insert, or_, select, update

from api.models import EnrichmentTask, Job, JobStatus, Store, StoreScore, TaskStatus
from api.repositories.base import BaseRepository
from api.schemas.enrichment_tasks import (
    EnrichmentTaskCreate,
    EnrichmentTaskUpdate,
    TaskMetrics,
)
from api.schemas.pagination import PageParams
from api.schemas.stores import JobStoreFilters, JobStoreItem, JobStoreOrder


class EnrichmentTaskRepository(BaseRepository):
    async def bulk_create(self, tasks: Sequence[EnrichmentTaskCreate]) -> list[int]:
        """Insert every task in `tasks`, with exactly their fields, in a single
        batched INSERT ... RETURNING.

        Fails as a whole on any database error (e.g. a second task for the same
        store in the same job). Does not commit.

        Returns the new task ids, in the same order as `tasks`.
        """
        result = await self.session.scalars(
            insert(EnrichmentTask).returning(
                EnrichmentTask.id, sort_by_parameter_order=True
            ),
            [task.model_dump() for task in tasks],
        )
        return list(result)

    async def get(self, task_id: int) -> EnrichmentTask | None:
        """Return the task with `task_id`, or None if there is none. Read only."""
        return await self.session.scalar(
            select(EnrichmentTask).where(EnrichmentTask.id == task_id)
        )

    async def list_succeeded_metrics(self, job_id: int) -> list[TaskMetrics]:
        """Return the metrics of every SUCCEEDED task of the job, in one query,
        ordered by task id. Read only."""
        result = await self.session.execute(
            select(
                EnrichmentTask.id,
                EnrichmentTask.estimated_monthly_footfall,
                EnrichmentTask.estimated_monthly_revenue,
                EnrichmentTask.store_size_sqft,
            )
            .where(
                EnrichmentTask.job_id == job_id,
                EnrichmentTask.status == TaskStatus.SUCCEEDED,
            )
            .order_by(EnrichmentTask.id)
        )
        return [
            TaskMetrics(
                task_id=task_id,
                estimated_monthly_footfall=footfall,
                estimated_monthly_revenue=revenue,
                store_size_sqft=size_sqft,
            )
            for task_id, footfall, revenue, size_sqft in result
        ]

    async def list_stores(
        self,
        job_id: int,
        filters: JobStoreFilters,
        order: JobStoreOrder,
        page: PageParams,
    ) -> tuple[list[JobStoreItem], int]:
        """Return one page of the job's stores, each with its task's status,
        metrics and error, and its score and tier if scored; plus the total
        number of stores matching `filters`. Read only.

        Two queries: the page, and the count, both served by the
        (job_id, status) and (job_id, tier) indexes.
        """
        # Labelled with JobStoreItem's field names, so each row maps onto it.
        columns = (
            EnrichmentTask.id.label("task_id"),
            Store.store_id,
            Store.store_name,
            Store.address,
            Store.city,
            Store.state,
            EnrichmentTask.status,
            EnrichmentTask.attempt_count,
            EnrichmentTask.last_error,
            EnrichmentTask.estimated_monthly_footfall,
            EnrichmentTask.estimated_monthly_revenue,
            EnrichmentTask.store_size_sqft,
            StoreScore.score,
            StoreScore.tier,
            EnrichmentTask.finished_at,
        )
        rows = await self.session.execute(
            self._filtered(select(*columns), job_id, filters)
            .order_by(*self._ordering(order))
            .offset(page.offset)
            .limit(page.page_size)
        )
        total = await self.session.scalar(
            self._filtered(select(func.count()), job_id, filters)
        )
        items = [JobStoreItem.model_validate(dict(row._mapping)) for row in rows]
        return items, total or 0

    @staticmethod
    def _filtered(query: Select, job_id: int, filters: JobStoreFilters) -> Select:
        """Join a job's tasks to their stores and (if scored) their scores, and
        apply `filters`."""
        query = (
            query.select_from(EnrichmentTask)
            .join(Store, Store.id == EnrichmentTask.store_id)
            .outerjoin(
                StoreScore,
                (StoreScore.job_id == EnrichmentTask.job_id)
                & (StoreScore.task_id == EnrichmentTask.id),
            )
            .where(EnrichmentTask.job_id == job_id)
        )
        if filters.status is not None:
            query = query.where(EnrichmentTask.status == filters.status)
        if filters.tier is not None:
            query = query.where(StoreScore.tier == filters.tier)
        return query

    @staticmethod
    def _ordering(order: JobStoreOrder) -> tuple:
        """ORDER BY columns for `order`; `store_id` breaks ties."""
        match order:
            case JobStoreOrder.SCORE:
                return (StoreScore.score.desc().nulls_last(), Store.store_id)
            case JobStoreOrder.RECENTLY_FINISHED:
                return (EnrichmentTask.finished_at.desc().nulls_last(), Store.store_id)
            case JobStoreOrder.STORE_ID:
                return (Store.store_id,)

    async def count_by_status(self, job_id: int) -> dict[TaskStatus, int]:
        """Count the job's tasks per status, in one grouped query served by the
        (job_id, status) index. Read only.

        Statuses with no tasks are left out; a job with no tasks gives {}.
        """
        result = await self.session.execute(
            select(EnrichmentTask.status, func.count())
            .where(EnrichmentTask.job_id == job_id)
            .group_by(EnrichmentTask.status)
        )
        return {TaskStatus(status): count for status, count in result}

    async def claim(
        self, task_id: int, job_id: int, lease_seconds: float
    ) -> datetime | None:
        """Claim one task for a handler: set it IN_PROGRESS with a lease ending
        `lease_seconds` from now, if and only if all of these hold:

        - the task has `task_id` and belongs to `job_id`;
        - it's PENDING or RETRYING, or IN_PROGRESS with an expired lease (the
          handler that claimed it is presumed dead, so it's taken over);
        - its job's status isn't FAILED.

        One UPDATE statement, so of two handlers claiming the same task only one
        can succeed: the second waits for the first's row lock, then re-checks
        the conditions against the claimed row, which no longer matches. The
        lease is computed and compared with the database's clock (now()), so
        clocks on worker machines don't matter. Does not commit.

        Returns the new lease, which the handler must present to record the
        outcome (see update_if_status), or None, changing nothing, if any check
        fails.
        """
        claimable = or_(
            EnrichmentTask.status.in_((TaskStatus.PENDING, TaskStatus.RETRYING)),
            (EnrichmentTask.status == TaskStatus.IN_PROGRESS)
            & (EnrichmentTask.lease_expires_at < func.now()),
        )
        result = await self.session.execute(
            update(EnrichmentTask)
            .where(
                EnrichmentTask.id == task_id,
                EnrichmentTask.job_id == job_id,
                claimable,
                self._job_not_failed(),
            )
            .values(
                status=TaskStatus.IN_PROGRESS,
                lease_expires_at=func.now() + timedelta(seconds=lease_seconds),
            )
            .returning(EnrichmentTask.lease_expires_at)
        )
        return result.scalar_one_or_none()

    async def is_unfinished(self, task_id: int, job_id: int) -> bool:
        """True if the task exists, belongs to `job_id`, hasn't SUCCEEDED or
        FAILED yet, and its job hasn't FAILED: i.e. it still needs work. Read only.
        """
        return bool(
            await self.session.scalar(
                select(
                    select(EnrichmentTask.id)
                    .where(
                        EnrichmentTask.id == task_id,
                        EnrichmentTask.job_id == job_id,
                        EnrichmentTask.status.in_(TaskStatus.unfinished()),
                        self._job_not_failed(),
                    )
                    .exists()
                )
            )
        )

    async def update_if_status(
        self,
        task_id: int,
        job_id: int,
        expected: TaskStatus,
        changes: EnrichmentTaskUpdate,
        lease: datetime | None = None,
    ) -> bool:
        """Update one task, writing only the fields set on `changes`, if and only
        if all of these hold:

        - the task has `task_id` and belongs to `job_id`;
        - its status is still `expected`;
        - with `lease`: its lease is still exactly `lease`, i.e. nobody has taken
          the task over since this handler claimed it;
        - its job's status isn't FAILED.

        The checks and the write are one UPDATE statement, so two workers handling
        the same task can't both succeed. Reading the status first and updating
        it afterwards would let both see `expected`. Does not commit.

        Returns True if the task was updated. Returns False, changing nothing, if
        any check fails (e.g. a duplicate SQS delivery, or a late result from a
        handler whose task was taken over).
        """
        conditions = [
            EnrichmentTask.id == task_id,
            EnrichmentTask.job_id == job_id,
            EnrichmentTask.status == expected,
            self._job_not_failed(),
        ]
        if lease is not None:
            conditions.append(EnrichmentTask.lease_expires_at == lease)
        # Every check is in the WHERE clause; RETURNING tells us whether the row
        # matched.
        result = await self.session.execute(
            update(EnrichmentTask)
            .where(*conditions)
            .values(**changes.model_dump(exclude_unset=True))
            .returning(EnrichmentTask.id)
        )
        return result.scalar_one_or_none() is not None

    async def fail_unfinished(
        self, job_id: int, reason: str, finished_at: datetime
    ) -> int:
        """Mark every unfinished task of the job (PENDING, IN_PROGRESS or
        RETRYING) FAILED with `reason`, in one UPDATE, ending any lease. Tasks
        that already SUCCEEDED or FAILED are untouched. Does not commit.

        Returns the number of tasks failed.
        """
        result = await self.session.execute(
            update(EnrichmentTask)
            .where(
                EnrichmentTask.job_id == job_id,
                EnrichmentTask.status.in_(TaskStatus.unfinished()),
            )
            .values(
                status=TaskStatus.FAILED,
                last_error=reason,
                finished_at=finished_at,
                lease_expires_at=None,
            )
            .returning(EnrichmentTask.id)
        )
        return len(result.all())

    @staticmethod
    def _job_not_failed() -> Exists:
        """The task's job still exists and hasn't FAILED."""
        return (
            select(Job.id)
            .where(Job.id == EnrichmentTask.job_id, Job.status != JobStatus.FAILED)
            .exists()
        )


EnrichmentTaskRepositoryDep = Annotated[EnrichmentTaskRepository, Depends()]
