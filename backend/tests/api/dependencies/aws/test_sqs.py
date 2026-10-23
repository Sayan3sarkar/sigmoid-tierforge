from botocore.exceptions import ClientError
from pytest import fixture, raises

from api.dependencies.aws.sqs import (
    ReceivedMessage,
    SQSClient,
)
from api.exceptions import SQSQueueUnavailableError
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

    async def test_reads_the_queue_attributes(self, sqs, boto_client):
        await sqs.verify_queue(QUEUE_URL)

        boto_client.get_queue_attributes.assert_awaited_once_with(
            QueueUrl=QUEUE_URL, AttributeNames=["QueueArn"]
        )

    async def test_raises_clear_error_when_queue_is_missing(self, sqs, boto_client):
        boto_client.get_queue_attributes.side_effect = ClientError(
            {"Error": {"Code": "AWS.SimpleQueueService.NonExistentQueue"}},
            "GetQueueAttributes",
        )

        with raises(SQSQueueUnavailableError, match=f"SQS queue {QUEUE_URL}"):
            await sqs.verify_queue(QUEUE_URL)


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
