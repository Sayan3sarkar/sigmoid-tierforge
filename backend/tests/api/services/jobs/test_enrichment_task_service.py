from decimal import Decimal

from pytest import fixture, raises
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import EnrichmentTask, Store, TaskStatus
from api.repositories.enrichment_task import EnrichmentTaskRepository
from api.repositories.store import StoreRepository
from api.schemas.enrichment import EnrichRequest, EnrichResponse
from api.schemas.enrichment_tasks import ClaimedTask
from api.services.jobs import EnrichmentTaskService

REQUEST = EnrichRequest(
    store_id="ST000001",
    store_name="Fresh Supermarket #1",
    address="71 Church Street",
    city="New Delhi",
    state="Delhi",
)


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
        return EnrichmentTaskService(tasks, stores, session)


class TestEnrichmentTaskServiceClaim(EnrichmentTaskServiceTest):
    @fixture
    def claimable(self, tasks, stores):
        """update_if_status matches; the task (store row 3) and store exist."""
        tasks.update_if_status.return_value = True
        tasks.get.return_value = EnrichmentTask(
            id=42, job_id=7, store_id=3, attempt_count=0
        )
        stores.get.return_value = Store(id=3, country="India", **REQUEST.model_dump())

    async def test_moves_a_pending_task_to_in_progress_and_commits(
        self, service, tasks, session, claimable
    ):
        await service.claim(task_id=42, job_id=7)

        call = tasks.update_if_status.await_args
        assert call.args == (42, 7)
        assert call.kwargs["expected"] == TaskStatus.PENDING
        assert call.kwargs["changes"].model_dump(exclude_unset=True) == {
            "status": TaskStatus.IN_PROGRESS
        }
        session.commit.assert_awaited_once()

    async def test_returns_the_task_with_its_stores_request(
        self, service, stores, claimable
    ):
        claimed = await service.claim(task_id=42, job_id=7)

        assert claimed == ClaimedTask(
            task_id=42, job_id=7, attempt_count=0, request=REQUEST
        )
        stores.get.assert_awaited_once_with(3)

    async def test_returns_none_when_the_task_could_not_be_claimed(
        self, service, tasks, stores, session
    ):
        tasks.update_if_status.return_value = False

        assert await service.claim(task_id=42, job_id=7) is None
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
    TASK = ClaimedTask(task_id=42, job_id=7, attempt_count=0, request=REQUEST)

    async def test_success_saves_the_metrics_and_commits(self, service, tasks, session):
        tasks.update_if_status.return_value = True
        result = EnrichResponse(
            store_id="ST000001",
            estimated_monthly_footfall=18234,
            estimated_monthly_revenue=Decimal("142033.50"),
            store_size_sqft=6210,
        )

        assert await service.record_success(self.TASK, result) is True

        call = tasks.update_if_status.await_args
        assert call.args == (42, 7)
        assert call.kwargs["expected"] == TaskStatus.IN_PROGRESS
        changes = call.kwargs["changes"].model_dump(exclude_unset=True)
        assert changes.pop("finished_at") is not None
        assert changes == {
            "status": TaskStatus.SUCCEEDED,
            "attempt_count": 1,
            "last_error": None,
            "estimated_monthly_footfall": 18234,
            "estimated_monthly_revenue": Decimal("142033.50"),
            "store_size_sqft": 6210,
        }
        session.commit.assert_awaited_once()

    async def test_failure_saves_the_reason_and_commits(self, service, tasks, session):
        tasks.update_if_status.return_value = True

        assert await service.record_failure(self.TASK, "rate limited (429)") is True

        call = tasks.update_if_status.await_args
        assert call.kwargs["expected"] == TaskStatus.IN_PROGRESS
        changes = call.kwargs["changes"].model_dump(exclude_unset=True)
        assert changes.pop("finished_at") is not None
        assert changes == {
            "status": TaskStatus.FAILED,
            "attempt_count": 1,
            "last_error": "rate limited (429)",
        }
        session.commit.assert_awaited_once()

    async def test_counts_one_more_attempt_than_before_the_claim(self, service, tasks):
        task = self.TASK.model_copy(update={"attempt_count": 2})

        await service.record_failure(task, "upstream error (500)")

        changes = tasks.update_if_status.await_args.kwargs["changes"]
        assert changes.attempt_count == 3

    async def test_returns_false_when_the_task_is_no_longer_in_progress(
        self, service, tasks
    ):
        tasks.update_if_status.return_value = False

        assert await service.record_failure(self.TASK, "timed out after 10s") is False
