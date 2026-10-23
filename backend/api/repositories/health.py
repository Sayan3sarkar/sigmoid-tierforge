from typing import Annotated

from fastapi import Depends
from sqlalchemy import text

from api.repositories.base import BaseRepository


class HealthRepository(BaseRepository):
    async def ping(self) -> None:
        """Round trip to Postgres; raises if the database can't be reached."""
        await self.session.execute(text("SELECT 1"))


HealthRepositoryDep = Annotated[HealthRepository, Depends()]
