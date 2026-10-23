from contextlib import AsyncExitStack
from logging import getLogger
from typing import Any

from aiobotocore.client import AioBaseClient
from aiobotocore.session import get_session
from pydantic import BaseModel

from config import Config

logger = getLogger(__name__)


class SQSQueue:
    """One existing SQS queue, accessed through an aiobotocore client.

    The queue itself is provisioned outside this code (LocalStack script locally,
    Terraform in AWS); this class only connects to it by URL.
    The API uses it to send messages, the worker to receive and delete them.
    Create it with `await SQSQueue.create(cfg)` and release it with `close()`.
    """

    def __init__(
        self,
        client: AioBaseClient,
        queue_url: str,
        exit_stack: AsyncExitStack,
        cfg: Config,
    ) -> None:
        self._client = client
        self._exit_stack = exit_stack
        self._cfg = cfg
        self.queue_url = queue_url

    @classmethod
    async def create(cls, cfg: Config) -> "SQSQueue":
        """Open a client for the queue at SQS_ENRICHMENT_QUEUE_URL.

        Endpoint and credentials left unset (None) fall back to botocore's
        defaults: the real AWS endpoint and the IAM role / credential chain.
        """
        exit_stack = AsyncExitStack()
        client = await exit_stack.enter_async_context(
            get_session().create_client(
                "sqs",
                endpoint_url=cfg.aws.endpoint_url,
                region_name=cfg.aws.region,
                aws_access_key_id=cfg.aws.access_key_id,
                aws_secret_access_key=cfg.aws.secret_access_key,
            )
        )
        queue_url = cfg.sqs.enrichment_queue_url
        logger.info("Using SQS queue %s", queue_url)
        return cls(client, queue_url, exit_stack, cfg)

    async def send_message(self, message: BaseModel) -> str:
        response = await self._client.send_message(
            QueueUrl=self.queue_url, MessageBody=message.model_dump_json()
        )
        return response["MessageId"]

    async def receive_messages(self) -> list[dict[str, Any]]:
        """Long-polls the queue; returns raw SQS messages (possibly none)."""
        response = await self._client.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=self._cfg.sqs.max_messages,
            WaitTimeSeconds=self._cfg.sqs.wait_time_seconds,
        )
        return response.get("Messages", [])

    async def delete_message(self, receipt_handle: str) -> None:
        await self._client.delete_message(
            QueueUrl=self.queue_url, ReceiptHandle=receipt_handle
        )

    async def close(self) -> None:
        await self._exit_stack.aclose()
