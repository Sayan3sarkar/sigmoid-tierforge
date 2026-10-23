from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging import getLogger
from typing import Annotated, TypeAlias

from aiobotocore.session import get_session
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Depends
from pydantic import BaseModel, ConfigDict
from types_aiobotocore_sqs.client import SQSClient as AioSQSClient
from types_aiobotocore_sqs.type_defs import MessageTypeDef

from api.exceptions import SQSQueueUnavailableError
from config import Config

logger = getLogger(__name__)


class ReceivedMessage(BaseModel):
    """A message read from a queue: what the consumer needs to handle and delete it."""

    model_config = ConfigDict(frozen=True)

    message_id: str
    receipt_handle: str
    body: str


class SQSClient:
    """Async SQS client (aiobotocore) that works with any existing queue.

    One shared client per process. Open it for the lifetime of the process with
    `async with SQSClient.connect(cfg) as sqs:`; inside that block, `get()` returns
    it anywhere (also the FastAPI dependency `SQSClientDep`). Leaving the block
    closes the client, even on errors. Every call names its queue by URL. Queues
    are provisioned outside this code (LocalStack script locally, Terraform in AWS).

    Today only the worker uses it. When an API route needs it (POST /api/jobs),
    wrap the API lifespan's `yield` in `async with SQSClient.connect(cfg):`.

    IAM (Terraform policy, per role):
    - worker: sqs:GetQueueAttributes (verify_queue at startup), sqs:ReceiveMessage
      and sqs:DeleteMessage on the enrichment queue;
    - API (from phase 2): sqs:SendMessage on the enrichment queue.
    """

    _instance: "SQSClient | None" = None

    def __init__(self, client: "AioSQSClient") -> None:
        self._client = client

    @classmethod
    @asynccontextmanager
    async def connect(cls, cfg: Config) -> AsyncIterator["SQSClient"]:
        """Open the shared client for the duration of the `async with` block.

        Endpoint and credentials left unset (None) fall back to botocore's
        defaults: the real AWS endpoint and the IAM role.
        """
        async with get_session().create_client(
            "sqs",
            endpoint_url=cfg.aws.endpoint_url,
            region_name=cfg.aws.region,
            aws_access_key_id=cfg.aws.access_key_id,
            aws_secret_access_key=cfg.aws.secret_access_key,
        ) as client:
            cls._instance = cls(client)
            logger.info(
                "SQS client ready (endpoint: %s)", cfg.aws.endpoint_url or "AWS"
            )
            try:
                yield cls._instance
            finally:
                cls._instance = None

    @classmethod
    def get(cls) -> "SQSClient":
        if cls._instance is None:
            raise RuntimeError(
                "SQSClient is not connected; use `async with SQSClient.connect(cfg)`"
            )
        return cls._instance

    async def verify_queue(self, queue_url: str) -> None:
        """Check the queue exists and is reachable (read-only; creates nothing).

        Used by the worker at startup. IAM: the worker's Terraform IAM policy needs
        sqs:GetQueueAttributes, in addition to receive and delete.
        """
        try:
            await self._client.get_queue_attributes(
                QueueUrl=queue_url, AttributeNames=["QueueArn"]
            )
        except (ClientError, BotoCoreError) as e:
            raise SQSQueueUnavailableError(
                f"SQS queue {queue_url} is not reachable: {e}"
            ) from e
        logger.info("SQS queue reachable: %s", queue_url)

    async def send_message(self, queue_url: str, message: BaseModel) -> str:
        """Send one message (the model as JSON); returns the SQS message ID."""
        response = await self._client.send_message(
            QueueUrl=queue_url, MessageBody=message.model_dump_json()
        )
        return response.get("MessageId", "")

    async def receive_messages(
        self, queue_url: str, max_messages: int = 10, wait_time_seconds: int = 20
    ) -> list[ReceivedMessage]:
        """Long-poll the queue; returns the messages received (possibly none)."""
        response = await self._client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_time_seconds,
        )
        return [self._to_received(message) for message in response.get("Messages", [])]

    async def delete_message(self, queue_url: str, receipt_handle: str) -> None:
        await self._client.delete_message(
            QueueUrl=queue_url, ReceiptHandle=receipt_handle
        )

    @staticmethod
    def _to_received(message: "MessageTypeDef") -> ReceivedMessage:
        # The stubs mark these keys optional; SQS always sets them on received messages.
        return ReceivedMessage(
            message_id=message.get("MessageId", ""),
            receipt_handle=message.get("ReceiptHandle", ""),
            body=message.get("Body", ""),
        )


# FastAPI dependency: the shared client created once at startup.
SQSClientDep: TypeAlias = Annotated[SQSClient, Depends(SQSClient.get)]
