from asyncio import CancelledError

from pytest import fixture, raises

from api.dependencies.aws.sqs import (
    ReceivedMessage,
    SQSClient,
)
from api.dependencies.db_session import DBSession
from api.exceptions import SQSQueueUnavailableError
from api.schemas.messages import EnrichmentMessage
from config import cfg
from worker.worker import EnrichmentWorker


class TestEnrichmentWorkerProcessMessage:
    @staticmethod
    def make_received(body: str) -> ReceivedMessage:
        return ReceivedMessage(
            message_id="msg-1", receipt_handle="receipt-1", body=body
        )

    @fixture
    def worker(self, sqs_client):
        return EnrichmentWorker(cfg, sqs=sqs_client)

    @fixture
    def handler(self, mocker, worker):
        return mocker.patch.object(
            worker, "handle_message", new_callable=mocker.AsyncMock
        )

    async def test_valid_message_is_handled_then_deleted(
        self, worker, handler, sqs_client
    ):
        received = self.make_received('{"job_id": 7, "store_id": "ST000001"}')

        await worker.process_message(received)

        handler.assert_awaited_once_with(
            EnrichmentMessage(job_id=7, store_id="ST000001")
        )
        sqs_client.delete_message.assert_awaited_once_with(
            cfg.sqs.enrichment_queue_url, "receipt-1"
        )

    async def test_malformed_message_is_deleted_without_handling(
        self, worker, handler, sqs_client
    ):
        received = self.make_received('{"unexpected": true}')

        await worker.process_message(received)

        handler.assert_not_awaited()
        sqs_client.delete_message.assert_awaited_once_with(
            cfg.sqs.enrichment_queue_url, "receipt-1"
        )

    async def test_message_is_kept_when_handler_fails(
        self, worker, handler, sqs_client
    ):
        handler.side_effect = RuntimeError("boom")
        received = self.make_received('{"job_id": 7, "store_id": "ST000001"}')

        await worker.process_message(received)

        sqs_client.delete_message.assert_not_awaited()


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
