from collections.abc import Sequence
from datetime import UTC, datetime
from logging import getLogger
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import Depends

from api.dependencies.aws.sqs import SQSClientDep
from api.dependencies.db_session import DbSessionDep
from api.exceptions import JobNotFoundError
from api.models import Job, JobStatus, TaskStatus
from api.repositories.enrichment_task import EnrichmentTaskRepositoryDep
from api.repositories.job import JobRepositoryDep
from api.repositories.store_score import StoreScoreRepositoryDep
from api.schemas.enrichment_tasks import EnrichmentTaskCreate
from api.schemas.jobs import (
    JobCreate,
    JobListItem,
    JobResponse,
    JobSummary,
    JobUpdate,
    ScoringSummary,
    TaskCounts,
)
from api.schemas.messages import EnrichmentEvent, EnrichStorePayload
from api.schemas.pagination import Page, PageParams
from api.schemas.scoring import ScoringConfig, TierCounts
from api.schemas.stores import JobStoreFilters, JobStoreItem, JobStoreOrder
from config import ConfigDep

logger = getLogger(__name__)


class EnrichmentJobService:
    """Enrichment jobs: creates one for an upload, queues one event per store,
    stops it if its calls keep failing (the circuit breaker), finishes it once
    all its tasks are done, and reads jobs back (the job list, a job's progress
    and summary, and its stores).

    The API uses it through FastAPI dependencies; the worker builds it itself.
    The read methods never write or commit.
    """

    def __init__(
        self,
        jobs_repository: JobRepositoryDep,
        enrichment_tasks_repository: EnrichmentTaskRepositoryDep,
        scores_repository: StoreScoreRepositoryDep,
        sqs_client: SQSClientDep,
        session: DbSessionDep,
        config: ConfigDep,
    ) -> None:
        self._jobs_repository = jobs_repository
        self._enrichment_tasks_repository = enrichment_tasks_repository
        self._scores_repository = scores_repository
        self._sqs_client = sqs_client
        self._session = session
        self._queue_url = config.sqs.enrichment_queue_url
        self._send_concurrency = config.sqs.send_concurrency
        self._breaker_threshold = config.enrichment.circuit_breaker_threshold

    async def create_job(
        self, upload_id: UUID, store_ids: Sequence[int]
    ) -> tuple[Job, list[int]]:
        """Add a PENDING job and one PENDING task per store. Doesn't commit: the
        caller commits it together with the stores, before calling dispatch()."""
        job = await self._jobs_repository.create(
            JobCreate(
                upload_id=upload_id,
                total_tasks=len(store_ids),
                status=JobStatus.PENDING,
            )
        )
        task_ids = await self._enrichment_tasks_repository.bulk_create(
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
            await self._sqs_client.send_messages(
                self._queue_url, events, concurrency=self._send_concurrency
            )
        except Exception as e:
            logger.exception("Could not send events for job %s", job_id)
            await self._jobs_repository.update(
                job_id,
                JobUpdate(
                    status=JobStatus.FAILED,
                    error=f"Could not queue enrichment: {e}",
                    finished_at=datetime.now(UTC),
                ),
            )
            await self._session.commit()
            raise

        await self._jobs_repository.update(
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

    async def record_call_outcome(
        self, job_id: int, succeeded: bool, reason: str = ""
    ) -> bool:
        """Feed one enrichment call's outcome to the job's circuit breaker, and
        commit.

        The breaker counts the job's failed calls in a row, across all its
        stores; any success resets the count. The API's normal failures are
        random, so a long streak means the API itself is broken: when the count
        reaches `circuit_breaker_threshold`, the job is FAILED with an error
        naming `reason` (the last failure), and so is every unfinished task of
        it. Their remaining events are then dropped by the claim, and results
        of calls still in flight are rejected.

        Returns True if this call tripped the breaker. Only one handler can:
        the job's status change is guarded on RUNNING.
        """
        if succeeded:
            await self._jobs_repository.reset_failed_calls(job_id)
            await self._session.commit()
            return False

        streak = await self._jobs_repository.add_failed_call(job_id)
        if streak is None or streak < self._breaker_threshold:
            await self._session.commit()
            return False

        finished_at = datetime.now(UTC)
        tripped = await self._jobs_repository.update_if_status(
            job_id,
            expected=JobStatus.RUNNING,
            changes=JobUpdate(
                status=JobStatus.FAILED,
                error=f"circuit breaker: {streak} consecutive failed calls"
                f" (last: {reason})",
                finished_at=finished_at,
            ),
        )
        if tripped:
            await self._enrichment_tasks_repository.fail_unfinished(
                job_id, "job stopped by circuit breaker", finished_at
            )
        await self._session.commit()
        return tripped

    async def finish_if_complete(self, job_id: int) -> JobStatus | None:
        """If every task of a RUNNING job has finished, mark the job COMPLETED
        (all tasks SUCCEEDED) or COMPLETED_WITH_FAILURES (some FAILED), and commit.

        Called after each task finishes. Returns the job's new status, or None
        if tasks are still unfinished (PENDING, IN_PROGRESS, or RETRYING: waiting
        for a retry), or the job isn't RUNNING (already finished, or FAILED).

        Safe when two workers finish the last tasks at the same time: each
        commits its task before counting, so whichever counts last sees every
        task finished, and the guarded update lets only one of them finish the
        job.
        """
        counts = await self._enrichment_tasks_repository.count_by_status(job_id)
        if any(counts.get(status, 0) for status in TaskStatus.unfinished()):
            return None

        status = (
            JobStatus.COMPLETED_WITH_FAILURES
            if counts.get(TaskStatus.FAILED, 0)
            else JobStatus.COMPLETED
        )
        finished = await self._jobs_repository.update_if_status(
            job_id,
            expected=JobStatus.RUNNING,
            changes=JobUpdate(status=status, finished_at=datetime.now(UTC)),
        )
        await self._session.commit()
        return status if finished else None

    async def list_jobs(self, page: PageParams) -> Page[JobListItem]:
        """One page of jobs, newest first."""
        jobs, total = await self._jobs_repository.list_recent(page)
        items = [
            JobListItem(
                job_id=job.id,
                upload_id=job.upload_id,
                status=job.status,
                total_tasks=job.total_tasks,
                created_at=job.created_at,
                finished_at=job.finished_at,
            )
            for job in jobs
        ]
        return Page(items=items, total_count=total)

    async def get_job(self, job_id: int) -> JobResponse:
        """The job with its task counts per status (progress).

        Raises JobNotFoundError (404) if there's no such job.
        """
        job = await self._get_job(job_id)
        return JobResponse(
            job_id=job.id,
            upload_id=job.upload_id,
            status=job.status,
            error=job.error,
            total_tasks=job.total_tasks,
            tasks=await self._task_counts(job_id),
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )

    async def get_summary(self, job_id: int) -> JobSummary:
        """Task counts per status, plus the latest scoring (when, with which
        settings, and the tier counts), or null if the job isn't scored yet.

        Raises JobNotFoundError (404) if there's no such job.
        """
        job = await self._get_job(job_id)
        scoring = None
        if job.scoring_config is not None and job.scored_at is not None:
            tier_counts = await self._scores_repository.count_by_tier(job_id)
            scoring = ScoringSummary(
                scored_at=job.scored_at,
                config=ScoringConfig.model_validate(job.scoring_config),
                tiers=TierCounts(
                    **{tier.value: count for tier, count in tier_counts.items()}
                ),
            )
        return JobSummary(
            job_id=job.id,
            status=job.status,
            total_tasks=job.total_tasks,
            tasks=await self._task_counts(job_id),
            scoring=scoring,
        )

    async def list_stores(
        self, job_id: int, filters: JobStoreFilters, page: PageParams
    ) -> Page[JobStoreItem]:
        """One page of the job's stores, filtered by status and/or tier.

        Ordered by what the filter is about: highest score first when filtering
        by tier or SUCCEEDED; most recently finished first when filtering by
        FAILED; otherwise by store_id. Raises JobNotFoundError (404) if there's
        no such job.
        """
        await self._get_job(job_id)
        items, total = await self._enrichment_tasks_repository.list_stores(
            job_id, filters, self._store_order_for(filters), page
        )
        return Page(items=items, total_count=total)

    @staticmethod
    def _store_order_for(filters: JobStoreFilters) -> JobStoreOrder:
        """The most useful order for what the filters select."""
        if filters.tier is not None or filters.status == TaskStatus.SUCCEEDED:
            return JobStoreOrder.SCORE
        if filters.status == TaskStatus.FAILED:
            return JobStoreOrder.RECENTLY_FINISHED
        return JobStoreOrder.STORE_ID

    async def _get_job(self, job_id: int) -> Job:
        """The job, or JobNotFoundError (404)."""
        job = await self._jobs_repository.get(job_id)
        if job is None:
            raise JobNotFoundError(f"Job {job_id} not found.")
        return job

    async def _task_counts(self, job_id: int) -> TaskCounts:
        """The job's task counts, with 0 for statuses that have no tasks."""
        counts = await self._enrichment_tasks_repository.count_by_status(job_id)
        return TaskCounts(**{status.value: count for status, count in counts.items()})


EnrichmentJobServiceDep = Annotated[EnrichmentJobService, Depends()]
