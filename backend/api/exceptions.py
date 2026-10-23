from logging import getLogger

from fastapi import FastAPI, Request
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


class SQSQueueUnavailableError(RuntimeError):
    """The configured SQS queue can't be reached (wrong URL, missing queue, no access).

    Raised at worker startup; not an AppError, since it never reaches an API client.
    """


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
