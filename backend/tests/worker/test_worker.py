from asyncio import CancelledError, Event, sleep
from decimal import Decimal
from logging import INFO
from uuid import uuid4

from pytest import fixture, mark, raises
from sqlalchemy import select

from api.dependencies.aws.sqs import (
    ReceivedMessage,
    SQSClient,
)
from api.dependencies.db_session import DBSession
from api.dependencies.enrichment import EnrichmentClient
from api.exceptions import (
    EnrichmentConnectionError,
    EnrichmentRateLimitedError,
    EnrichmentTimeoutError,
    EnrichmentUpstreamError,
    SQSQueueUnavailableError,
)
from api.models import EnrichmentTask, Job, JobStatus, TaskStatus
from api.repositories.enrichment_task import EnrichmentTaskRepository
from api.repositories.job import JobRepository
from api.repositories.store import StoreRepository
from api.schemas.enrichment import EnrichRequest, EnrichResponse
from api.schemas.enrichment_tasks import EnrichmentTaskCreate
from api.schemas.jobs import JobCreate, JobUpdate
from api.schemas.messages import EVENT_VERSION, EnrichmentEvent, EnrichStorePayload
from api.schemas.stores import StoreRow
from config import cfg
from worker.rate_limiter import TokenBucket
from worker.worker import EnrichmentWorker


class TestEnrichmentWorkerProcessMessage:
    @staticmethod
    def make_received(body: str) -> ReceivedMessage:
        return ReceivedMessage(
            message_id="msg-1", receipt_handle="receipt-1", body=body
        )

    @staticmethod
    def make_event(version: int = EVENT_VERSION) -> EnrichmentEvent:
        return EnrichmentEvent(
            version=version, payload=EnrichStorePayload(job_id=7, task_id=42)
        )

    @fixture
    def worker(self, sqs_client):
        return EnrichmentWorker(cfg, sqs=sqs_client)

    @fixture
    def handler(self, mocker, worker):
        return mocker.patch.object(
            worker, "handle_event", new_callable=mocker.AsyncMock
        )

    async def test_valid_event_is_handled_then_deleted(
        self, worker, handler, sqs_client
    ):
        event = self.make_event()

        await worker.process_message(self.make_received(event.model_dump_json()))

        handler.assert_awaited_once_with(event)
        sqs_client.delete_message.assert_awaited_once_with(
            cfg.sqs.enrichment_queue_url, "receipt-1"
        )

    async def test_malformed_message_is_deleted_without_handling(
        self, worker, handler, sqs_client
    ):
        await worker.process_message(self.make_received('{"unexpected": true}'))

        handler.assert_not_awaited()
        sqs_client.delete_message.assert_awaited_once_with(
            cfg.sqs.enrichment_queue_url, "receipt-1"
        )

    async def test_unsupported_event_version_is_deleted_without_handling(
        self, worker, handler, sqs_client
    ):
        event = self.make_event(version=EVENT_VERSION + 1)

        await worker.process_message(self.make_received(event.model_dump_json()))

        handler.assert_not_awaited()
        sqs_client.delete_message.assert_awaited_once_with(
            cfg.sqs.enrichment_queue_url, "receipt-1"
        )

    async def test_message_is_kept_when_handler_fails(
        self, worker, handler, sqs_client
    ):
        handler.side_effect = RuntimeError("boom")

        await worker.process_message(
            self.make_received(self.make_event().model_dump_json())
        )

        sqs_client.delete_message.assert_not_awaited()


