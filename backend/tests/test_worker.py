from pytest import fixture, raises

from api.schemas.messages import EnrichmentMessage
from config import cfg
from worker.worker import EnrichmentWorker


class TestEnrichmentWorkerProcessMessage:
    @staticmethod
    def make_raw_message(body: str) -> dict:
        return {"MessageId": "msg-1", "ReceiptHandle": "receipt-1", "Body": body}

    @fixture
    def worker(self, sqs_queue):
        return EnrichmentWorker(cfg, queue=sqs_queue)

    @fixture
    def handler(self, mocker, worker):
        return mocker.patch.object(
            worker, "handle_message", new_callable=mocker.AsyncMock
        )

    async def test_valid_message_is_handled_then_deleted(
        self, worker, handler, sqs_queue
    ):
        raw = self.make_raw_message('{"job_id": 7, "store_id": "ST000001"}')

        await worker.process_message(raw)

        handler.assert_awaited_once_with(
            EnrichmentMessage(job_id=7, store_id="ST000001")
        )
        sqs_queue.delete_message.assert_awaited_once_with("receipt-1")

    async def test_malformed_message_is_deleted_without_handling(
        self, worker, handler, sqs_queue
    ):
        raw = self.make_raw_message('{"unexpected": true}')

        await worker.process_message(raw)

        handler.assert_not_awaited()
        sqs_queue.delete_message.assert_awaited_once_with("receipt-1")

    async def test_message_is_kept_when_handler_fails(self, worker, handler, sqs_queue):
        handler.side_effect = RuntimeError("boom")
        raw = self.make_raw_message('{"job_id": 7, "store_id": "ST000001"}')

        await worker.process_message(raw)

        sqs_queue.delete_message.assert_not_awaited()


class TestEnrichmentWorkerQueue:
    def test_accessing_queue_before_run_raises(self):
        with raises(RuntimeError, match="call run\\(\\) first"):
            EnrichmentWorker(cfg).queue
