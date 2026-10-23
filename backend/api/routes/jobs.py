from fastapi import APIRouter

from api.schemas.errors import ErrorResponse
from api.schemas.jobs import JobListItem, JobResponse, JobSummary
from api.schemas.pagination import Page, PageParamsDep
from api.schemas.scoring import ScoringConfig, ScoringResponse
from api.schemas.stores import JobStoreFiltersDep, JobStoreItem
from api.services.jobs import EnrichmentJobServiceDep
from api.services.scoring import ScoringServiceDep

router = APIRouter(prefix="/jobs", tags=["jobs"])

NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such job"}}


@router.get("", response_model=Page[JobListItem])
async def list_jobs(
    page: PageParamsDep, service: EnrichmentJobServiceDep
) -> Page[JobListItem]:
    """List jobs, newest first, paginated."""
    return await service.list_jobs(page)


@router.get("/{job_id}", response_model=JobResponse, responses=NOT_FOUND)
async def get_job(job_id: int, service: EnrichmentJobServiceDep) -> JobResponse:
    """A job's status, timestamps, error, and task counts per status
    (progress)."""
    return await service.get_job(job_id)


@router.get("/{job_id}/summary", response_model=JobSummary, responses=NOT_FOUND)
async def get_job_summary(job_id: int, service: EnrichmentJobServiceDep) -> JobSummary:
    """Task counts per status, and the latest scoring (when, with which
    settings, and the Large / Medium / Small counts), or null if the job
    hasn't been scored."""
    return await service.get_summary(job_id)


@router.get("/{job_id}/stores", response_model=Page[JobStoreItem], responses=NOT_FOUND)
async def list_job_stores(
    job_id: int,
    filters: JobStoreFiltersDep,
    page: PageParamsDep,
    service: EnrichmentJobServiceDep,
) -> Page[JobStoreItem]:
    """The job's stores with status, metrics, error, score and tier, paginated.

    Filter by `status` (pending, in_progress, succeeded, failed) and/or `tier`
    (large, medium, small). Ordered by score with a tier or `status=succeeded`,
    by most recent failure with `status=failed`, otherwise by store_id.
    """
    return await service.list_stores(job_id, filters, page)


@router.post(
    "/{job_id}/scoring",
    response_model=ScoringResponse,
    responses={
        **NOT_FOUND,
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
