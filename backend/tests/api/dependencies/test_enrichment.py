from asyncio import sleep
from collections.abc import Awaitable, Callable
from decimal import Decimal
from socket import socket

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from aiohttp.web import Application, Request, Response, json_response
from pytest import fixture, mark, raises

from api.dependencies.enrichment import EnrichmentClient
from api.exceptions import (
    EnrichmentCallError,
    EnrichmentConnectionError,
    EnrichmentInvalidResponseError,
    EnrichmentRateLimitedError,
    EnrichmentTimeoutError,
    EnrichmentUpstreamError,
)
from api.schemas.enrichment import EnrichRequest, EnrichResponse
from config import cfg

REQUEST = EnrichRequest(
    store_id="ST000001",
    store_name="Fresh Supermarket #1",
    address="71 Church Street",
    city="New Delhi",
    state="Delhi",
)
METRICS = {
    "store_id": "ST000001",
    "estimated_monthly_footfall": 18234,
    "estimated_monthly_revenue": 142033.50,
    "store_size_sqft": 6210,
}

Handler = Callable[[Request], Awaitable[Response]]


@fixture
async def client_for():
    """Start a local test server answering `POST /enrich` with a given handler,
    and return an EnrichmentClient pointed at it. Everything is closed after
    the test."""
    opened: list[tuple[TestServer, ClientSession]] = []

    async def start(handler: Handler, timeout_seconds: float = 10) -> EnrichmentClient:
        app = Application()
        app.router.add_post("/enrich", handler)
        server = TestServer(app)
        await server.start_server()
        http = ClientSession(base_url=str(server.make_url("/")))
        opened.append((server, http))
        return EnrichmentClient(http, timeout_seconds)

    yield start
    for server, http in opened:
        await http.close()
        await server.close()


def respond(status: int, body: dict | None = None) -> Handler:
    async def handler(request: Request) -> Response:
        return json_response(body or {"detail": "x"}, status=status)

    return handler


class TestEnrichmentClientSuccess:
    async def test_posts_the_store_and_returns_its_metrics(self, client_for):
        received: list[dict] = []

        async def handler(request: Request) -> Response:
            received.append(await request.json())
            return json_response(METRICS)

        result = await (await client_for(handler)).enrich(REQUEST)

        assert result == EnrichResponse(
            store_id="ST000001",
            estimated_monthly_footfall=18234,
            estimated_monthly_revenue=Decimal("142033.5"),
            store_size_sqft=6210,
        )
        assert received == [REQUEST.model_dump()]


class TestEnrichmentClientFailures:
    @mark.parametrize(
        "status, error, reason",
        [
            (429, EnrichmentRateLimitedError, r"rate limited \(429\)"),
            (500, EnrichmentUpstreamError, r"upstream error \(500\)"),
            (503, EnrichmentUpstreamError, r"upstream error \(503\)"),
        ],
    )
    async def test_an_error_status_raises_with_its_reason(
        self, client_for, status, error, reason
    ):
        client = await client_for(respond(status))

        with raises(error, match=reason):
            await client.enrich(REQUEST)

    async def test_a_slow_call_times_out(self, client_for):
        async def handler(request: Request) -> Response:
            await sleep(1)
            return json_response(METRICS)

        client = await client_for(handler, timeout_seconds=0.05)

        with raises(EnrichmentTimeoutError, match="timed out after 0.05s"):
            await client.enrich(REQUEST)

    async def test_a_refused_connection_raises(self):
        # A port nothing listens on: bind a free one, then release it.
        with socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        async with ClientSession(base_url=f"http://127.0.0.1:{port}") as http:
            client = EnrichmentClient(http, timeout_seconds=10)
            with raises(
                EnrichmentConnectionError,
                match="connection failed: ClientConnectorError",
            ):
                await client.enrich(REQUEST)

    async def test_a_body_without_metrics_is_invalid(self, client_for):
        client = await client_for(respond(200, {"store_id": "ST000001"}))

        with raises(EnrichmentInvalidResponseError, match="invalid response body"):
            await client.enrich(REQUEST)

    async def test_metrics_for_another_store_are_invalid(self, client_for):
        client = await client_for(respond(200, {**METRICS, "store_id": "ST000002"}))

        with raises(EnrichmentInvalidResponseError, match="not ST000001"):
            await client.enrich(REQUEST)

    async def test_every_failure_is_an_enrichment_call_error(self, client_for):
        # The worker catches this base class to mark the task FAILED.
        client = await client_for(respond(500))

        with raises(EnrichmentCallError):
            await client.enrich(REQUEST)


class TestEnrichmentClientConnect:
    async def test_uses_the_configured_base_url_timeout_and_pool_size(self):
        async with EnrichmentClient.connect(cfg) as client:
            http = client._http
            assert str(http._base_url).rstrip("/") == cfg.enrichment.base_url
            assert http.timeout.total == cfg.enrichment.timeout_seconds
            assert http.connector.limit == cfg.enrichment.concurrency
            assert client._timeout_seconds == cfg.enrichment.timeout_seconds

        assert http.closed
