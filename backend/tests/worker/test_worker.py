from asyncio import CancelledError
from logging import INFO
from uuid import uuid4

from pytest import fixture, raises
from sqlalchemy import select

from api.dependencies.aws.sqs import (
    ReceivedMessage,
    SQSClient,
)
from api.dependencies.db_session import DBSession
from api.exceptions import SQSQueueUnavailableError
from api.models import EnrichmentTask, JobStatus, TaskStatus
from api.repositories.enrichment_task import EnrichmentTaskRepository
from api.repositories.job import JobRepository
from api.repositories.store import StoreRepository
from api.schemas.enrichment_tasks import EnrichmentTaskCreate
from api.schemas.jobs import JobCreate, JobUpdate
from api.schemas.messages import EVENT_VERSION, EnrichmentEvent, EnrichStorePayload
from api.schemas.stores import StoreRow
from config import cfg
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
    """Runs against the test database: the worker claims tasks for real."""

    @fixture
    async def job_and_task(self, test_database):
        DBSession.create()
        upload_id = uuid4()
        store = StoreRow(
            store_id="ST000001",
            store_name="Fresh Supermarket #1",
            address="71 Church Street",
            city="New Delhi",
            state="Delhi",
            country="India",
        )
        async with DBSession.context() as session:
            [store_id] = await StoreRepository(session).bulk_create(upload_id, [store])
            job = await JobRepository(session).create(
                JobCreate(upload_id=upload_id, total_tasks=1, status=JobStatus.PENDING)
            )
            [task_id] = await EnrichmentTaskRepository(session).bulk_create(
                [
                    EnrichmentTaskCreate(
                        job_id=job.id, store_id=store_id, status=TaskStatus.PENDING
                    )
                ]
            )
        yield job.id, task_id
        await DBSession.close()

    @staticmethod
    async def task_status(task_id: int) -> TaskStatus:
        async with DBSession.context() as session:
            return await session.scalar(
                select(EnrichmentTask.status).where(EnrichmentTask.id == task_id)
            )

    @staticmethod
    def event_for(job_id: int, task_id: int) -> EnrichmentEvent:
        return EnrichmentEvent(
            payload=EnrichStorePayload(job_id=job_id, task_id=task_id)
        )

    async def test_claims_a_pending_task(self, job_and_task):
        job_id, task_id = job_and_task

        await EnrichmentWorker(cfg).handle_event(self.event_for(job_id, task_id))

        assert await self.task_status(task_id) == TaskStatus.IN_PROGRESS

    async def test_duplicate_delivery_is_skipped(self, job_and_task, caplog):
        job_id, task_id = job_and_task
        caplog.set_level(INFO, logger="worker")
        worker = EnrichmentWorker(cfg)

        await worker.handle_event(self.event_for(job_id, task_id))
        await worker.handle_event(self.event_for(job_id, task_id))

        assert await self.task_status(task_id) == TaskStatus.IN_PROGRESS
        assert "skipped" in caplog.text

    async def test_task_of_a_failed_job_is_skipped(self, job_and_task):
        job_id, task_id = job_and_task
        async with DBSession.context() as session:
            await JobRepository(session).update(
                job_id, JobUpdate(status=JobStatus.FAILED, error="events not sent")
            )

        await EnrichmentWorker(cfg).handle_event(self.event_for(job_id, task_id))

        assert await self.task_status(task_id) == TaskStatus.PENDING


class TestEnrichmentWorkerSQSClient:
    def test_accessing_sqs_before_run_raises(self):
        with raises(RuntimeError, match="call run\\(\\) first"):
            EnrichmentWorker(cfg).sqs


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
