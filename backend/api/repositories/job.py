from typing import Annotated

from fastapi import Depends
from sqlalchemy import update

from api.models import Job
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


JobRepositoryDep = Annotated[JobRepository, Depends()]
