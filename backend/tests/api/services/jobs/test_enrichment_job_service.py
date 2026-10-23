from pytest import fixture, mark
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.aws.sqs import SQSClient
from api.models import JobStatus, TaskStatus
from api.repositories.enrichment_task import EnrichmentTaskRepository
from api.repositories.job import JobRepository
from api.services.jobs import EnrichmentJobService
from config import cfg


class TestEnrichmentJobServiceFinishIfComplete:
    """Unit tests: the repositories, SQS client and session are mocks."""

    @fixture
    def jobs(self, mocker):
        repository = mocker.AsyncMock(spec=JobRepository)
        repository.update_if_status.return_value = True
        return repository

    @fixture
    def tasks(self, mocker):
        return mocker.AsyncMock(spec=EnrichmentTaskRepository)

    @fixture
    def session(self, mocker):
        return mocker.AsyncMock(spec=AsyncSession)

    @fixture
    def service(self, mocker, jobs, tasks, session):
        sqs = mocker.AsyncMock(spec=SQSClient)
        return EnrichmentJobService(jobs, tasks, sqs, session, cfg)

    @mark.parametrize(
        "counts",
        [
            {TaskStatus.PENDING: 1, TaskStatus.SUCCEEDED: 4},
            {TaskStatus.IN_PROGRESS: 1, TaskStatus.FAILED: 4},
        ],
    )
    async def test_leaves_the_job_running_while_tasks_are_unfinished(
        self, service, jobs, tasks, session, counts
    ):
        tasks.count_by_status.return_value = counts

        assert await service.finish_if_complete(7) is None
        jobs.update_if_status.assert_not_awaited()
        session.commit.assert_not_awaited()

    @mark.parametrize(
        "counts, status",
        [
            ({TaskStatus.SUCCEEDED: 5}, JobStatus.COMPLETED),
            (
                {TaskStatus.SUCCEEDED: 4, TaskStatus.FAILED: 1},
                JobStatus.COMPLETED_WITH_FAILURES,
            ),
            ({TaskStatus.FAILED: 5}, JobStatus.COMPLETED_WITH_FAILURES),
        ],
    )
    async def test_finishes_a_running_job_once_every_task_is_done(
        self, service, jobs, tasks, session, counts, status
    ):
        tasks.count_by_status.return_value = counts

        assert await service.finish_if_complete(7) == status

        call = jobs.update_if_status.await_args
        assert call.args == (7,)
        assert call.kwargs["expected"] == JobStatus.RUNNING
        changes = call.kwargs["changes"].model_dump(exclude_unset=True)
        assert changes["status"] == status
        assert changes["finished_at"] is not None
        session.commit.assert_awaited_once()

    async def test_returns_none_when_the_job_is_not_running_any_more(
        self, service, jobs, tasks
    ):
        # Already finished by another worker, or FAILED.
        tasks.count_by_status.return_value = {TaskStatus.SUCCEEDED: 5}
        jobs.update_if_status.return_value = False

        assert await service.finish_if_complete(7) is None
