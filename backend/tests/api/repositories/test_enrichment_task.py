from datetime import UTC, datetime
from decimal import Decimal

from pytest import fixture
from sqlalchemy import select

from api.dependencies.db_session import DBSession
from api.models import EnrichmentTask, JobStatus, TaskStatus
from api.repositories.enrichment_task import EnrichmentTaskRepository
from api.repositories.job import JobRepository
from api.schemas.enrichment_tasks import EnrichmentTaskCreate, EnrichmentTaskUpdate
from api.schemas.jobs import JobUpdate


async def get_task(task_id: int) -> EnrichmentTask:
    async with DBSession.context() as session:
        return await session.scalar(
            select(EnrichmentTask).where(EnrichmentTask.id == task_id)
        )


@fixture
async def task_ids(upload, job_id) -> list[int]:
    """One committed PENDING task per store of `upload`."""
    _, store_ids = upload
    async with DBSession.context() as session:
        return await EnrichmentTaskRepository(session).bulk_create(
            [
                EnrichmentTaskCreate(
                    job_id=job_id, store_id=store_id, status=TaskStatus.PENDING
                )
                for store_id in store_ids
            ]
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
