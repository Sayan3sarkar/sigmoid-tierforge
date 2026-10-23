from logging import getLogger

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.schemas.errors import ErrorResponse

logger = getLogger(__name__)


class AppError(Exception):
    """Base for errors that map to a client-facing HTTP response."""

    status_code = 400

    def __init__(self, detail: str, errors: list[str] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.errors = errors or []


class InvalidUploadError(AppError):
    """The uploaded file can't be accepted (wrong type, bad header, bad rows)."""

    status_code = 422


class UploadTooLargeError(AppError):
    status_code = 413


class EnrichmentDispatchError(AppError):
    """The stores were saved but their enrichment events could not be sent."""

    status_code = 503


class JobNotFoundError(AppError):
    """No job has the requested id."""

    status_code = 404


class JobNotScorableError(AppError):
    """The job exists but can't be scored in its current status."""

    status_code = 409


class SQSQueueUnavailableError(RuntimeError):
    """The configured SQS queue can't be reached (wrong URL, missing queue, no access).

    Raised at worker startup; not an AppError, since it never reaches an API client.
    """


class SQSSendError(RuntimeError):
    """SQS rejected one or more messages of a batch."""


class EnrichmentCallError(RuntimeError):
    """An enrichment API call didn't return usable metrics.

    The message is the short reason saved on the failed task (`last_error`).
    Raised in the worker; not an AppError, since it never reaches an API client.
    """


class EnrichmentRateLimitedError(EnrichmentCallError):
    """The API answered 429: calls exceeded its rate limit."""


class EnrichmentUpstreamError(EnrichmentCallError):
    """The API answered with an error status other than 429, e.g. 500."""


class EnrichmentTimeoutError(EnrichmentCallError):
    """The call didn't complete within the timeout."""


class EnrichmentConnectionError(EnrichmentCallError):
    """The API couldn't be reached, or the connection broke mid-call."""


class EnrichmentInvalidResponseError(EnrichmentCallError):
    """The API answered 200, but the body isn't valid metrics for the store."""


def register_exception_handlers(app: FastAPI) -> None:
    # The decorator (unlike app.add_exception_handler) accepts a handler typed for
    # the specific exception, so `exc: AppError` type-checks without casts.
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.info(
            "%s %s -> %s: %s",
            request.method,
            request.url.path,
            exc.status_code,
            exc.detail,
        )
        body = ErrorResponse(detail=exc.detail, errors=exc.errors)
        return JSONResponse(status_code=exc.status_code, content=body.model_dump())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Invalid query parameters or body: 422 in the same shape as every
        other error, with one readable line per problem."""
        errors = [describe_validation_error(error) for error in exc.errors()]
        logger.info(
            "%s %s -> 422: %s", request.method, request.url.path, "; ".join(errors)
        )
        body = ErrorResponse(detail="Invalid request.", errors=errors)
        return JSONResponse(status_code=422, content=body.model_dump())


def describe_validation_error(error: dict) -> str:
    """One validation error as `<where>.<field>: <message>`, e.g.
    `query.page_size: Input should be less than or equal to 200` or
    `body.weights: weights must add up to 100, not 110`."""
    location = ".".join(str(part) for part in error.get("loc", ()))
    # Our own validators' messages come prefixed by Pydantic.
    message = str(error.get("msg", "")).removeprefix("Value error, ")
    return f"{location}: {message}" if location else message
