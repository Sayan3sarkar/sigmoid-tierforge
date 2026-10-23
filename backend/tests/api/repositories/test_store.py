from uuid import uuid4

from sqlalchemy import select

from api.dependencies.db_session import DBSession
from api.models import Store
from api.repositories.store import StoreRepository
from tests.api.repositories.conftest import store_row


async def get_store_ids(ids: list[int]) -> list[str]:
    async with DBSession.context() as session:
        result = await session.scalars(
            select(Store.store_id).where(Store.id.in_(ids)).order_by(Store.id)
        )
        return list(result)


class TestStoreRepositoryBulkCreate:
    async def test_returns_ids_in_the_order_of_the_rows(self, db):
        rows = [store_row(n) for n in (1, 2, 3)]
        async with DBSession.context() as session:
            ids = await StoreRepository(session).bulk_create(uuid4(), rows)

        assert await get_store_ids(ids) == [row.store_id for row in rows]
