from asyncio import timeout
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging import getLogger

from aiohttp import ClientError, ClientSession, ClientTimeout, TCPConnector
from pydantic import ValidationError

from api.exceptions import (
    EnrichmentConnectionError,
    EnrichmentInvalidResponseError,
    EnrichmentRateLimitedError,
    EnrichmentTimeoutError,
    EnrichmentUpstreamError,
)
from api.schemas.enrichment import EnrichRequest, EnrichResponse
from config import Config

logger = getLogger(__name__)


class EnrichmentClient:
    """Async client for the third-party enrichment API (`POST /enrich`).

    Used by the worker. Open it for the lifetime of the process with
    `async with EnrichmentClient.connect(cfg) as enrichment:`; leaving the block
    closes its connections. It makes exactly one HTTP call per `enrich()`: no
    retries and no rate limiting, which are the caller's job.
    """

    def __init__(self, http: ClientSession, timeout_seconds: float) -> None:
        """`http` must have the API's base URL set; tests point it at a local
        test server."""
        self._http = http
        self._timeout_seconds = timeout_seconds

    @classmethod
    @asynccontextmanager
    async def connect(cls, cfg: Config) -> AsyncIterator["EnrichmentClient"]:
        """Open a pooled aiohttp session for the duration of the `async with`
        block.

        The pool holds one connection per call the worker may have in flight,
        and keeps them open between calls.
        """
        settings = cfg.enrichment
        async with ClientSession(
            base_url=settings.base_url,
            timeout=ClientTimeout(total=settings.timeout_seconds),
            connector=TCPConnector(limit=settings.concurrency),
        ) as http:
            logger.info("Enrichment client ready (%s)", settings.base_url)
            yield cls(http, settings.timeout_seconds)

    async def enrich(self, request: EnrichRequest) -> EnrichResponse:
        """Call `POST /enrich` once for one store and return its metrics.

        Raises an `EnrichmentCallError` subclass, whose message is a short
        reason, if the call doesn't return valid metrics for this store:
        429, any other non-200 status, a timeout, a connection error, or an
        unexpected body.
        """
        try:
            # One deadline for the whole call, from connecting to reading the
            # last byte of the body.
            async with timeout(self._timeout_seconds):
                async with self._http.post(
                    "/enrich", json=request.model_dump()
                ) as response:
                    status = response.status
                    body = await response.read()
        except TimeoutError as e:
            # aiohttp's own timeouts are TimeoutError subclasses too.
            raise EnrichmentTimeoutError(
                f"timed out after {self._timeout_seconds:g}s"
            ) from e
        except ClientError as e:
            # Refused, reset or broken connections, and malformed responses.
            raise EnrichmentConnectionError(
                f"connection failed: {type(e).__name__}"
            ) from e

        if status == 429:
            raise EnrichmentRateLimitedError("rate limited (429)")
        if status != 200:
            raise EnrichmentUpstreamError(f"upstream error ({status})")

        try:
            result = EnrichResponse.model_validate_json(body)
        except ValidationError as e:
            raise EnrichmentInvalidResponseError(
                f"invalid response body: {e.error_count()} error(s)"
            ) from e
        if result.store_id != request.store_id:
            raise EnrichmentInvalidResponseError(
                f"response is for store {result.store_id}, not {request.store_id}"
            )
        return result
