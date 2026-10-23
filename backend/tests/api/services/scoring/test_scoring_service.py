from decimal import Decimal

from pytest import fixture, mark, raises
from sqlalchemy.ext.asyncio import AsyncSession

from api.exceptions import JobNotFoundError, JobNotScorableError
from api.models import Job, JobStatus, Tier
from api.repositories.enrichment_task import EnrichmentTaskRepository
from api.repositories.job import JobRepository
from api.repositories.store_score import StoreScoreRepository
from api.schemas.enrichment_tasks import TaskMetrics
from api.schemas.scoring import ScoringConfig, TierCounts
from api.services.scoring.scoring_service import ScoringService

CONFIG = ScoringConfig.model_validate(
    {
        "bars": {"footfall": 15000, "revenue": 150000, "size_sqft": 8000},
        "weights": {"footfall": 50, "revenue": 30, "size_sqft": 20},
        "tiers": {"large_min": 70, "medium_min": 40},
    }
)
# The brief's worked example: stores A, B and C.
METRICS = [
    TaskMetrics(
        task_id=1,
        estimated_monthly_footfall=40_000,
        estimated_monthly_revenue=Decimal("400000"),
        store_size_sqft=18_000,
    ),
    TaskMetrics(
        task_id=2,
        estimated_monthly_footfall=20_000,
        estimated_monthly_revenue=Decimal("100000"),
        store_size_sqft=5_000,
    ),
    TaskMetrics(
        task_id=3,
        estimated_monthly_footfall=2_000,
        estimated_monthly_revenue=Decimal("20000"),
        store_size_sqft=9_000,
    ),
]


class TestScoringServiceScoreJob:
    """Unit tests: the repositories and the session are mocks."""

    @fixture
    def jobs(self, mocker):
        repository = mocker.AsyncMock(spec=JobRepository)
        repository.get.return_value = Job(id=7, status=JobStatus.COMPLETED)
        return repository

    @fixture
    def tasks(self, mocker):
        repository = mocker.AsyncMock(spec=EnrichmentTaskRepository)
        repository.list_succeeded_metrics.return_value = METRICS
        return repository

    @fixture
    def scores(self, mocker):
        repository = mocker.AsyncMock(spec=StoreScoreRepository)
        repository.count_by_tier.return_value = {
            Tier.LARGE: 1,
            Tier.MEDIUM: 1,
            Tier.SMALL: 1,
        }
        return repository

    @fixture
    def session(self, mocker):
        return mocker.AsyncMock(spec=AsyncSession)

    @fixture
    def service(self, jobs, tasks, scores, session):
        return ScoringService(jobs, tasks, scores, session)

    async def test_scores_every_succeeded_store_and_replaces_the_jobs_scores(
        self, service, scores
    ):
        await service.score_job(7, CONFIG)

        job_id, new_scores = scores.replace_for_job.await_args.args
        assert job_id == 7
        assert [(s.task_id, s.score, s.tier) for s in new_scores] == [
            (1, 100, Tier.LARGE),
            (2, 50, Tier.MEDIUM),
            (3, 20, Tier.SMALL),
        ]
        assert len({s.scored_at for s in new_scores}) == 1

    async def test_saves_the_config_on_the_job_and_commits_once(
        self, service, jobs, session
    ):
        await service.score_job(7, CONFIG)

        job_id, changes = jobs.update.await_args.args
        assert job_id == 7
        saved = changes.model_dump(exclude_unset=True)
        assert saved.pop("scored_at") is not None
        assert saved == {"scoring_config": CONFIG.model_dump(mode="json")}
        session.commit.assert_awaited_once()

    async def test_locks_the_job_while_scoring(self, service, jobs):
        await service.score_job(7, CONFIG)

        jobs.get.assert_awaited_once_with(7, lock=True)

    async def test_returns_the_tier_counts(self, service):
        response = await service.score_job(7, CONFIG)

        assert response.job_id == 7
        assert response.scored_count == 3
        assert response.tiers == TierCounts(large=1, medium=1, small=1)
        assert response.config == CONFIG

    async def test_a_tier_with_no_stores_counts_zero(self, service, scores):
        scores.count_by_tier.return_value = {Tier.SMALL: 3}

        response = await service.score_job(7, CONFIG)

        assert response.tiers == TierCounts(large=0, medium=0, small=3)

    async def test_a_job_without_succeeded_stores_scores_nothing(
        self, service, tasks, scores
    ):
        tasks.list_succeeded_metrics.return_value = []
        scores.count_by_tier.return_value = {}

        response = await service.score_job(7, CONFIG)

        scores.replace_for_job.assert_awaited_once_with(7, [])
        assert response.scored_count == 0
        assert response.tiers == TierCounts()

    async def test_completed_with_failures_can_be_scored(self, service, jobs):
        jobs.get.return_value = Job(id=7, status=JobStatus.COMPLETED_WITH_FAILURES)

        response = await service.score_job(7, CONFIG)

        assert response.scored_count == 3

    async def test_an_unknown_job_raises_not_found(self, service, jobs, session):
        jobs.get.return_value = None

        with raises(JobNotFoundError, match="Job 7 not found"):
            await service.score_job(7, CONFIG)
        session.commit.assert_not_awaited()

    @mark.parametrize(
        "status", [JobStatus.PENDING, JobStatus.RUNNING, JobStatus.FAILED]
    )
    async def test_an_unfinished_or_failed_job_raises_not_scorable(
        self, service, jobs, scores, session, status
    ):
        jobs.get.return_value = Job(id=7, status=status)

        with raises(JobNotScorableError, match=f"Job 7 is {status}"):
            await service.score_job(7, CONFIG)
        scores.replace_for_job.assert_not_awaited()
        session.commit.assert_not_awaited()
