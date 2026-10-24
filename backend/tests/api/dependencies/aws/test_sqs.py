from botocore.exceptions import ClientError
from pytest import fixture, raises

from api.dependencies.aws.sqs import (
    ReceivedMessage,
    SQSClient,
)
from api.exceptions import SQSQueueUnavailableError, SQSSendError
from api.schemas.messages import EnrichmentEvent, EnrichStorePayload
from config import cfg

QUEUE_URL = cfg.sqs.enrichment_queue_url


class TestSQSClientConnect:
    async def test_client_is_shared_only_inside_the_block(self):
        async with SQSClient.connect(cfg) as sqs:
            assert SQSClient.get() is sqs

        with raises(RuntimeError, match="not connected"):
            SQSClient.get()

    async def test_client_is_released_when_the_block_raises(self):
        with raises(ValueError, match="boom"):
            async with SQSClient.connect(cfg):
                raise ValueError("boom")

        with raises(RuntimeError, match="not connected"):
            SQSClient.get()

    def test_get_outside_connect_raises(self):
        with raises(RuntimeError, match="SQSClient.connect"):
            SQSClient.get()


class TestSQSClientVerifyQueue:
    @fixture
    def boto_client(self, mocker):
        return mocker.AsyncMock()

    @fixture
    def sqs(self, boto_client):
        return SQSClient(boto_client)

    async def test_returns_the_queues_visibility_timeout(self, sqs, boto_client):
        boto_client.get_queue_attributes.return_value = {
            "Attributes": {"QueueArn": "arn:aws:sqs:…", "VisibilityTimeout": "45"}
        }

        assert await sqs.verify_queue(QUEUE_URL) == 45
        boto_client.get_queue_attributes.assert_awaited_once_with(
            QueueUrl=QUEUE_URL, AttributeNames=["QueueArn", "VisibilityTimeout"]
        )

    async def test_raises_clear_error_when_queue_is_missing(self, sqs, boto_client):
        boto_client.get_queue_attributes.side_effect = ClientError(
            {"Error": {"Code": "AWS.SimpleQueueService.NonExistentQueue"}},
            "GetQueueAttributes",
        )

        with raises(SQSQueueUnavailableError, match=f"SQS queue {QUEUE_URL}"):
            await sqs.verify_queue(QUEUE_URL)


class TestSQSClientSendMessage:
    @fixture
    def boto_client(self, mocker):
        client = mocker.AsyncMock()
        client.send_message.return_value = {"MessageId": "msg-1"}
        return client

    @fixture
    def sqs(self, boto_client):
        return SQSClient(boto_client)

    @staticmethod
    def event() -> EnrichmentEvent:
        return EnrichmentEvent(payload=EnrichStorePayload(job_id=7, task_id=42))

    async def test_sends_the_model_as_json(self, sqs, boto_client):
        event = self.event()

        assert await sqs.send_message(QUEUE_URL, event) == "msg-1"
        boto_client.send_message.assert_awaited_once_with(
            QueueUrl=QUEUE_URL, MessageBody=event.model_dump_json(), DelaySeconds=0
        )

    async def test_can_hold_the_message_back(self, sqs, boto_client):
        await sqs.send_message(QUEUE_URL, self.event(), delay_seconds=8)

        assert boto_client.send_message.await_args.kwargs["DelaySeconds"] == 8


class TestSQSClientReceiveMessages:
    @fixture
    def boto_client(self, mocker):
        return mocker.AsyncMock()

    @fixture
    def sqs(self, boto_client):
        return SQSClient(boto_client)

    async def test_returns_typed_messages(self, sqs, boto_client):
        boto_client.receive_message.return_value = {
            "Messages": [
                {"MessageId": "m-1", "ReceiptHandle": "r-1", "Body": '{"a": 1}'},
            ]
        }

        messages = await sqs.receive_messages(
            QUEUE_URL, max_messages=5, wait_time_seconds=1
        )

        assert messages == [
            ReceivedMessage(message_id="m-1", receipt_handle="r-1", body='{"a": 1}')
        ]
        boto_client.receive_message.assert_awaited_once_with(
            QueueUrl=QUEUE_URL, MaxNumberOfMessages=5, WaitTimeSeconds=1
        )

    async def test_returns_empty_list_when_queue_is_empty(self, sqs, boto_client):
        boto_client.receive_message.return_value = {}

        assert await sqs.receive_messages(QUEUE_URL) == []


class TestSQSClientSendMessages:
    @fixture
    def boto_client(self, mocker):
        client = mocker.AsyncMock()
        client.send_message_batch.return_value = {"Successful": [], "Failed": []}
        return client

    @fixture
    def sqs(self, boto_client):
        return SQSClient(boto_client)

    @staticmethod
    def make_events(count: int) -> list[EnrichmentEvent]:
        return [
            EnrichmentEvent(payload=EnrichStorePayload(job_id=1, task_id=n))
            for n in range(count)
        ]

    async def test_sends_in_batches_of_ten(self, sqs, boto_client):
        events = self.make_events(25)

        await sqs.send_messages(QUEUE_URL, events)

        batches = [
            call.kwargs["Entries"]
            for call in boto_client.send_message_batch.await_args_list
        ]
        assert sorted(len(batch) for batch in batches) == [5, 10, 10]
        assert all(
            call.kwargs["QueueUrl"] == QUEUE_URL
            for call in boto_client.send_message_batch.await_args_list
        )
        sent_bodies = sorted(
            entry["MessageBody"] for batch in batches for entry in batch
        )
        assert sent_bodies == sorted(event.model_dump_json() for event in events)
        assert [entry["Id"] for entry in batches[0]] == [str(n) for n in range(10)]

    async def test_sends_nothing_for_no_messages(self, sqs, boto_client):
        await sqs.send_messages(QUEUE_URL, [])

        boto_client.send_message_batch.assert_not_awaited()

    async def test_raises_when_sqs_rejects_messages(self, sqs, boto_client):
        boto_client.send_message_batch.return_value = {
            "Successful": [],
            "Failed": [{"Id": "0", "Message": "throttled", "SenderFault": False}],
        }

        with raises(SQSSendError, match="rejected 1 of 3 messages: throttled"):
            await sqs.send_messages(QUEUE_URL, self.make_events(3))
