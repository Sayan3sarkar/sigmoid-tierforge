from datetime import UTC, datetime
from decimal import Decimal

from pytest import fixture, mark, raises
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import EnrichmentTask, Store, TaskStatus
from api.repositories.enrichment_task import EnrichmentTaskRepository
from api.repositories.store import StoreRepository
from api.schemas.enrichment import EnrichRequest, EnrichResponse
from api.schemas.enrichment_tasks import ClaimedTask, ClaimResult, ClaimStatus
from api.services.jobs import EnrichmentTaskService
from config import cfg

REQUEST = EnrichRequest(
    store_id="ST000001",
    store_name="Fresh Supermarket #1",
    address="71 Church Street",
    city="New Delhi",
    state="Delhi",
)
METRICS = EnrichResponse(
    store_id="ST000001",
    estimated_monthly_footfall=18234,
    estimated_monthly_revenue=Decimal("142033.50"),
    store_size_sqft=6210,
)
LEASE = datetime(2026, 10, 24, 10, 0, 25, tzinfo=UTC)


class EnrichmentTaskServiceTest:
    """Unit tests: the repositories and the session are mocks."""

    @fixture
    def tasks(self, mocker):
        return mocker.AsyncMock(spec=EnrichmentTaskRepository)

    @fixture
    def stores(self, mocker):
        return mocker.AsyncMock(spec=StoreRepository)

    @fixture
    def session(self, mocker):
        return mocker.AsyncMock(spec=AsyncSession)

    @fixture
    def service(self, tasks, stores, session):
        return EnrichmentTaskService(tasks, stores, session, cfg)


class TestEnrichmentTaskServiceClaim(EnrichmentTaskServiceTest):
    @fixture
    def claimable(self, tasks, stores):
        """The claim matches; the task (store row 3) and store exist."""
        tasks.claim.return_value = LEASE
        tasks.get.return_value = EnrichmentTask(
            id=42, job_id=7, store_id=3, attempt_count=2
        )
        stores.get.return_value = Store(id=3, country="India", **REQUEST.model_dump())

    async def test_claims_with_the_configured_lease_and_commits(
        self, service, tasks, session, claimable
    ):
        await service.claim(task_id=42, job_id=7)

        tasks.claim.assert_awaited_once_with(42, 7, cfg.enrichment.lease_seconds)
        session.commit.assert_awaited_once()

    async def test_returns_the_task_with_its_lease_and_stores_request(
        self, service, stores, claimable
    ):
        result = await service.claim(task_id=42, job_id=7)

        assert result == ClaimResult(
            status=ClaimStatus.CLAIMED,
            task=ClaimedTask(
                task_id=42,
                job_id=7,
                attempt_count=2,
                lease_expires_at=LEASE,
                request=REQUEST,
            ),
        )
        stores.get.assert_awaited_once_with(3)

    @mark.parametrize(
        "unfinished, status", [(True, ClaimStatus.BUSY), (False, ClaimStatus.DONE)]
    )
    async def test_says_why_a_task_could_not_be_claimed(
        self, service, tasks, stores, session, unfinished, status
    ):
        tasks.claim.return_value = None
        tasks.is_unfinished.return_value = unfinished

        assert await service.claim(task_id=42, job_id=7) == ClaimResult(status=status)
        tasks.is_unfinished.assert_awaited_once_with(42, 7)
        stores.get.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_raises_without_committing_if_the_store_is_missing(
        self, service, stores, session, claimable
    ):
        stores.get.return_value = None

        with raises(LookupError):
            await service.claim(task_id=42, job_id=7)
        session.commit.assert_not_awaited()


class TestEnrichmentTaskServiceRecordOutcome(EnrichmentTaskServiceTest):
    TASK = ClaimedTask(
        task_id=42, job_id=7, attempt_count=0, lease_expires_at=LEASE, request=REQUEST
    )

    @fixture(autouse=True)
    def updates(self, tasks):
        tasks.update_if_status.return_value = True

    @staticmethod
    def written(tasks) -> dict:
        """The fields the last update wrote, after checking it was fenced on the
        claim: IN_PROGRESS under the claim's lease."""
        call = tasks.update_if_status.await_args
        assert call.args == (42, 7)
        assert call.kwargs["expected"] == TaskStatus.IN_PROGRESS
        assert call.kwargs["lease"] == LEASE
        return call.kwargs["changes"].model_dump(exclude_unset=True)

    def task_with(self, attempt_count: int) -> ClaimedTask:
        return self.TASK.model_copy(update={"attempt_count": attempt_count})

    async def test_success_saves_the_metrics_ends_the_lease_and_commits(
        self, service, tasks, session
    ):
        assert await service.record_success(self.TASK, METRICS) is True

        changes = self.written(tasks)
        assert changes.pop("finished_at") is not None
        assert changes == {
            "status": TaskStatus.SUCCEEDED,
            "attempt_count": 1,
            "last_error": None,
            "estimated_monthly_footfall": 18234,
            "estimated_monthly_revenue": Decimal("142033.50"),
            "store_size_sqft": 6210,
            "lease_expires_at": None,
        }
        session.commit.assert_awaited_once()

    @mark.parametrize("attempt_count", [0, 1, 2, 3])
    async def test_a_failed_call_with_attempts_left_is_retried(
        self, service, tasks, session, attempt_count
    ):
        status = await service.record_failed_call(
            self.task_with(attempt_count), "upstream error (500)"
        )

        assert status == TaskStatus.RETRYING
        assert self.written(tasks) == {
            "status": TaskStatus.RETRYING,
            "attempt_count": attempt_count + 1,
            "last_error": "upstream error (500)",
            "lease_expires_at": None,
        }
        session.commit.assert_awaited_once()

    async def test_the_last_attempt_fails_the_task_for_good(
        self, service, tasks, session
    ):
        # The 5th failed call (cfg.enrichment.max_attempts = 5).
        status = await service.record_failed_call(
            self.task_with(4), "timed out after 10s"
        )

        assert status == TaskStatus.FAILED
        changes = self.written(tasks)
        assert changes.pop("finished_at") is not None
        assert changes == {
            "status": TaskStatus.FAILED,
            "attempt_count": 5,
            "last_error": "timed out after 10s",
            "lease_expires_at": None,
        }
        session.commit.assert_awaited_once()

    async def test_a_429_is_retried_without_using_an_attempt(self, service, tasks):
        status = await service.record_failed_call(
            self.task_with(4), "rate limited (429)", rate_limited=True
        )

        # Even with one attempt left, a 429 never fails the task.
        assert status == TaskStatus.RETRYING
        assert self.written(tasks) == {
            "status": TaskStatus.RETRYING,
            "attempt_count": 4,
            "last_error": "rate limited (429)",
            "lease_expires_at": None,
        }

    async def test_record_failure_fails_the_task_whatever_its_attempts(
        self, service, tasks
    ):
        assert await service.record_failure(self.TASK, "invalid response") is True

        changes = self.written(tasks)
        assert (changes["status"], changes["attempt_count"]) == (TaskStatus.FAILED, 1)

    async def test_nothing_is_recorded_once_the_claim_is_lost(self, service, tasks):
        # Taken over by another handler, finished, or its job FAILED.
        tasks.update_if_status.return_value = False

        assert await service.record_success(self.TASK, METRICS) is False
        assert await service.record_failed_call(self.TASK, "500") is None
        assert await service.record_failed_call(self.task_with(4), "500") is None
        assert await service.record_failure(self.TASK, "500") is False
