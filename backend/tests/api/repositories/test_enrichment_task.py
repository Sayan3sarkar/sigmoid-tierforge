from datetime import UTC, datetime
from decimal import Decimal

from pytest import fixture, mark
from sqlalchemy import select

from api.dependencies.db_session import DBSession
from api.models import EnrichmentTask, JobStatus, TaskStatus, Tier
from api.repositories.enrichment_task import EnrichmentTaskRepository
from api.repositories.job import JobRepository
from api.repositories.store_score import StoreScoreRepository
from api.schemas.enrichment_tasks import (
    EnrichmentTaskUpdate,
    TaskMetrics,
)
from api.schemas.jobs import JobUpdate
from api.schemas.pagination import PageParams
from api.schemas.store_scores import StoreScoreCreate
from api.schemas.stores import JobStoreFilters, JobStoreItem, JobStoreOrder


async def get_task(task_id: int) -> EnrichmentTask:
    async with DBSession.context() as session:
        return await session.scalar(
            select(EnrichmentTask).where(EnrichmentTask.id == task_id)
        )


class TestEnrichmentTaskRepositoryBulkCreate:
    async def test_returns_ids_in_the_order_of_the_tasks(
        self, upload, job_id, task_ids
    ):
        _, store_ids = upload

        tasks = [await get_task(task_id) for task_id in task_ids]

        assert [task.store_id for task in tasks] == store_ids
        assert {task.job_id for task in tasks} == {job_id}
        assert {task.status for task in tasks} == {TaskStatus.PENDING}
        assert {task.attempt_count for task in tasks} == {0}
        # No result until the task is enriched.
        assert {task.estimated_monthly_footfall for task in tasks} == {None}
        assert {task.finished_at for task in tasks} == {None}


class TestEnrichmentTaskRepositoryUpdateIfStatus:
    @staticmethod
    async def update_if_status(
        task_id: int, job_id: int, expected: TaskStatus, changes: EnrichmentTaskUpdate
    ) -> bool:
        async with DBSession.context() as session:
            return await EnrichmentTaskRepository(session).update_if_status(
                task_id, job_id, expected, changes
            )

    async def test_writes_the_changes_when_the_status_matches(self, job_id, task_ids):
        updated = await self.update_if_status(
            task_ids[0],
            job_id,
            TaskStatus.PENDING,
            EnrichmentTaskUpdate(status=TaskStatus.FAILED, last_error="timeout"),
        )

        task = await get_task(task_ids[0])
        assert updated is True
        assert task.status == TaskStatus.FAILED
        assert task.last_error == "timeout"
        assert task.attempt_count == 0

    async def test_saves_an_enrichment_result(self, job_id, task_ids):
        finished_at = datetime(2026, 10, 23, 10, 0, tzinfo=UTC)

        updated = await self.update_if_status(
            task_ids[0],
            job_id,
            TaskStatus.PENDING,
            EnrichmentTaskUpdate(
                status=TaskStatus.SUCCEEDED,
                estimated_monthly_footfall=18234,
                estimated_monthly_revenue=Decimal("142033.50"),
                store_size_sqft=6210,
                finished_at=finished_at,
            ),
        )

        task = await get_task(task_ids[0])
        assert updated is True
        assert task.status == TaskStatus.SUCCEEDED
        assert task.estimated_monthly_footfall == 18234
        assert task.estimated_monthly_revenue == Decimal("142033.50")
        assert task.store_size_sqft == 6210
        assert task.finished_at == finished_at
        assert task.last_error is None

    async def test_changes_nothing_when_the_status_differs(self, job_id, task_ids):
        updated = await self.update_if_status(
            task_ids[0],
            job_id,
            TaskStatus.IN_PROGRESS,
            EnrichmentTaskUpdate(status=TaskStatus.SUCCEEDED),
        )

        assert updated is False
        assert (await get_task(task_ids[0])).status == TaskStatus.PENDING

    async def test_changes_nothing_for_another_job_id(self, job_id, task_ids):
        updated = await self.update_if_status(
            task_ids[0],
            job_id + 1,
            TaskStatus.PENDING,
            EnrichmentTaskUpdate(status=TaskStatus.IN_PROGRESS),
        )

        assert updated is False
        assert (await get_task(task_ids[0])).status == TaskStatus.PENDING

    async def test_changes_nothing_when_the_job_failed(self, job_id, task_ids):
        async with DBSession.context() as session:
            await JobRepository(session).update(
                job_id, JobUpdate(status=JobStatus.FAILED)
            )

        updated = await self.update_if_status(
            task_ids[0],
            job_id,
            TaskStatus.PENDING,
            EnrichmentTaskUpdate(status=TaskStatus.IN_PROGRESS),
        )

        assert updated is False
        assert (await get_task(task_ids[0])).status == TaskStatus.PENDING


