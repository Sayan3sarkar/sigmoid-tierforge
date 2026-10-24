from asyncio import CancelledError, Event, sleep
from datetime import timedelta
from decimal import Decimal
from logging import INFO
from uuid import uuid4

from pytest import fixture, mark, raises
from sqlalchemy import func, select, update

from api.dependencies.aws.sqs import (
    ReceivedMessage,
    SQSClient,
)
from api.dependencies.db_session import DBSession
from api.dependencies.enrichment import EnrichmentClient
from api.exceptions import (
    EnrichmentConnectionError,
    EnrichmentInvalidResponseError,
    EnrichmentRateLimitedError,
    EnrichmentTimeoutError,
    EnrichmentUpstreamError,
    LeaseTooLongError,
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
from worker.backoff import Backoff
from worker.rate_limiter import TokenBucket
from worker.worker import EnrichmentWorker, HandledEvent, MessageAction


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
            worker,
            "handle_event",
            new_callable=mocker.AsyncMock,
            return_value=HandledEvent(action=MessageAction.DELETE),
        )

    async def process(self, worker) -> None:
        await worker.process_message(
            self.make_received(self.make_event().model_dump_json())
        )

    async def test_valid_event_is_handled_then_deleted(
        self, worker, handler, sqs_client
    ):
        await self.process(worker)

        [event] = handler.await_args.args
        assert event.payload == EnrichStorePayload(job_id=7, task_id=42)
        sqs_client.send_message.assert_not_awaited()
        sqs_client.delete_message.assert_awaited_once_with(
            cfg.sqs.enrichment_queue_url, "receipt-1"
        )

    async def test_a_retry_sends_a_delayed_event_then_deletes(
        self, worker, handler, sqs_client
    ):
        handler.return_value = HandledEvent(
            action=MessageAction.RETRY, retry_delay_seconds=4
        )

        await self.process(worker)

        call = sqs_client.send_message.await_args
        assert call.args[0] == cfg.sqs.enrichment_queue_url
        assert call.args[1].payload == EnrichStorePayload(job_id=7, task_id=42)
        assert call.kwargs == {"delay_seconds": 4}
        sqs_client.delete_message.assert_awaited_once_with(
            cfg.sqs.enrichment_queue_url, "receipt-1"
        )

    async def test_the_message_is_kept_if_the_retry_event_cant_be_sent(
        self, worker, handler, sqs_client
    ):
        # SQS redelivers it after the visibility timeout; the task is claimed then.
        handler.return_value = HandledEvent(
            action=MessageAction.RETRY, retry_delay_seconds=4
        )
        sqs_client.send_message.side_effect = RuntimeError("SQS down")

        await self.process(worker)

        sqs_client.delete_message.assert_not_awaited()

    async def test_the_message_is_kept_while_another_handler_holds_the_task(
        self, worker, handler, sqs_client
    ):
        handler.return_value = HandledEvent(action=MessageAction.KEEP)

        await self.process(worker)

        sqs_client.send_message.assert_not_awaited()
        sqs_client.delete_message.assert_not_awaited()

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

        await self.process(worker)

        sqs_client.delete_message.assert_not_awaited()


