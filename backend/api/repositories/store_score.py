from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from sqlalchemy import delete, func, insert, select

from api.models import StoreScore, Tier
from api.repositories.base import BaseRepository
from api.schemas.store_scores import StoreScoreCreate


class StoreScoreRepository(BaseRepository):
    async def replace_for_job(
        self, job_id: int, scores: Sequence[StoreScoreCreate]
    ) -> None:
        """Delete every score of the job, then insert `scores` in one batched
        statement.

        Does not commit: the caller commits the delete and the insert together,
        so readers see either all the old scores or all the new ones.
        """
        await self.session.execute(
            delete(StoreScore).where(StoreScore.job_id == job_id)
        )
        if scores:
            await self.session.execute(
                insert(StoreScore), [score.model_dump() for score in scores]
            )

    async def count_by_tier(self, job_id: int) -> dict[Tier, int]:
        """Count the job's scores per tier, in one grouped query served by the
        (job_id, tier) index. Read only.

        Tiers with no stores are left out; an unscored job gives {}.
        """
        result = await self.session.execute(
            select(StoreScore.tier, func.count())
            .where(StoreScore.job_id == job_id)
            .group_by(StoreScore.tier)
        )
        return {Tier(tier): count for tier, count in result}


StoreScoreRepositoryDep = Annotated[StoreScoreRepository, Depends()]
