"""Enrichment worker: long-polls the SQS queue, parses each message and handles it.

The handler is a stub for now; the enrichment logic comes later.
Run with `poe worker`.
"""

from asyncio import CancelledError, Task, create_task, get_running_loop
from asyncio import run as asyncio_run
from logging import getLogger
from signal import SIGINT, SIGTERM

from pydantic import ValidationError

from api.dependencies.aws.sqs import ReceivedMessage, SQSClient
from api.dependencies.db_session import DBSession
from api.schemas.messages import EnrichmentMessage
from config import Config, cfg, configure_logging


class EnrichmentWorker:
    logger = getLogger("worker")

    def __init__(self, config: Config, sqs: SQSClient | None = None) -> None:
        self.config = config
        self.queue_url = config.sqs.enrichment_queue_url
        self._sqs = sqs
        self._consumer: Task | None = None

    @property
    def sqs(self) -> SQSClient:
        if self._sqs is None:
            raise RuntimeError("Worker has no SQS client yet; call run() first")
        return self._sqs

    @classmethod
    def main(cls) -> None:
        """Entry point: configure logging and run the worker until SIGINT/SIGTERM."""
        configure_logging(cfg.log_level)
        asyncio_run(cls(cfg).run())

    async def run(self) -> None:
        try:
            DBSession.create()
            # The SQS client is open for the whole block and closed on the way out.
            async with SQSClient.connect(self.config) as sqs:
                self._sqs = sqs
                # Fail fast on a wrong queue URL instead of polling it forever.
                await sqs.verify_queue(self.queue_url)
                self._consumer = create_task(self.consume())

                loop = get_running_loop()
                for sig in (SIGINT, SIGTERM):
                    loop.add_signal_handler(sig, self.stop)

                await self._consumer
        except CancelledError:
            self.logger.info("Worker stopping")
        finally:
            await DBSession.close()

    def stop(self) -> None:
        if self._consumer is not None:
            self._consumer.cancel()

    async def consume(self) -> None:
        self.logger.info("Worker consuming from %s", self.queue_url)
        while True:
            messages = await self.sqs.receive_messages(
                self.queue_url,
                max_messages=self.config.sqs.max_messages,
                wait_time_seconds=self.config.sqs.wait_time_seconds,
            )
            for received in messages:
                await self.process_message(received)

    async def process_message(self, received: ReceivedMessage) -> None:
        """Parse, handle and delete one message.

        A malformed message is deleted, since retrying it can never succeed.
        If the handler raises, the message is kept, so SQS redelivers it after
        the visibility timeout (and moves it to the dead-letter queue eventually).
        """
        try:
            message = EnrichmentMessage.model_validate_json(received.body)
        except ValidationError:
            self.logger.error(
                "Dropping malformed message %s: %s", received.message_id, received.body
            )
            await self.sqs.delete_message(self.queue_url, received.receipt_handle)
            return

        try:
            await self.handle_message(message)
        except Exception:
            self.logger.exception("Failed to handle message %s", received.message_id)
            return

        await self.sqs.delete_message(self.queue_url, received.receipt_handle)

    async def handle_message(self, message: EnrichmentMessage) -> None:
        """Enrich one store. Not implemented yet: only logs the message."""
        self.logger.info(
            "Received job_id=%s store_id=%s", message.job_id, message.store_id
        )


if __name__ == "__main__":
    EnrichmentWorker.main()