class TestEnrichmentWorkerHandleEvent:
    """Runs against the test database; only the enrichment API is mocked.

    The backoff's jitter is fixed at its highest, so the first retry waits 2 s.
    """

    METRICS = EnrichResponse(
        store_id="ST000001",
        estimated_monthly_footfall=18234,
        estimated_monthly_revenue=Decimal("142033.50"),
        store_size_sqft=6210,
    )
    DELETE = HandledEvent(action=MessageAction.DELETE)

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

    @staticmethod
    def make_worker(sqs_client, enrichment, limiter, **settings) -> EnrichmentWorker:
        config = cfg.model_copy(
            update={"enrichment": cfg.enrichment.model_copy(update=settings)}
        )
        return EnrichmentWorker(
            config,
            sqs=sqs_client,
            enrichment=enrichment,
            rate_limiter=limiter,
            backoff=Backoff(config.enrichment, random=lambda: 1.0),
        )

    @fixture
    def worker(self, sqs_client, enrichment, limiter):
        return self.make_worker(sqs_client, enrichment, limiter)

    @staticmethod
    async def get_task(task_id: int) -> EnrichmentTask:
        async with DBSession.context() as session:
            return await session.scalar(
                select(EnrichmentTask).where(EnrichmentTask.id == task_id)
            )

    @staticmethod
    async def get_job(job_id: int) -> Job:
        async with DBSession.context() as session:
            return await session.scalar(select(Job).where(Job.id == job_id))

    async def job_status(self, job_id: int) -> str:
        return (await self.get_job(job_id)).status

    @staticmethod
    async def claim_elsewhere(task_id: int, job_id: int) -> None:
        """Another handler claims the task (it's then IN_PROGRESS, leased)."""
        async with DBSession.context() as session:
            await EnrichmentTaskRepository(session).claim(task_id, job_id, 25)
            await session.commit()

    @staticmethod
    async def expire_lease(task_id: int) -> None:
        """The handler holding the task stalled or died: its lease runs out."""
        async with DBSession.context() as session:
            await session.execute(
                update(EnrichmentTask)
                .where(EnrichmentTask.id == task_id)
                .values(lease_expires_at=func.now() - timedelta(seconds=1))
            )
            await session.commit()

    @staticmethod
    def event_for(job_id: int, task_id: int) -> EnrichmentEvent:
        return EnrichmentEvent(
            payload=EnrichStorePayload(job_id=job_id, task_id=task_id)
        )

    async def test_success_saves_the_metrics_and_completes_the_job(
        self, worker, enrichment, limiter, one_task
    ):
        job_id, task_id = one_task

        handled = await worker.handle_event(self.event_for(job_id, task_id))

        assert handled == self.DELETE
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
        assert task.lease_expires_at is None
        assert await self.job_status(job_id) == JobStatus.COMPLETED

    @mark.parametrize(
        "error",
        [
            EnrichmentUpstreamError("upstream error (500)"),
            EnrichmentTimeoutError("timed out after 10s"),
            EnrichmentConnectionError("connection failed: ConnectError"),
            EnrichmentInvalidResponseError("invalid response body: bad JSON"),
        ],
    )
    async def test_a_failed_call_is_retried_after_the_backoff(
        self, worker, enrichment, one_task, error
    ):
        job_id, task_id = one_task
        enrichment.enrich.side_effect = error

        handled = await worker.handle_event(self.event_for(job_id, task_id))

        assert handled == HandledEvent(
            action=MessageAction.RETRY, retry_delay_seconds=2
        )
        task = await self.get_task(task_id)
        assert task.status == TaskStatus.RETRYING
        assert task.last_error == str(error)
        assert task.attempt_count == 1
        assert task.finished_at is None
        assert task.lease_expires_at is None
        assert await self.job_status(job_id) == JobStatus.RUNNING

    async def test_a_429_is_retried_soon_without_using_an_attempt(
        self, worker, enrichment, one_task
    ):
        job_id, task_id = one_task
        enrichment.enrich.side_effect = EnrichmentRateLimitedError("rate limited (429)")

        handled = await worker.handle_event(self.event_for(job_id, task_id))

        assert handled == HandledEvent(
            action=MessageAction.RETRY, retry_delay_seconds=1
        )
        task = await self.get_task(task_id)
        assert (task.status, task.attempt_count) == (TaskStatus.RETRYING, 0)

    async def test_a_retry_that_succeeds_completes_the_job(
        self, worker, enrichment, one_task
    ):
        job_id, task_id = one_task
        enrichment.enrich.side_effect = [
            EnrichmentUpstreamError("upstream error (500)"),
            self.METRICS,
        ]

        await worker.handle_event(self.event_for(job_id, task_id))
        handled = await worker.handle_event(self.event_for(job_id, task_id))

        assert handled == self.DELETE
        task = await self.get_task(task_id)
        assert (task.status, task.attempt_count) == (TaskStatus.SUCCEEDED, 2)
        assert task.last_error is None
        assert await self.job_status(job_id) == JobStatus.COMPLETED

    async def test_the_backoff_grows_and_the_fifth_failure_is_final(
        self, worker, enrichment, one_task
    ):
        job_id, task_id = one_task
        enrichment.enrich.side_effect = EnrichmentUpstreamError("upstream error (500)")

        handled = [
            await worker.handle_event(self.event_for(job_id, task_id)) for _ in range(5)
        ]

        assert [h.retry_delay_seconds for h in handled[:4]] == [2, 4, 8, 16]
        assert handled[4] == self.DELETE
        task = await self.get_task(task_id)
        assert (task.status, task.attempt_count) == (TaskStatus.FAILED, 5)
        assert task.last_error == "upstream error (500)"
        assert task.finished_at is not None
        assert await self.job_status(job_id) == JobStatus.COMPLETED_WITH_FAILURES

    async def test_the_job_keeps_running_until_its_last_task_finishes(self, worker, db):
        job_id, task_ids = await self.running_job(2)

        await worker.handle_event(self.event_for(job_id, task_ids[0]))
        assert await self.job_status(job_id) == JobStatus.RUNNING

        await worker.handle_event(self.event_for(job_id, task_ids[1]))
        assert await self.job_status(job_id) == JobStatus.COMPLETED

    async def test_duplicate_delivery_of_a_finished_task_is_dropped(
        self, worker, enrichment, one_task, caplog
    ):
        job_id, task_id = one_task
        caplog.set_level(INFO, logger="worker")

        await worker.handle_event(self.event_for(job_id, task_id))
        handled = await worker.handle_event(self.event_for(job_id, task_id))

        assert handled == self.DELETE
        enrichment.enrich.assert_awaited_once()
        assert (await self.get_task(task_id)).status == TaskStatus.SUCCEEDED
        assert "skipped" in caplog.text

    async def test_a_task_held_by_another_handler_is_left_alone(
        self, worker, enrichment, limiter, one_task
    ):
        job_id, task_id = one_task
        await self.claim_elsewhere(task_id, job_id)

        handled = await worker.handle_event(self.event_for(job_id, task_id))

        assert handled == HandledEvent(action=MessageAction.KEEP)
        enrichment.enrich.assert_not_awaited()
        limiter.acquire.assert_not_awaited()
        assert (await self.get_task(task_id)).status == TaskStatus.IN_PROGRESS

    async def test_a_task_whose_handler_died_is_taken_over(
        self, worker, enrichment, one_task
    ):
        job_id, task_id = one_task
        await self.claim_elsewhere(task_id, job_id)
        await self.expire_lease(task_id)

        handled = await worker.handle_event(self.event_for(job_id, task_id))

        assert handled == self.DELETE
        enrichment.enrich.assert_awaited_once()
        task = await self.get_task(task_id)
        assert (task.status, task.attempt_count) == (TaskStatus.SUCCEEDED, 1)
        assert await self.job_status(job_id) == JobStatus.COMPLETED

    async def test_a_late_result_after_a_takeover_changes_nothing(
        self, worker, enrichment, one_task
    ):
        job_id, task_id = one_task

        async def stall_then_answer(request):
            # While this call hangs, its lease runs out and another handler
            # takes the task over.
            await self.expire_lease(task_id)
            await self.claim_elsewhere(task_id, job_id)
            return self.METRICS

        enrichment.enrich.side_effect = stall_then_answer

        handled = await worker.handle_event(self.event_for(job_id, task_id))

        assert handled == self.DELETE
        task = await self.get_task(task_id)
        # Still the new owner's: no result saved, no attempt counted.
        assert (task.status, task.attempt_count) == (TaskStatus.IN_PROGRESS, 0)
        assert task.lease_expires_at is not None
        assert task.estimated_monthly_footfall is None

    async def test_task_of_a_failed_job_is_skipped_without_calling_the_api(
        self, worker, enrichment, limiter, one_task
    ):
        job_id, task_id = one_task
        async with DBSession.context() as session:
            await JobRepository(session).update(
                job_id, JobUpdate(status=JobStatus.FAILED, error="events not sent")
            )

        handled = await worker.handle_event(self.event_for(job_id, task_id))

        assert handled == self.DELETE
        enrichment.enrich.assert_not_awaited()
        limiter.acquire.assert_not_awaited()
        assert (await self.get_task(task_id)).status == TaskStatus.PENDING
        assert await self.job_status(job_id) == JobStatus.FAILED

    async def test_the_circuit_breaker_fails_the_job_and_its_stores(
        self, sqs_client, enrichment, limiter, db
    ):
        worker = self.make_worker(
            sqs_client, enrichment, limiter, circuit_breaker_threshold=3
        )
        job_id, task_ids = await self.running_job(4)
        enrichment.enrich.side_effect = EnrichmentConnectionError(
            "connection failed: ClientConnectorError"
        )

        handled = [
            await worker.handle_event(self.event_for(job_id, task_id))
            for task_id in task_ids[:3]
        ]

        # The 3rd failure in a row trips it: no retry is sent for that one.
        assert [h.action for h in handled] == [
            MessageAction.RETRY,
            MessageAction.RETRY,
            MessageAction.DELETE,
        ]
        job = await self.get_job(job_id)
        assert job.status == JobStatus.FAILED
        assert job.error == (
            "circuit breaker: 3 consecutive failed calls"
            " (last: connection failed: ClientConnectorError)"
        )
        tasks = [await self.get_task(task_id) for task_id in task_ids]
        assert {task.status for task in tasks} == {TaskStatus.FAILED}
        assert tasks[3].last_error == "job stopped by circuit breaker"

        # The job's remaining events, retries included, are dropped unanswered.
        for task_id in (task_ids[0], task_ids[3]):
            assert await worker.handle_event(self.event_for(job_id, task_id)) == (
                self.DELETE
            )
        assert enrichment.enrich.await_count == 3

    async def test_a_success_ends_the_failure_streak(
        self, sqs_client, enrichment, limiter, db
    ):
        worker = self.make_worker(
            sqs_client, enrichment, limiter, circuit_breaker_threshold=3
        )
        job_id, task_ids = await self.running_job(4)
        error = EnrichmentUpstreamError("upstream error (500)")
        enrichment.enrich.side_effect = [error, error, self.METRICS, error]

        for task_id in task_ids:
            await worker.handle_event(self.event_for(job_id, task_id))

        job = await self.get_job(job_id)
        assert (job.status, job.consecutive_failures) == (JobStatus.RUNNING, 1)

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
        worker = EnrichmentWorker(
            config, sqs=sqs_client, rate_limiter=TokenBucket(1000)
        )
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
            EnrichmentWorker(cfg).enrichment_client

    def test_the_rate_limiter_uses_the_configured_rate(self):
        assert (
            EnrichmentWorker(cfg)._rate_limiter.rate == cfg.enrichment.rate_per_second
        )


class TestEnrichmentWorkerStartup:
    @fixture(autouse=True)
    def visibility_timeout(self, sqs_client):
        sqs_client.verify_queue.return_value = 30

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

    async def test_refuses_a_lease_the_queue_would_outlast(self, sqs_client):
        # A dead handler's message would come back while its lease still runs.
        sqs_client.verify_queue.return_value = 20

        with raises(LeaseTooLongError, match=r"\(25\) must be below .* \(20s\)"):
            await EnrichmentWorker(cfg).run()

        sqs_client.receive_messages.assert_not_awaited()
        assert DBSession.engine is None
