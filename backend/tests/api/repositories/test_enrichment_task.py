from asyncio import gather
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pytest import fixture, mark
from sqlalchemy import func, select, update

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


async def set_task(task_id: int, **values) -> None:
    """Write `values` straight onto the task, e.g. to put it in a given state."""
    async with DBSession.context() as session:
        await session.execute(
            update(EnrichmentTask).where(EnrichmentTask.id == task_id).values(**values)
        )
        await session.commit()


async def claim(task_id: int, job_id: int, lease_seconds: float = 25):
    async with DBSession.context() as session:
        lease = await EnrichmentTaskRepository(session).claim(
            task_id, job_id, lease_seconds
        )
        await session.commit()
        return lease


async def fail_job(job_id: int) -> None:
    async with DBSession.context() as session:
        await JobRepository(session).update(job_id, JobUpdate(status=JobStatus.FAILED))


class TestEnrichmentTaskRepositoryClaim:
    @mark.parametrize("status", [TaskStatus.PENDING, TaskStatus.RETRYING])
    async def test_claims_a_task_waiting_for_its_attempt(
        self, job_id, task_ids, status
    ):
        await set_task(task_ids[0], status=status)

        lease = await claim(task_ids[0], job_id, lease_seconds=25)

        task = await get_task(task_ids[0])
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.lease_expires_at == lease
        # now() + 25 s, on the database's clock.
        assert 24 < (lease - datetime.now(UTC)).total_seconds() <= 25

    async def test_takes_over_a_task_whose_lease_expired(self, job_id, task_ids):
        await claim(task_ids[0], job_id)
        await set_task(task_ids[0], lease_expires_at=func.now() - timedelta(seconds=1))

        lease = await claim(task_ids[0], job_id)

        task = await get_task(task_ids[0])
        assert lease is not None
        assert (task.status, task.lease_expires_at) == (TaskStatus.IN_PROGRESS, lease)

    async def test_leaves_a_task_under_a_live_lease_alone(self, job_id, task_ids):
        first = await claim(task_ids[0], job_id)

        assert await claim(task_ids[0], job_id) is None
        assert (await get_task(task_ids[0])).lease_expires_at == first

    @mark.parametrize("status", [TaskStatus.SUCCEEDED, TaskStatus.FAILED])
    async def test_never_claims_a_finished_task(self, job_id, task_ids, status):
        await set_task(task_ids[0], status=status)

        assert await claim(task_ids[0], job_id) is None
        assert (await get_task(task_ids[0])).status == status

    async def test_never_claims_a_task_of_a_failed_job(self, job_id, task_ids):
        await fail_job(job_id)

        assert await claim(task_ids[0], job_id) is None
        assert (await get_task(task_ids[0])).status == TaskStatus.PENDING

    async def test_never_claims_a_task_of_another_job(self, job_id, task_ids):
        assert await claim(task_ids[0], job_id + 1) is None

    async def test_only_one_of_two_concurrent_claims_wins(self, job_id, task_ids):
        leases = await gather(claim(task_ids[0], job_id), claim(task_ids[0], job_id))

        [winner] = [lease for lease in leases if lease is not None]
        assert (await get_task(task_ids[0])).lease_expires_at == winner


class TestEnrichmentTaskRepositoryLeaseFence:
    @staticmethod
    async def succeed(task_id: int, job_id: int, lease) -> bool:
        async with DBSession.context() as session:
            updated = await EnrichmentTaskRepository(session).update_if_status(
                task_id,
                job_id,
                TaskStatus.IN_PROGRESS,
                EnrichmentTaskUpdate(status=TaskStatus.SUCCEEDED),
                lease=lease,
            )
            await session.commit()
            return updated

    async def test_writes_while_the_task_still_has_the_lease(self, job_id, task_ids):
        lease = await claim(task_ids[0], job_id)

        assert await self.succeed(task_ids[0], job_id, lease) is True
        assert (await get_task(task_ids[0])).status == TaskStatus.SUCCEEDED

    async def test_a_late_result_after_a_takeover_changes_nothing(
        self, job_id, task_ids
    ):
        # Handler 1 claims, stalls past its lease; handler 2 takes over.
        first = await claim(task_ids[0], job_id)
        await set_task(task_ids[0], lease_expires_at=func.now() - timedelta(seconds=1))
        second = await claim(task_ids[0], job_id)

        # Handler 1's result is rejected; handler 2's is written.
        assert await self.succeed(task_ids[0], job_id, first) is False
        assert (await get_task(task_ids[0])).status == TaskStatus.IN_PROGRESS
        assert await self.succeed(task_ids[0], job_id, second) is True


class TestEnrichmentTaskRepositoryIsUnfinished:
    @staticmethod
    async def is_unfinished(task_id: int, job_id: int) -> bool:
        async with DBSession.context() as session:
            return await EnrichmentTaskRepository(session).is_unfinished(
                task_id, job_id
            )

    @mark.parametrize(
        "status, unfinished",
        [
            (TaskStatus.PENDING, True),
            (TaskStatus.IN_PROGRESS, True),
            (TaskStatus.RETRYING, True),
            (TaskStatus.SUCCEEDED, False),
            (TaskStatus.FAILED, False),
        ],
    )
    async def test_by_status(self, job_id, task_ids, status, unfinished):
        await set_task(task_ids[0], status=status)

        assert await self.is_unfinished(task_ids[0], job_id) is unfinished

    async def test_a_task_of_a_failed_job_needs_no_more_work(self, job_id, task_ids):
        await fail_job(job_id)

        assert await self.is_unfinished(task_ids[0], job_id) is False

    async def test_unknown_task_or_wrong_job(self, job_id, task_ids):
        assert await self.is_unfinished(task_ids[0], job_id + 1) is False
        assert await self.is_unfinished(max(task_ids) + 1, job_id) is False


class TestEnrichmentTaskRepositoryFailUnfinished:
    async def test_fails_every_unfinished_task_and_ends_its_lease(
        self, job_id, task_ids
    ):
        # Task 0 waits for a retry, task 1 is mid-call, task 2 already succeeded.
        await set_task(task_ids[0], status=TaskStatus.RETRYING, attempt_count=2)
        await claim(task_ids[1], job_id)
        await set_task(task_ids[2], status=TaskStatus.SUCCEEDED)
        finished_at = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)

        async with DBSession.context() as session:
            failed = await EnrichmentTaskRepository(session).fail_unfinished(
                job_id, "job stopped by circuit breaker", finished_at
            )
            await session.commit()

        tasks = [await get_task(task_id) for task_id in task_ids]
        assert failed == 2
        for task in tasks[:2]:
            assert task.status == TaskStatus.FAILED
            assert task.last_error == "job stopped by circuit breaker"
            assert task.finished_at == finished_at
            assert task.lease_expires_at is None
        assert tasks[0].attempt_count == 2  # attempts made are kept
        assert tasks[2].status == TaskStatus.SUCCEEDED


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
