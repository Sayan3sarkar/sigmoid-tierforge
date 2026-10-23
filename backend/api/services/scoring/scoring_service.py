from datetime import UTC, datetime
from logging import getLogger
from typing import Annotated

from fastapi import Depends

from api.dependencies.db_session import DbSessionDep
from api.exceptions import JobNotFoundError, JobNotScorableError
from api.models import JobStatus
from api.repositories.enrichment_task import EnrichmentTaskRepositoryDep
from api.repositories.job import JobRepositoryDep
from api.repositories.store_score import StoreScoreRepositoryDep
from api.schemas.jobs import JobUpdate
from api.schemas.scoring import ScoringConfig, ScoringResponse, TierCounts
from api.schemas.store_scores import StoreScoreCreate
from api.services.scoring.scorer import StoreScorer

logger = getLogger(__name__)

# Enrichment has finished, so the set of stores to score is final.
SCORABLE_STATUSES = frozenset({JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_FAILURES})


class ScoringService:
    """Scores and tiers every successfully enriched store of a job, using only
    the metrics already saved. Never calls the enrichment API."""

    def __init__(
        self,
        jobs_repository: JobRepositoryDep,
        tasks_repository: EnrichmentTaskRepositoryDep,
        scores_repository: StoreScoreRepositoryDep,
        session: DbSessionDep,
    ) -> None:
        self._jobs_repository = jobs_repository
        self._enrichment_tasks_repository = tasks_repository
        self._scores_repository = scores_repository
        self._session = session

    async def score_job(
        self, job_id: int, scoring_config: ScoringConfig
    ) -> ScoringResponse:
        """Score the job's SUCCEEDED stores with `scoring_config`, replace its previous
        scores, save `scoring_config` on the job, and commit, all in one transaction.

        Readers see either the old scores or the new ones, never a mix. Running
        it again with the same config gives the same scores.

        Raises JobNotFoundError (404) if there's no such job, and
        JobNotScorableError (409) unless its enrichment has finished.
        """
        # 1. Load the job, locking it so two scoring runs of the same job happen
        #    one after the other instead of interleaving their delete and insert.
        job = await self._jobs_repository.get(job_id, lock=True)
        if job is None:
            raise JobNotFoundError(f"Job {job_id} not found.")
        if job.status not in SCORABLE_STATUSES:
            raise JobNotScorableError(
                f"Job {job_id} is {job.status}; it can be scored once enrichment "
                f"has finished ({JobStatus.COMPLETED} or "
                f"{JobStatus.COMPLETED_WITH_FAILURES})."
            )

        # 2. Read every succeeded store's metrics in one query and score them.
        metrics = await self._enrichment_tasks_repository.list_succeeded_metrics(job_id)
        scored_at = datetime.now(UTC)
        new_scores: list[StoreScoreCreate] = []
        for task in metrics:
            score = StoreScorer.score_store(
                task.estimated_monthly_footfall,
                task.estimated_monthly_revenue,
                task.store_size_sqft,
                scoring_config,
            )
            new_scores.append(
                StoreScoreCreate(
                    job_id=job_id,
                    task_id=task.task_id,
                    score=score,
                    tier=StoreScorer.tier_for(score, scoring_config.tiers),
                    scored_at=scored_at,
                )
            )

        # 3. Replace the job's scores (one delete, one bulk insert) and save the
        #    settings they were computed with.
        await self._scores_repository.replace_for_job(job_id, new_scores)
        await self._jobs_repository.update(
            job_id,
            JobUpdate(
                scoring_config=scoring_config.model_dump(mode="json"),
                scored_at=scored_at,
            ),
        )
        counts = await self._scores_repository.count_by_tier(job_id)

        # 4. One commit for all of it.
        await self._session.commit()
        logger.info("Job %s scored: %d stores, %s", job_id, len(new_scores), counts)
        return ScoringResponse(
            job_id=job_id,
            scored_count=len(new_scores),
            tiers=TierCounts(**{tier.value: count for tier, count in counts.items()}),
            config=scoring_config,
            scored_at=scored_at,
        )


ScoringServiceDep = Annotated[ScoringService, Depends()]