class TestEnrichmentTaskRepositoryGet:
    async def test_returns_the_task(self, upload, job_id, task_ids):
        _, store_ids = upload
        async with DBSession.context() as session:
            task = await EnrichmentTaskRepository(session).get(task_ids[1])

        assert task.id == task_ids[1]
        assert task.job_id == job_id
        assert task.store_id == store_ids[1]

    async def test_returns_none_for_an_unknown_id(self, task_ids):
        async with DBSession.context() as session:
            assert (
                await EnrichmentTaskRepository(session).get(max(task_ids) + 1) is None
            )


class TestEnrichmentTaskRepositoryListSucceededMetrics:
    async def test_returns_only_succeeded_tasks_with_their_metrics(
        self, job_id, task_ids
    ):
        async with DBSession.context() as session:
            repository = EnrichmentTaskRepository(session)
            for task_id, footfall in ((task_ids[0], 18234), (task_ids[2], 500)):
                await repository.update_if_status(
                    task_id,
                    job_id,
                    TaskStatus.PENDING,
                    EnrichmentTaskUpdate(
                        status=TaskStatus.SUCCEEDED,
                        estimated_monthly_footfall=footfall,
                        estimated_monthly_revenue=Decimal("142033.50"),
                        store_size_sqft=6210,
                    ),
                )
            await repository.update_if_status(
                task_ids[1],
                job_id,
                TaskStatus.PENDING,
                EnrichmentTaskUpdate(status=TaskStatus.FAILED, last_error="x"),
            )

            metrics = await repository.list_succeeded_metrics(job_id)

        assert metrics == [
            TaskMetrics(
                task_id=task_ids[0],
                estimated_monthly_footfall=18234,
                estimated_monthly_revenue=Decimal("142033.50"),
                store_size_sqft=6210,
            ),
            TaskMetrics(
                task_id=task_ids[2],
                estimated_monthly_footfall=500,
                estimated_monthly_revenue=Decimal("142033.50"),
                store_size_sqft=6210,
            ),
        ]

    async def test_a_job_without_succeeded_tasks_has_none(self, job_id, task_ids):
        async with DBSession.context() as session:
            repository = EnrichmentTaskRepository(session)
            assert await repository.list_succeeded_metrics(job_id) == []


class TestEnrichmentTaskRepositoryCountByStatus:
    async def test_counts_the_jobs_tasks_per_status(self, job_id, task_ids):
        async with DBSession.context() as session:
            repository = EnrichmentTaskRepository(session)
            await repository.update_if_status(
                task_ids[0],
                job_id,
                TaskStatus.PENDING,
                EnrichmentTaskUpdate(status=TaskStatus.SUCCEEDED),
            )
            await repository.update_if_status(
                task_ids[1],
                job_id,
                TaskStatus.PENDING,
                EnrichmentTaskUpdate(status=TaskStatus.FAILED),
            )

            counts = await repository.count_by_status(job_id)

        assert counts == {
            TaskStatus.SUCCEEDED: 1,
            TaskStatus.FAILED: 1,
            TaskStatus.PENDING: 1,
        }

    async def test_a_job_without_tasks_has_no_counts(self, job_id):
        async with DBSession.context() as session:
            assert await EnrichmentTaskRepository(session).count_by_status(job_id) == {}