class TestEnrichmentWorkerHandleEvent:
    """Runs against the test database; only the enrichment API is mocked."""

    METRICS = EnrichResponse(
        store_id="ST000001",
        estimated_monthly_footfall=18234,
        estimated_monthly_revenue=Decimal("142033.50"),
        store_size_sqft=6210,
    )

    @fixture
    async def db(self, test_database):
        DBSession.create()
        yield
        await DBSession.close()

    @staticmethod
    async def running_job(store_count: int) -> tuple[int, list[int]]:
        """A RUNNING job with one PENDING task per store: (job id, task ids)."""
        upload_id = uuid4()
        rows = [
            StoreRow(
                store_id=f"ST{n:06d}",
                store_name=f"Fresh Supermarket #{n}",
                address="71 Church Street",
                city="New Delhi",
                state="Delhi",
                country="India",
            )
            for n in range(1, store_count + 1)
        ]
        async with DBSession.context() as session:
            store_ids = await StoreRepository(session).bulk_create(upload_id, rows)
            job = await JobRepository(session).create(
                JobCreate(
                    upload_id=upload_id,
                    total_tasks=store_count,
                    status=JobStatus.RUNNING,
                )
            )
            task_ids = await EnrichmentTaskRepository(session).bulk_create(
                [
                    EnrichmentTaskCreate(
                        job_id=job.id, store_id=store_id, status=TaskStatus.PENDING
                    )
                    for store_id in store_ids
                ]
            )
        return job.id, task_ids

    @fixture
    async def one_task(self, db):
        job_id, [task_id] = await self.running_job(1)
        return job_id, task_id

    @fixture
    def enrichment(self, mocker):
        client = mocker.AsyncMock(spec=EnrichmentClient)
        client.enrich.return_value = self.METRICS
        return client

    @fixture
    def limiter(self, mocker):
        return mocker.AsyncMock(spec=TokenBucket)

    @fixture
    def worker(self, sqs_client, enrichment, limiter):
        return EnrichmentWorker(
            cfg, sqs=sqs_client, enrichment=enrichment, limiter=limiter
        )

    @staticmethod
    async def get_task(task_id: int) -> EnrichmentTask:
        async with DBSession.context() as session:
            return await session.scalar(
                select(EnrichmentTask).where(EnrichmentTask.id == task_id)
            )

    @staticmethod
    async def job_status(job_id: int) -> str:
        async with DBSession.context() as session:
            return await session.scalar(select(Job.status).where(Job.id == job_id))

    @staticmethod
    def event_for(job_id: int, task_id: int) -> EnrichmentEvent:
        return EnrichmentEvent(
            payload=EnrichStorePayload(job_id=job_id, task_id=task_id)
        )

    async def test_success_saves_the_metrics_and_completes_the_job(
        self, worker, enrichment, limiter, one_task
    ):
        job_id, task_id = one_task

        await worker.handle_event(self.event_for(job_id, task_id))

        enrichment.enrich.assert_awaited_once_with(
            EnrichRequest(
                store_id="ST000001",
                store_name="Fresh Supermarket #1",
                address="71 Church Street",
                city="New Delhi",
                state="Delhi",
            )
        )
        limiter.acquire.assert_awaited_once()
        task = await self.get_task(task_id)
        assert task.status == TaskStatus.SUCCEEDED
        assert task.estimated_monthly_footfall == 18234
        assert task.estimated_monthly_revenue == Decimal("142033.50")
        assert task.store_size_sqft == 6210
        assert task.attempt_count == 1
        assert task.last_error is None
        assert task.finished_at is not None
        assert await self.job_status(job_id) == JobStatus.COMPLETED

    @mark.parametrize(
        "error",
        [
            EnrichmentRateLimitedError("rate limited (429)"),
            EnrichmentUpstreamError("upstream error (500)"),
            EnrichmentTimeoutError("timed out after 10s"),
            EnrichmentConnectionError("connection failed: ConnectError"),
        ],
    )
    async def test_a_failed_call_fails_the_task_with_its_reason(
        self, worker, enrichment, one_task, error
    ):
        job_id, task_id = one_task
        enrichment.enrich.side_effect = error

        await worker.handle_event(self.event_for(job_id, task_id))

        task = await self.get_task(task_id)
        assert task.status == TaskStatus.FAILED
        assert task.last_error == str(error)
        assert task.attempt_count == 1
        assert task.estimated_monthly_footfall is None
        assert task.finished_at is not None
        assert await self.job_status(job_id) == JobStatus.COMPLETED_WITH_FAILURES

    async def test_the_job_keeps_running_until_its_last_task_finishes(self, worker, db):
        job_id, task_ids = await self.running_job(2)

        await worker.handle_event(self.event_for(job_id, task_ids[0]))
        assert await self.job_status(job_id) == JobStatus.RUNNING

        await worker.handle_event(self.event_for(job_id, task_ids[1]))
        assert await self.job_status(job_id) == JobStatus.COMPLETED

    async def test_duplicate_delivery_is_skipped_without_calling_the_api(
        self, worker, enrichment, one_task, caplog
    ):
        job_id, task_id = one_task
        caplog.set_level(INFO, logger="worker")

        await worker.handle_event(self.event_for(job_id, task_id))
        await worker.handle_event(self.event_for(job_id, task_id))

        enrichment.enrich.assert_awaited_once()
        assert (await self.get_task(task_id)).status == TaskStatus.SUCCEEDED
        assert "skipped" in caplog.text

    async def test_task_of_a_failed_job_is_skipped_without_calling_the_api(
        self, worker, enrichment, limiter, one_task
    ):
        job_id, task_id = one_task
        async with DBSession.context() as session:
            await JobRepository(session).update(
                job_id, JobUpdate(status=JobStatus.FAILED, error="events not sent")
            )

        await worker.handle_event(self.event_for(job_id, task_id))

        enrichment.enrich.assert_not_awaited()
        limiter.acquire.assert_not_awaited()
        assert (await self.get_task(task_id)).status == TaskStatus.PENDING
        assert await self.job_status(job_id) == JobStatus.FAILED

    async def test_an_unexpected_error_is_raised_so_the_message_is_kept(
        self, worker, enrichment, one_task
    ):
        job_id, task_id = one_task
        enrichment.enrich.side_effect = RuntimeError("bug")

        with raises(RuntimeError, match="bug"):
            await worker.handle_event(self.event_for(job_id, task_id))


