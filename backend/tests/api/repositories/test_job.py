from datetime import UTC, datetime

from sqlalchemy import select

from api.dependencies.db_session import DBSession
from api.models import Job, JobStatus
from api.repositories.job import JobRepository
from api.schemas.jobs import JobUpdate


async def get_job(job_id: int) -> Job:
    async with DBSession.context() as session:
        return await session.scalar(select(Job).where(Job.id == job_id))


class TestJobRepositoryCreate:
    async def test_saves_the_given_fields(self, upload, job_id):
        upload_id, store_ids = upload

        job = await get_job(job_id)

        assert job.upload_id == upload_id
        assert job.total_tasks == len(store_ids)
        assert job.status == JobStatus.PENDING
        assert job.error is None


class TestJobRepositoryUpdate:
    async def test_writes_only_the_fields_passed(self, job_id):
        started_at = datetime(2026, 10, 23, 10, 0, tzinfo=UTC)
        async with DBSession.context() as session:
            await JobRepository(session).update(
                job_id, JobUpdate(status=JobStatus.RUNNING, started_at=started_at)
            )
            await JobRepository(session).update(job_id, JobUpdate(error="boom"))

        job = await get_job(job_id)

        assert job.status == JobStatus.RUNNING
        assert job.started_at == started_at
        assert job.error == "boom"
        assert job.finished_at is None

    async def test_a_field_passed_as_none_is_cleared(self, job_id):
        async with DBSession.context() as session:
            await JobRepository(session).update(job_id, JobUpdate(error="boom"))
            await JobRepository(session).update(job_id, JobUpdate(error=None))

        assert (await get_job(job_id)).error is None


class TestJobRepositoryUpdateIfStatus:
    async def test_writes_the_changes_when_the_status_matches(self, job_id):
        async with DBSession.context() as session:
            updated = await JobRepository(session).update_if_status(
                job_id, JobStatus.PENDING, JobUpdate(status=JobStatus.RUNNING)
            )

        assert updated is True
        assert (await get_job(job_id)).status == JobStatus.RUNNING

    async def test_changes_nothing_when_the_status_differs(self, job_id):
        async with DBSession.context() as session:
            updated = await JobRepository(session).update_if_status(
                job_id, JobStatus.RUNNING, JobUpdate(status=JobStatus.COMPLETED)
            )

        assert updated is False
        assert (await get_job(job_id)).status == JobStatus.PENDING

    async def test_only_the_first_of_two_identical_changes_succeeds(self, job_id):
        # Two workers finishing the same job: exactly one gets to do it.
        changes = JobUpdate(status=JobStatus.COMPLETED)
        async with DBSession.context() as session:
            first = await JobRepository(session).update_if_status(
                job_id, JobStatus.PENDING, changes
            )
            second = await JobRepository(session).update_if_status(
                job_id, JobStatus.PENDING, changes
            )

        assert (first, second) == (True, False)
