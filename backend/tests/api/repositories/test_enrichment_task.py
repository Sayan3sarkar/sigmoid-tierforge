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