class TestEnrichmentWorkerConsume:
    @staticmethod
    def message(n: int) -> ReceivedMessage:
        return ReceivedMessage(
            message_id=f"msg-{n}", receipt_handle=f"receipt-{n}", body="{}"
        )

    async def test_handles_up_to_concurrency_messages_at_once(self, mocker, sqs_client):
        concurrency = 3
        config = cfg.model_copy(
            update={
                "enrichment": cfg.enrichment.model_copy(
                    update={"concurrency": concurrency}
                )
            }
        )
        worker = EnrichmentWorker(config, sqs=sqs_client, limiter=TokenBucket(1000))
        handled: list[str] = []
        in_flight = 0
        peak = 0
        all_started = Event()

        async def process(received: ReceivedMessage) -> None:
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            if in_flight == concurrency:
                all_started.set()
            # Hold every handler until `concurrency` messages are in flight.
            await all_started.wait()
            in_flight -= 1
            handled.append(received.message_id)

        async def receive(*args, **kwargs) -> list[ReceivedMessage]:
            if sqs_client.receive_messages.await_count == 1:
                return [self.message(n) for n in range(1, 6)]
            # Second poll: once all five are handled, stop as SIGINT would.
            while len(handled) < 5:
                await sleep(0)
            raise CancelledError()

        mocker.patch.object(worker, "process_message", side_effect=process)
        sqs_client.receive_messages.side_effect = receive

        with raises(CancelledError):
            await worker.consume()

        assert peak == concurrency
        assert sorted(handled) == [f"msg-{n}" for n in range(1, 6)]


class TestEnrichmentWorkerClients:
    def test_accessing_sqs_before_run_raises(self):
        with raises(RuntimeError, match="call run\\(\\) first"):
            EnrichmentWorker(cfg).sqs

    def test_accessing_enrichment_before_run_raises(self):
        with raises(RuntimeError, match="call run\\(\\) first"):
            EnrichmentWorker(cfg).enrichment

    def test_the_rate_limiter_uses_the_configured_rate(self):
        assert EnrichmentWorker(cfg).limiter.rate == cfg.enrichment.rate_per_second


class TestEnrichmentWorkerStartup:
    async def test_verifies_the_queue_before_consuming(self, sqs_client):
        # Stop the consume loop on its first poll, as SIGINT would.
        sqs_client.receive_messages.side_effect = CancelledError()

        await EnrichmentWorker(cfg).run()

        sqs_client.verify_queue.assert_awaited_once_with(cfg.sqs.enrichment_queue_url)
        sqs_client.receive_messages.assert_awaited_once()
        with raises(RuntimeError, match="not connected"):
            SQSClient.get()
        assert DBSession.engine is None

    async def test_stops_and_cleans_up_when_queue_is_unreachable(self, sqs_client):
        sqs_client.verify_queue.side_effect = SQSQueueUnavailableError("unreachable")

        with raises(SQSQueueUnavailableError):
            await EnrichmentWorker(cfg).run()

        sqs_client.receive_messages.assert_not_awaited()
        with raises(RuntimeError, match="not connected"):
            SQSClient.get()
        assert DBSession.engine is None
