from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy import insert

from api.models import Store
from api.repositories.base import BaseRepository
from api.schemas.stores import StoreRow


class StoreRepository(BaseRepository):
    async def bulk_create(self, upload_id: UUID, rows: Sequence[StoreRow]) -> list[int]:
        """Insert every row of one upload, all sharing `upload_id`, in a single
        batched INSERT ... RETURNING.

        Fails as a whole on any database error (e.g. a duplicate store ID within
        the upload). Does not commit.

        Returns the new store ids, in the same order as `rows`.
        """
        result = await self.session.scalars(
            insert(Store).returning(Store.id, sort_by_parameter_order=True),
            [{"upload_id": upload_id, **row.model_dump()} for row in rows],
        )
        return list(result)


StoreRepositoryDep = Annotated[StoreRepository, Depends()]
