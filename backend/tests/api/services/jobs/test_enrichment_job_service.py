from datetime import UTC, datetime
from uuid import uuid4

from pytest import fixture, mark, raises
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.aws.sqs import SQSClient
from api.exceptions import JobNotFoundError
from api.models import Job, JobStatus, TaskStatus, Tier
from api.repositories.enrichment_task import EnrichmentTaskRepository
from api.repositories.job import JobRepository
from api.repositories.store_score import StoreScoreRepository
from api.schemas.jobs import TaskCounts
from api.schemas.pagination import PageParams
from api.schemas.scoring import ScoringConfig, TierCounts
from api.schemas.stores import JobStoreFilters, JobStoreOrder
from api.services.jobs import EnrichmentJobService
from config import cfg

NOW = datetime(2026, 10, 23, 10, 0, tzinfo=UTC)
CONFIG = {
    "bars": {"footfall": 15000, "revenue": 150000.0, "size_sqft": 8000},
    "weights": {"footfall": 50, "revenue": 30, "size_sqft": 20},
    "tiers": {"large_min": 70, "medium_min": 40},
}


def make_job(**fields) -> Job:
    values = {
        "id": 7,
        "upload_id": uuid4(),
        "status": JobStatus.RUNNING,
        "error": None,
        "total_tasks": 5,
        "created_at": NOW,
        "started_at": NOW,
        "finished_at": None,
        "scoring_config": None,
        "scored_at": None,
    }
    return Job(**{**values, **fields})


class EnrichmentJobServiceTest:
    """Unit tests: the repositories, SQS client and session are mocks."""

    @fixture
    def jobs(self, mocker):
        repository = mocker.AsyncMock(spec=JobRepository)
        repository.get.return_value = make_job()
        repository.update_if_status.return_value = True
        return repository

    @fixture
    def tasks(self, mocker):
        repository = mocker.AsyncMock(spec=EnrichmentTaskRepository)
        repository.count_by_status.return_value = {
            TaskStatus.SUCCEEDED: 3,
            TaskStatus.FAILED: 1,
            TaskStatus.PENDING: 1,
        }
        repository.list_stores.return_value = ([], 0)
        return repository

    @fixture
    def scores(self, mocker):
        repository = mocker.AsyncMock(spec=StoreScoreRepository)
        repository.count_by_tier.return_value = {Tier.LARGE: 1, Tier.SMALL: 2}
        return repository

    @fixture
    def session(self, mocker):
        return mocker.AsyncMock(spec=AsyncSession)

    @fixture
    def service(self, mocker, jobs, tasks, scores, session):
        sqs = mocker.AsyncMock(spec=SQSClient)
        return EnrichmentJobService(jobs, tasks, scores, sqs, session, cfg)


class TestEnrichmentJobServiceFinishIfComplete(EnrichmentJobServiceTest):
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


class TestEnrichmentJobServiceListJobs(EnrichmentJobServiceTest):
    async def test_returns_a_page_of_jobs(self, service, jobs):
        jobs.list_recent.return_value = ([make_job(id=9), make_job(id=8)], 12)

        page = await service.list_jobs(PageParams(page=2, page_size=2))

        jobs.list_recent.assert_awaited_once_with(PageParams(page=2, page_size=2))
        assert [item.job_id for item in page.items] == [9, 8]
        assert page.total_count == 12


class TestEnrichmentJobServiceGetJob(EnrichmentJobServiceTest):
    async def test_returns_the_job_with_counts_for_every_status(self, service):
        job = await service.get_job(7)

        assert job.job_id == 7
        assert job.status == JobStatus.RUNNING
        assert job.tasks == TaskCounts(pending=1, in_progress=0, succeeded=3, failed=1)

    async def test_an_unknown_job_raises_not_found(self, service, jobs):
        jobs.get.return_value = None

        with raises(JobNotFoundError, match="Job 7 not found"):
            await service.get_job(7)


class TestEnrichmentJobServiceGetSummary(EnrichmentJobServiceTest):
    async def test_an_unscored_job_has_no_scoring(self, service, scores):
        summary = await service.get_summary(7)

        assert summary.scoring is None
        assert summary.tasks.succeeded == 3
        scores.count_by_tier.assert_not_awaited()

    async def test_a_scored_job_has_its_latest_scoring(self, service, jobs):
        jobs.get.return_value = make_job(
            status=JobStatus.COMPLETED_WITH_FAILURES,
            scoring_config=CONFIG,
            scored_at=NOW,
        )

        summary = await service.get_summary(7)

        assert summary.status == JobStatus.COMPLETED_WITH_FAILURES
        assert summary.scoring.scored_at == NOW
        assert summary.scoring.config == ScoringConfig.model_validate(CONFIG)
        assert summary.scoring.tiers == TierCounts(large=1, medium=0, small=2)

    async def test_an_unknown_job_raises_not_found(self, service, jobs):
        jobs.get.return_value = None

        with raises(JobNotFoundError):
            await service.get_summary(7)


class TestEnrichmentJobServiceListStores(EnrichmentJobServiceTest):
    @mark.parametrize(
        "filters, order",
        [
            (JobStoreFilters(), JobStoreOrder.STORE_ID),
            (JobStoreFilters(status=TaskStatus.PENDING), JobStoreOrder.STORE_ID),
            (JobStoreFilters(status=TaskStatus.IN_PROGRESS), JobStoreOrder.STORE_ID),
            (JobStoreFilters(status=TaskStatus.SUCCEEDED), JobStoreOrder.SCORE),
            (JobStoreFilters(tier=Tier.LARGE), JobStoreOrder.SCORE),
            (
                JobStoreFilters(status=TaskStatus.FAILED),
                JobStoreOrder.RECENTLY_FINISHED,
            ),
        ],
    )
    async def test_orders_by_what_the_filters_select(
        self, service, tasks, filters, order
    ):
        page = PageParams()

        await service.list_stores(7, filters, page)

        tasks.list_stores.assert_awaited_once_with(7, filters, order, page)

    async def test_returns_the_page_with_its_total(self, service, tasks):
        tasks.list_stores.return_value = ([], 42)

        page = await service.list_stores(7, JobStoreFilters(), PageParams(page=3))

        assert (page.items, page.total_count) == ([], 42)

    async def test_an_unknown_job_raises_not_found(self, service, jobs, tasks):
        jobs.get.return_value = None

        with raises(JobNotFoundError):
            await service.list_stores(7, JobStoreFilters(), PageParams())
        tasks.list_stores.assert_not_awaited()
