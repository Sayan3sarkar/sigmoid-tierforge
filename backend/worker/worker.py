"""Enrichment worker: long-polls the SQS queue, parses each message and handles it.

The handler is a stub for now; the enrichment logic comes later.
Run with `poe worker`.
"""

from asyncio import CancelledError, Task, create_task, get_running_loop
from asyncio import run as asyncio_run
from logging import getLogger
from signal import SIGINT, SIGTERM
from typing import Any

from pydantic import ValidationError

from api.aws.sqs import SQSQueue
from api.dependencies.db_session import DBSession
from api.schemas.messages import EnrichmentMessage
from config import Config, cfg, configure_logging


class EnrichmentWorker:
    logger = getLogger("worker")

    def __init__(self, config: Config, queue: SQSQueue | None = None) -> None:
        self.config = config
        self._queue = queue
        self._consumer: Task | None = None

    @property
    def queue(self) -> SQSQueue:
        if self._queue is None:
            raise RuntimeError("Worker has no SQS queue yet; call run() first")
        return self._queue

    @classmethod
    def main(cls) -> None:
        """Entry point: configure logging and run the worker until SIGINT/SIGTERM."""
        configure_logging(cfg.log_level)
        asyncio_run(cls(cfg).run())

    async def run(self) -> None:
        DBSession.create()
        self._queue = await SQSQueue.create(self.config)
        self._consumer = create_task(self.consume())

        loop = get_running_loop()
        for sig in (SIGINT, SIGTERM):
            loop.add_signal_handler(sig, self.stop)

        try:
            await self._consumer
        except CancelledError:
            self.logger.info("Worker stopping")
        finally:
            await self.queue.close()
            await DBSession.close()

    def stop(self) -> None:
        if self._consumer is not None:
            self._consumer.cancel()

    async def consume(self) -> None:
        self.logger.info("Worker consuming from %s", self.queue.queue_url)
        while True:
            for raw in await self.queue.receive_messages():
                await self.process_message(raw)

    async def process_message(self, raw: dict[str, Any]) -> None:
        """Parse, handle and delete one message.

        A malformed message is deleted, since retrying it can never succeed.
        If the handler raises, the message is kept, so SQS redelivers it after
        the visibility timeout (and moves it to the dead-letter queue eventually).
        """
        try:
            message = EnrichmentMessage.model_validate_json(raw["Body"])
        except ValidationError:
            self.logger.error(
                "Dropping malformed message %s: %s", raw["MessageId"], raw["Body"]
            )
            await self.queue.delete_message(raw["ReceiptHandle"])
            return

        try:
            await self.handle_message(message)
        except Exception:
            self.logger.exception("Failed to handle message %s", raw["MessageId"])
            return

        await self.queue.delete_message(raw["ReceiptHandle"])

    async def handle_message(self, message: EnrichmentMessage) -> None:
        """Enrich one store. Not implemented yet: only logs the message."""
        self.logger.info(
            "Received job_id=%s store_id=%s", message.job_id, message.store_id
        )


if __name__ == "__main__":
    EnrichmentWorker.main()
