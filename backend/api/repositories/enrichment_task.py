from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Select, func, insert, select, update

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

    async def update_if_status(
        self,
        task_id: int,
        job_id: int,
        expected: TaskStatus,
        changes: EnrichmentTaskUpdate,
    ) -> bool:
        """Update one task, writing only the fields set on `changes`, if and only
        if all of these hold:

        - the task has `task_id` and belongs to `job_id`;
        - its status is still `expected`;
        - its job's status isn't FAILED.

        The checks and the write are one UPDATE statement, so two workers handling
        the same task can't both succeed. Reading the status first and updating
        it afterwards would let both see `expected`. Does not commit.

        Returns True if the task was updated. Returns False, changing nothing, if
        any check fails (e.g. a duplicate SQS delivery).
        """
        # The task's job still exists and hasn't FAILED.
        job_not_failed = (
            select(Job.id)
            .where(Job.id == EnrichmentTask.job_id, Job.status != JobStatus.FAILED)
            .exists()
        )
        # Every check is in the WHERE clause; RETURNING tells us whether the row
        # matched.
        result = await self.session.execute(
            update(EnrichmentTask)
            .where(
                EnrichmentTask.id == task_id,
                EnrichmentTask.job_id == job_id,
                EnrichmentTask.status == expected,
                job_not_failed,
            )
            .values(**changes.model_dump(exclude_unset=True))
            .returning(EnrichmentTask.id)
        )
        return result.scalar_one_or_none() is not None


EnrichmentTaskRepositoryDep = Annotated[EnrichmentTaskRepository, Depends()]
