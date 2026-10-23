from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends

from api.dependencies.db_session import DbSessionDep
from api.models import TaskStatus
from api.repositories.enrichment_task import EnrichmentTaskRepositoryDep
from api.repositories.store import StoreRepositoryDep
from api.schemas.enrichment import EnrichRequest, EnrichResponse
from api.schemas.enrichment_tasks import ClaimedTask, EnrichmentTaskUpdate


class EnrichmentTaskService:
    """Moves enrichment tasks through their statuses:
    PENDING -> IN_PROGRESS -> SUCCEEDED or FAILED.

    Used by the worker, which builds it with repositories on its own session.
    Every method commits its change before returning.
    """

    def __init__(
        self,
        tasks: EnrichmentTaskRepositoryDep,
        stores: StoreRepositoryDep,
        session: DbSessionDep,
    ) -> None:
        self._tasks = tasks
        self._stores = stores
        self._session = session

    async def claim(self, task_id: int, job_id: int) -> ClaimedTask | None:
        """Move a task from PENDING to IN_PROGRESS, commit, and return it with
        its store's enrichment request.

        Returns None, changing nothing, if the task isn't PENDING any more
        (e.g. a duplicate SQS delivery) or its job has FAILED.
        """
        claimed = await self._tasks.update_if_status(
            task_id,
            job_id,
            expected=TaskStatus.PENDING,
            changes=EnrichmentTaskUpdate(status=TaskStatus.IN_PROGRESS),
        )
        if not claimed:
            return None

        task = await self._tasks.get(task_id)
        store = await self._stores.get(task.store_id) if task else None
        if task is None or store is None:
            # Can't happen: the claim just matched the task, and the foreign
            # key keeps its store. Raising rolls the claim back.
            raise LookupError(f"Task {task_id} or its store disappeared")

        # Commit the claim on its own, so it's durable (and other workers see it)
        # before the slow enrichment call that follows.
        await self._session.commit()
        return ClaimedTask(
            task_id=task.id,
            job_id=task.job_id,
            attempt_count=task.attempt_count,
            request=EnrichRequest(
                store_id=store.store_id,
                store_name=store.store_name,
                address=store.address,
                city=store.city,
                state=store.state,
            ),
        )

    async def record_success(self, task: ClaimedTask, result: EnrichResponse) -> bool:
        """Mark a claimed task SUCCEEDED with the store's metrics, and commit.

        Counts the call as one more attempt. Returns False, changing nothing, if
        the task isn't IN_PROGRESS any more or its job has FAILED.
        """
        return await self._finish(
            task,
            EnrichmentTaskUpdate(
                status=TaskStatus.SUCCEEDED,
                attempt_count=task.attempt_count + 1,
                last_error=None,
                estimated_monthly_footfall=result.estimated_monthly_footfall,
                estimated_monthly_revenue=result.estimated_monthly_revenue,
                store_size_sqft=result.store_size_sqft,
                finished_at=datetime.now(UTC),
            ),
        )

    async def record_failure(self, task: ClaimedTask, reason: str) -> bool:
        """Mark a claimed task FAILED with `reason` as its `last_error`, and
        commit. Draft 1 doesn't retry, so FAILED is final.

        Counts the call as one more attempt. Returns False, changing nothing, if
        the task isn't IN_PROGRESS any more or its job has FAILED.
        """
        return await self._finish(
            task,
            EnrichmentTaskUpdate(
                status=TaskStatus.FAILED,
                attempt_count=task.attempt_count + 1,
                last_error=reason,
                finished_at=datetime.now(UTC),
            ),
        )

    async def _finish(self, task: ClaimedTask, changes: EnrichmentTaskUpdate) -> bool:
        """Apply `changes` to an IN_PROGRESS task, and commit.

        Only the worker holding the claim gets here, so writing
        `attempt_count + 1` read at claim time can't lose an increment.
        """
        updated = await self._tasks.update_if_status(
            task.task_id, task.job_id, expected=TaskStatus.IN_PROGRESS, changes=changes
        )
        await self._session.commit()
        return updated


EnrichmentTaskServiceDep = Annotated[EnrichmentTaskService, Depends()]
