from typing import Annotated

from fastapi import Depends
from sqlalchemy import select, update

from api.models import Job, JobStatus
from api.repositories.base import BaseRepository
from api.schemas.jobs import JobCreate, JobUpdate


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
