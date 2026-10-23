from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from sqlalchemy import insert, select, update

from api.models import EnrichmentTask, Job, JobStatus, TaskStatus
from api.repositories.base import BaseRepository
from api.schemas.enrichment_tasks import EnrichmentTaskCreate, EnrichmentTaskUpdate


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
