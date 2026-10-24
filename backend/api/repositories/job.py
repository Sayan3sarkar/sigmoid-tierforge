from typing import Annotated

from fastapi import Depends
from sqlalchemy import func, select, update

from api.models import Job, JobStatus
from api.repositories.base import BaseRepository
from api.schemas.jobs import JobCreate, JobUpdate
from api.schemas.pagination import PageParams


class JobRepository(BaseRepository):
    async def create(self, data: JobCreate) -> Job:
        """Insert one job with exactly the fields in `data`.

        Flushes so Postgres assigns the id, which the caller needs to create the
        job's tasks. Does not commit.

        Returns the new `Job`, with `id` set.
        """
        job = Job(**data.model_dump())
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(self, job_id: int, lock: bool = False) -> Job | None:
        """Return the job with `job_id`, or None if there is none.

        With `lock`, the row is locked (SELECT ... FOR UPDATE) until the
        caller's transaction ends, so callers that lock the same job run one
        after another. Does not commit.
        """
        query = select(Job).where(Job.id == job_id)
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def list_recent(self, page: PageParams) -> tuple[list[Job], int]:
        """Return one page of jobs, newest first, and the total number of jobs.
        Read only."""
        jobs = await self.session.scalars(
            select(Job)
            .order_by(Job.created_at.desc(), Job.id.desc())
            .offset(page.offset)
            .limit(page.page_size)
        )
        total = await self.session.scalar(select(func.count()).select_from(Job))
        return list(jobs), total or 0

    async def update(self, job_id: int, changes: JobUpdate) -> None:
        """Update one job, writing only the fields explicitly set on `changes`.

        Fields left out of `changes` are untouched; a field passed as None is
        cleared. Does nothing if no job has `job_id`. Does not commit.
        """
        await self.session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(**changes.model_dump(exclude_unset=True))
        )

    async def add_failed_call(self, job_id: int) -> int | None:
        """Add one to a RUNNING job's streak of failed calls in a row
        (`consecutive_failures`), in one UPDATE, so concurrent handlers can't
        lose a count. Does not commit; the row stays locked until the caller's
        transaction ends.

        Returns the new streak, or None, changing nothing, if no job has
        `job_id` or it isn't RUNNING.
        """
        result = await self.session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == JobStatus.RUNNING)
            .values(consecutive_failures=Job.consecutive_failures + 1)
            .returning(Job.consecutive_failures)
        )
        return result.scalar_one_or_none()

    async def reset_failed_calls(self, job_id: int) -> None:
        """End a job's streak of failed calls: set `consecutive_failures` to 0.

        Only writes when the streak isn't 0 already, so the usual success, with
        no failures before it, neither writes nor locks the job's row. Does not
        commit.
        """
        await self.session.execute(
            update(Job)
            .where(Job.id == job_id, Job.consecutive_failures > 0)
            .values(consecutive_failures=0)
        )

    async def update_if_status(
        self, job_id: int, expected: JobStatus, changes: JobUpdate
    ) -> bool:
        """Update one job, writing only the fields set on `changes`, if and only
        if its status is still `expected`.

        The check and the write are one UPDATE statement, so when two workers
        both try the same change, exactly one succeeds. Does not commit.

        Returns True if the job was updated; False, changing nothing, if no job
        has `job_id` or its status isn't `expected`.
        """
        result = await self.session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == expected)
            .values(**changes.model_dump(exclude_unset=True))
            .returning(Job.id)
        )
        return result.scalar_one_or_none() is not None


JobRepositoryDep = Annotated[JobRepository, Depends()]
