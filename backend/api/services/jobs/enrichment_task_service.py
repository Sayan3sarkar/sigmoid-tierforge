from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends

from api.dependencies.db_session import DbSessionDep
from api.models import TaskStatus
from api.repositories.enrichment_task import EnrichmentTaskRepositoryDep
from api.repositories.store import StoreRepositoryDep
from api.schemas.enrichment import EnrichRequest, EnrichResponse
from api.schemas.enrichment_tasks import (
    ClaimedTask,
    ClaimResult,
    ClaimStatus,
    EnrichmentTaskUpdate,
)
from config import ConfigDep


class EnrichmentTaskService:
    """Moves enrichment tasks through their statuses:
    PENDING -> IN_PROGRESS -> SUCCEEDED or FAILED, with
    IN_PROGRESS -> RETRYING -> IN_PROGRESS for each retry.

    A claim gives the handler a lease on the task; every outcome is written only
    while the task still has that lease, so a handler whose task was taken over
    (its lease expired) can't overwrite the new owner's work.

    Used by the worker, which builds it with repositories on its own session.
    Every method that changes a task commits before returning.
    """

    def __init__(
        self,
        tasks: EnrichmentTaskRepositoryDep,
        stores: StoreRepositoryDep,
        session: DbSessionDep,
        config: ConfigDep,
    ) -> None:
        self._tasks = tasks
        self._stores = stores
        self._session = session
        self._config = config.enrichment

    async def claim(self, task_id: int, job_id: int) -> ClaimResult:
        """Claim a task: set it IN_PROGRESS under a new lease, commit, and return
        it with its store's enrichment request.

        Claims PENDING and RETRYING tasks, and takes over IN_PROGRESS tasks
        whose lease has expired. Otherwise changes nothing and says why:
        - BUSY: the task still needs work, but someone else holds it (or just
          claimed it), so its message should be kept;
        - DONE: the task SUCCEEDED or FAILED, or its job FAILED, so its message
          can be dropped.
        """
        lease = await self._tasks.claim(task_id, job_id, self._config.lease_seconds)
        if lease is None:
            # When in doubt, BUSY: keeping a message only costs a redelivery,
            # while dropping one for a task that still needs work strands it.
            if await self._tasks.is_unfinished(task_id, job_id):
                return ClaimResult(status=ClaimStatus.BUSY)
            return ClaimResult(status=ClaimStatus.DONE)

        task = await self._tasks.get(task_id)
        store = await self._stores.get(task.store_id) if task else None
        if task is None or store is None:
            # Can't happen: the claim just matched the task, and the foreign
            # key keeps its store. Raising rolls the claim back.
            raise LookupError(f"Task {task_id} or its store disappeared")

        # Commit the claim on its own, so it's durable (and other workers see it)
        # before the slow enrichment call that follows.
        await self._session.commit()
        return ClaimResult(
            status=ClaimStatus.CLAIMED,
            task=ClaimedTask(
                task_id=task.id,
                job_id=task.job_id,
                attempt_count=task.attempt_count,
                lease_expires_at=lease,
                request=EnrichRequest(
                    store_id=store.store_id,
                    store_name=store.store_name,
                    address=store.address,
                    city=store.city,
                    state=store.state,
                ),
            ),
        )

    async def record_success(self, task: ClaimedTask, result: EnrichResponse) -> bool:
        """Mark a claimed task SUCCEEDED with the store's metrics, and commit.

        Counts the call as one more attempt. Returns False, changing nothing, if
        the task isn't IN_PROGRESS under this claim's lease any more, or its job
        has FAILED.
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

    async def record_failed_call(
        self, task: ClaimedTask, reason: str, rate_limited: bool = False
    ) -> TaskStatus | None:
        """Record a failed call on a claimed task, and commit. Either the task
        gets another try, or it has run out of attempts:

        - a 429 (`rate_limited`): RETRYING, without counting an attempt, since
          the API refused the call rather than failing it;
        - any other failure: one more attempt. Below `max_attempts`, RETRYING;
          reaching it, FAILED for good (see record_failure).

        `reason` is saved as `last_error` either way. Returns the task's new
        status (RETRYING: send it a retry event; FAILED), or None, changing
        nothing, if the task isn't IN_PROGRESS under this claim's lease any
        more, or its job has FAILED.
        """
        if rate_limited:
            attempts = task.attempt_count
        else:
            attempts = task.attempt_count + 1
            if attempts >= self._config.max_attempts:
                updated = await self.record_failure(task, reason)
                return TaskStatus.FAILED if updated else None

        updated = await self._finish(
            task,
            EnrichmentTaskUpdate(
                status=TaskStatus.RETRYING, attempt_count=attempts, last_error=reason
            ),
        )
        return TaskStatus.RETRYING if updated else None

    async def record_failure(self, task: ClaimedTask, reason: str) -> bool:
        """Mark a claimed task FAILED for good with `reason` as its `last_error`,
        and commit.

        Counts the call as one more attempt. Returns False, changing nothing, if
        the task isn't IN_PROGRESS under this claim's lease any more, or its job
        has FAILED.
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
        """End a claim: apply `changes` to the task if it's still IN_PROGRESS
        under this claim's lease, clear the lease, and commit.

        Only the handler holding the lease gets here, so writing
        `attempt_count + 1` read at claim time can't lose an increment.
        """
        updated = await self._tasks.update_if_status(
            task.task_id,
            task.job_id,
            expected=TaskStatus.IN_PROGRESS,
            changes=changes.model_copy(update={"lease_expires_at": None}),
            lease=task.lease_expires_at,
        )
        await self._session.commit()
        return updated


EnrichmentTaskServiceDep = Annotated[EnrichmentTaskService, Depends()]
