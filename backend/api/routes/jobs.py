from fastapi import APIRouter

from api.schemas.errors import ErrorResponse
from api.schemas.scoring import ScoringConfig, ScoringResponse
from api.services.scoring import ScoringServiceDep

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post(
    "/{job_id}/scoring",
    response_model=ScoringResponse,
    responses={
        404: {"model": ErrorResponse, "description": "No such job"},
        409: {
            "model": ErrorResponse,
            "description": "The job's enrichment hasn't finished (or it failed)",
        },
    },
)
async def score_job(
    job_id: int, config: ScoringConfig, service: ScoringServiceDep
) -> ScoringResponse:
    """Score and tier every successfully enriched store of a finished job.

    A store's score is the sum of the weights of the bars it meets (value >=
    bar); its tier comes from the Large and Medium thresholds. Replaces the
    job's previous scores and saves these settings on the job. Uses only saved
    metrics; never calls the enrichment API.
    """
    return await service.score_job(job_id, config)
