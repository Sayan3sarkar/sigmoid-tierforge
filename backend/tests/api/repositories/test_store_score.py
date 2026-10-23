from datetime import UTC, datetime

from pytest import fixture
from sqlalchemy import select

from api.dependencies.db_session import DBSession
from api.models import StoreScore, Tier
from api.repositories.store_score import StoreScoreRepository
from api.schemas.store_scores import StoreScoreCreate

SCORED_AT = datetime(2026, 10, 23, 10, 0, tzinfo=UTC)


async def scores_of(job_id: int) -> list[tuple[int, int, str]]:
    async with DBSession.context() as session:
        result = await session.execute(
            select(StoreScore.task_id, StoreScore.score, StoreScore.tier)
            .where(StoreScore.job_id == job_id)
            .order_by(StoreScore.task_id)
        )
        return [tuple(row) for row in result]


def score(job_id: int, task_id: int, value: int, tier: Tier) -> StoreScoreCreate:
    return StoreScoreCreate(
        job_id=job_id, task_id=task_id, score=value, tier=tier, scored_at=SCORED_AT
    )


@fixture
async def replace(db):
    async def run(job_id: int, scores: list[StoreScoreCreate]) -> None:
        async with DBSession.context() as session:
            await StoreScoreRepository(session).replace_for_job(job_id, scores)

    return run


class TestStoreScoreRepositoryReplaceForJob:
    async def test_inserts_the_scores(self, replace, job_id, task_ids):
        await replace(
            job_id,
            [
                score(job_id, task_ids[0], 100, Tier.LARGE),
                score(job_id, task_ids[1], 50, Tier.MEDIUM),
            ],
        )

        assert await scores_of(job_id) == [
            (task_ids[0], 100, Tier.LARGE),
            (task_ids[1], 50, Tier.MEDIUM),
        ]

    async def test_a_second_run_leaves_only_its_own_scores(
        self, replace, job_id, task_ids
    ):
        await replace(
            job_id,
            [
                score(job_id, task_ids[0], 100, Tier.LARGE),
                score(job_id, task_ids[1], 50, Tier.MEDIUM),
            ],
        )

        await replace(job_id, [score(job_id, task_ids[0], 20, Tier.SMALL)])

        assert await scores_of(job_id) == [(task_ids[0], 20, Tier.SMALL)]

    async def test_no_scores_clears_the_job(self, replace, job_id, task_ids):
        await replace(job_id, [score(job_id, task_ids[0], 100, Tier.LARGE)])

        await replace(job_id, [])

        assert await scores_of(job_id) == []

    async def test_saves_the_given_scored_at(self, replace, job_id, task_ids):
        await replace(job_id, [score(job_id, task_ids[0], 100, Tier.LARGE)])

        async with DBSession.context() as session:
            scored_at = await session.scalar(
                select(StoreScore.scored_at).where(StoreScore.job_id == job_id)
            )
        assert scored_at == SCORED_AT


class TestStoreScoreRepositoryCountByTier:
    async def test_counts_the_jobs_scores_per_tier(self, replace, job_id, task_ids):
        await replace(
            job_id,
            [
                score(job_id, task_ids[0], 100, Tier.LARGE),
                score(job_id, task_ids[1], 90, Tier.LARGE),
                score(job_id, task_ids[2], 20, Tier.SMALL),
            ],
        )

        async with DBSession.context() as session:
            counts = await StoreScoreRepository(session).count_by_tier(job_id)

        assert counts == {Tier.LARGE: 2, Tier.SMALL: 1}

    async def test_an_unscored_job_has_no_counts(self, db, job_id):
        async with DBSession.context() as session:
            assert await StoreScoreRepository(session).count_by_tier(job_id) == {}
