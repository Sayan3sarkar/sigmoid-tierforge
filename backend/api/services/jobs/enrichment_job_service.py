from collections.abc import Sequence
from datetime import UTC, datetime
from logging import getLogger
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import Depends

from api.dependencies.aws.sqs import SQSClientDep
from api.dependencies.db_session import DbSessionDep
from api.models import Job, JobStatus, TaskStatus
from api.repositories.enrichment_task import EnrichmentTaskRepositoryDep
from api.repositories.job import JobRepositoryDep
from api.schemas.enrichment_tasks import EnrichmentTaskCreate
from api.schemas.jobs import JobCreate, JobUpdate
from api.schemas.messages import EnrichmentEvent, EnrichStorePayload
from config import ConfigDep

logger = getLogger(__name__)


class EnrichmentJobService:
    """Creates an enrichment job for an upload and queues one event per store."""

    def __init__(
        self,
        jobs: JobRepositoryDep,
        tasks: EnrichmentTaskRepositoryDep,
        sqs: SQSClientDep,
        session: DbSessionDep,
        config: ConfigDep,
    ) -> None:
        self._jobs = jobs
        self._tasks = tasks
        self._sqs = sqs
        self._session = session
        self._queue_url = config.sqs.enrichment_queue_url
        self._send_concurrency = config.sqs.send_concurrency

    async def create_job(
        self, upload_id: UUID, store_ids: Sequence[int]
    ) -> tuple[Job, list[int]]:
        """Add a PENDING job and one PENDING task per store. Doesn't commit: the
        caller commits it together with the stores, before calling dispatch()."""
        job = await self._jobs.create(
            JobCreate(
                upload_id=upload_id,
                total_tasks=len(store_ids),
                status=JobStatus.PENDING,
            )
        )
        task_ids = await self._tasks.bulk_create(
            [
                EnrichmentTaskCreate(
                    job_id=job.id, store_id=store_id, status=TaskStatus.PENDING
                )
                for store_id in store_ids
            ]
        )
        return job, task_ids

    async def dispatch(self, job_id: int, task_ids: list[int]) -> JobStatus:
        """Send one event per task, then mark the job RUNNING and commit.

        The job and tasks must already be committed, so the worker never receives
        an event for a row it can't see. If sending fails, the job is marked FAILED
        (committed) and the error re-raised; the worker skips tasks of failed jobs.
        """
        events = [
            EnrichmentEvent(payload=EnrichStorePayload(job_id=job_id, task_id=task_id))
            for task_id in task_ids
        ]
        started = perf_counter()
        try:
            await self._sqs.send_messages(
                self._queue_url, events, concurrency=self._send_concurrency
            )
        except Exception as e:
            logger.exception("Could not send events for job %s", job_id)
            await self._jobs.update(
                job_id,
                JobUpdate(
                    status=JobStatus.FAILED,
                    error=f"Could not queue enrichment: {e}",
                    finished_at=datetime.now(UTC),
                ),
            )
            await self._session.commit()
            raise

        await self._jobs.update(
            job_id,
            JobUpdate(status=JobStatus.RUNNING, started_at=datetime.now(UTC)),
        )
        await self._session.commit()
        logger.info(
            "Job %s running: %d events sent in %.2fs",
            job_id,
            len(events),
            perf_counter() - started,
        )
        return JobStatus.RUNNING


EnrichmentJobServiceDep = Annotated[EnrichmentJobService, Depends()]
