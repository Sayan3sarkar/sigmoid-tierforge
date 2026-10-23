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


class TestStoreRepositoryGet:
    async def test_returns_the_store_by_primary_key(self, upload):
        upload_id, store_ids = upload
        async with DBSession.context() as session:
            store = await StoreRepository(session).get(store_ids[1])

        assert store.id == store_ids[1]
        assert store.upload_id == upload_id
        assert store.store_id == "ST000002"

    async def test_returns_none_for_an_unknown_id(self, upload):
        _, store_ids = upload
        async with DBSession.context() as session:
            assert await StoreRepository(session).get(max(store_ids) + 1) is None
