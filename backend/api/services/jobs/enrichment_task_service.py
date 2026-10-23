from typing import Annotated

from fastapi import Depends

from api.dependencies.db_session import DbSessionDep
from api.models import TaskStatus
from api.repositories.enrichment_task import EnrichmentTaskRepositoryDep
from api.schemas.enrichment_tasks import EnrichmentTaskUpdate


class EnrichmentTaskService:
    """Moves enrichment tasks through their statuses. Used by the worker, which
    builds it with a repository on its own session."""

    def __init__(
        self, tasks: EnrichmentTaskRepositoryDep, session: DbSessionDep
    ) -> None:
        self._tasks = tasks
        self._session = session

    async def claim(self, task_id: int, job_id: int) -> bool:
        """Move a task from PENDING to IN_PROGRESS, and commit.

        Returns False, changing nothing, if the task isn't PENDING any more
        (e.g. a duplicate SQS delivery) or its job has FAILED.
        """
        claimed = await self._tasks.update_if_status(
            task_id,
            job_id,
            expected=TaskStatus.PENDING,
            changes=EnrichmentTaskUpdate(status=TaskStatus.IN_PROGRESS),
        )
        await self._session.commit()
        return claimed


EnrichmentTaskServiceDep = Annotated[EnrichmentTaskService, Depends()]
