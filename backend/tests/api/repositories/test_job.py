from datetime import UTC, datetime

from pytest import raises
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from api.dependencies.db_session import DBSession
from api.models import Job, JobStatus
from api.repositories.job import JobRepository
from api.schemas.jobs import JobCreate, JobUpdate
from api.schemas.pagination import PageParams


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


class TestJobRepositoryGet:
    async def test_returns_the_job(self, upload, job_id):
        upload_id, _ = upload
        async with DBSession.context() as session:
            job = await JobRepository(session).get(job_id)

        assert job.id == job_id
        assert job.upload_id == upload_id
        assert job.scoring_config is None

    async def test_returns_none_for_an_unknown_id(self, job_id):
        async with DBSession.context() as session:
            assert await JobRepository(session).get(job_id + 1) is None

    async def test_lock_blocks_a_second_locker_until_the_first_commits(self, job_id):
        async with DBSession.context() as first:
            await JobRepository(first).get(job_id, lock=True)

            async with DBSession.context() as second:
                # Give up after 50 ms instead of waiting for the first lock.
                await second.execute(text("SET LOCAL lock_timeout = '50ms'"))
                with raises(DBAPIError, match="lock timeout"):
                    await JobRepository(second).get(job_id, lock=True)
                await second.rollback()

    async def test_saves_a_scoring_config_as_json(self, job_id):
        config = {"bars": {"footfall": 15000}, "tiers": {"large_min": 70}}
        async with DBSession.context() as session:
            await JobRepository(session).update(
                job_id, JobUpdate(scoring_config=config)
            )

        assert (await get_job(job_id)).scoring_config == config


class TestJobRepositoryListRecent:
    async def test_returns_jobs_newest_first_with_the_total(self, upload):
        upload_id, store_ids = upload
        async with DBSession.context() as session:
            repository = JobRepository(session)
            created = [
                await repository.create(
                    JobCreate(
                        upload_id=upload_id, total_tasks=1, status=JobStatus.PENDING
                    )
                )
                for _ in range(3)
            ]
            # Other tests' jobs share this database, so compare the first page
            # against the three newest and the total against a fresh count.
            jobs, total = await repository.list_recent(PageParams(page_size=3))
            all_jobs = await session.scalar(select(func.count()).select_from(Job))

        assert [job.id for job in jobs] == [job.id for job in reversed(created)]
        assert total == all_jobs

    async def test_pages_through_the_jobs(self, upload):
        upload_id, _ = upload
        async with DBSession.context() as session:
            repository = JobRepository(session)
            for _ in range(3):
                await repository.create(
                    JobCreate(
                        upload_id=upload_id, total_tasks=1, status=JobStatus.PENDING
                    )
                )
            first, _ = await repository.list_recent(PageParams(page=1, page_size=2))
            second, _ = await repository.list_recent(PageParams(page=2, page_size=2))

        assert len(first) == 2
        assert first[-1].created_at >= second[0].created_at
        assert {job.id for job in first}.isdisjoint(job.id for job in second)
