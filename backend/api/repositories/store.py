from collections.abc import Sequence
from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy import insert

from api.models import Store
from api.repositories.base import BaseRepository
from api.schemas.stores import StoreRow


class StoreRepository(BaseRepository):
    async def bulk_create(self, upload_id: UUID, rows: Sequence[StoreRow]) -> int:
        """Insert all rows of one upload in a single batched statement."""
        await self.session.execute(
            insert(Store), [{"upload_id": upload_id, **asdict(row)} for row in rows]
        )
        return len(rows)


StoreRepositoryDep = Annotated[StoreRepository, Depends()]