class TestEnrichmentTaskRepositoryListStores:
    """Three stores (ST000001-3): 1 succeeded and scored 20 (small), 2 failed,
    3 succeeded and scored 100 (large)."""

    @fixture
    async def outcomes(self, job_id, task_ids) -> list[int]:
        async with DBSession.context() as session:
            tasks = EnrichmentTaskRepository(session)
            for task_id, footfall, finished_at in (
                (task_ids[0], 2_000, datetime(2026, 10, 23, 10, 0, tzinfo=UTC)),
                (task_ids[2], 40_000, datetime(2026, 10, 23, 10, 2, tzinfo=UTC)),
            ):
                await tasks.update_if_status(
                    task_id,
                    job_id,
                    TaskStatus.PENDING,
                    EnrichmentTaskUpdate(
                        status=TaskStatus.SUCCEEDED,
                        attempt_count=1,
                        estimated_monthly_footfall=footfall,
                        estimated_monthly_revenue=Decimal("1000.50"),
                        store_size_sqft=5000,
                        finished_at=finished_at,
                    ),
                )
            await tasks.update_if_status(
                task_ids[1],
                job_id,
                TaskStatus.PENDING,
                EnrichmentTaskUpdate(
                    status=TaskStatus.FAILED,
                    attempt_count=1,
                    last_error="timed out after 10s",
                    finished_at=datetime(2026, 10, 23, 10, 1, tzinfo=UTC),
                ),
            )
            await StoreScoreRepository(session).replace_for_job(
                job_id,
                [
                    StoreScoreCreate(
                        job_id=job_id,
                        task_id=task_id,
                        score=score,
                        tier=tier,
                        scored_at=datetime(2026, 10, 23, 11, 0, tzinfo=UTC),
                    )
                    for task_id, score, tier in (
                        (task_ids[0], 20, Tier.SMALL),
                        (task_ids[2], 100, Tier.LARGE),
                    )
                ],
            )
        return task_ids

    @staticmethod
    async def list_stores(
        job_id: int,
        filters: JobStoreFilters = JobStoreFilters(),
        order: JobStoreOrder = JobStoreOrder.STORE_ID,
        page: PageParams = PageParams(),
    ) -> tuple[list[JobStoreItem], int]:
        async with DBSession.context() as session:
            return await EnrichmentTaskRepository(session).list_stores(
                job_id, filters, order, page
            )

    async def test_lists_every_store_of_the_job_with_its_outcome(
        self, job_id, outcomes
    ):
        items, total = await self.list_stores(job_id)

        assert total == 3
        first, failed, scored = items
        assert first.store_id == "ST000001"
        assert first.store_name == "Fresh Supermarket #1"
        assert first.status == TaskStatus.SUCCEEDED
        assert first.estimated_monthly_footfall == 2000
        assert first.estimated_monthly_revenue == Decimal("1000.50")
        assert (first.score, first.tier) == (20, Tier.SMALL)
        assert failed.status == TaskStatus.FAILED
        assert failed.last_error == "timed out after 10s"
        assert failed.estimated_monthly_footfall is None
        assert (failed.score, failed.tier) == (None, None)
        assert (scored.score, scored.tier) == (100, Tier.LARGE)

    async def test_unscored_stores_have_no_score(self, job_id, task_ids):
        items, _ = await self.list_stores(job_id)

        assert [(item.status, item.score, item.tier) for item in items] == [
            (TaskStatus.PENDING, None, None)
        ] * 3

    @mark.parametrize(
        "filters, store_ids",
        [
            (JobStoreFilters(status=TaskStatus.SUCCEEDED), ["ST000001", "ST000003"]),
            (JobStoreFilters(status=TaskStatus.FAILED), ["ST000002"]),
            (JobStoreFilters(status=TaskStatus.PENDING), []),
            (JobStoreFilters(tier=Tier.LARGE), ["ST000003"]),
            (JobStoreFilters(tier=Tier.MEDIUM), []),
            (JobStoreFilters(status=TaskStatus.FAILED, tier=Tier.LARGE), []),
        ],
    )
    async def test_filters_by_status_and_tier(
        self, job_id, outcomes, filters, store_ids
    ):
        items, total = await self.list_stores(job_id, filters)

        assert [item.store_id for item in items] == store_ids
        assert total == len(store_ids)

    @mark.parametrize(
        "order, store_ids",
        [
            (JobStoreOrder.SCORE, ["ST000003", "ST000001", "ST000002"]),
            (JobStoreOrder.RECENTLY_FINISHED, ["ST000003", "ST000002", "ST000001"]),
            (JobStoreOrder.STORE_ID, ["ST000001", "ST000002", "ST000003"]),
        ],
    )
    async def test_orders(self, job_id, outcomes, order, store_ids):
        items, _ = await self.list_stores(job_id, order=order)

        assert [item.store_id for item in items] == store_ids

    async def test_pages_through_the_stores_with_the_full_total(self, job_id, outcomes):
        first, total = await self.list_stores(job_id, page=PageParams(page_size=2))
        second, _ = await self.list_stores(job_id, page=PageParams(page=2, page_size=2))
        beyond, _ = await self.list_stores(job_id, page=PageParams(page=3, page_size=2))

        assert [item.store_id for item in first] == ["ST000001", "ST000002"]
        assert [item.store_id for item in second] == ["ST000003"]
        assert beyond == []
        assert total == 3

    async def test_an_unknown_job_has_no_stores(self, job_id, task_ids):
        assert await self.list_stores(job_id + 1) == ([], 0)
