from uuid import UUID, uuid4

from pytest import fixture

from api.dependencies.db_session import DBSession
from api.models import JobStatus
from api.repositories.job import JobRepository
from api.repositories.store import StoreRepository
from api.schemas.jobs import JobCreate
from api.schemas.stores import StoreRow


def store_row(n: int) -> StoreRow:
    return StoreRow(
        store_id=f"ST{n:06d}",
        store_name=f"Fresh Supermarket #{n}",
        address="71 Church Street",
        city="New Delhi",
        state="Delhi",
        country="India",
    )


@fixture
async def db(test_database):
    """The shared engine, opened against the test database for one test."""
    DBSession.create()
    yield
    await DBSession.close()


@fixture
async def upload(db) -> tuple[UUID, list[int]]:
    """Three committed stores of one upload: (upload_id, store ids)."""
    upload_id = uuid4()
    async with DBSession.context() as session:
        store_ids = await StoreRepository(session).bulk_create(
            upload_id, [store_row(n) for n in (1, 2, 3)]
        )
    return upload_id, store_ids


@fixture
async def job_id(upload) -> int:
    """A committed PENDING job for `upload`."""
    upload_id, store_ids = upload
    async with DBSession.context() as session:
        job = await JobRepository(session).create(
            JobCreate(
                upload_id=upload_id,
                total_tasks=len(store_ids),
                status=JobStatus.PENDING,
            )
        )
    return job.id
