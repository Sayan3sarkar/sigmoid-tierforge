"""Enrichment worker: long-polls the SQS queue and handles each enrichment event.

Phase 2: it claims each event's task (PENDING -> IN_PROGRESS) but doesn't call the
enrichment API yet; that comes in phase 3. Run with `poe worker`.
"""

from asyncio import CancelledError, Task, create_task, get_running_loop
from asyncio import run as asyncio_run
from logging import getLogger
from signal import SIGINT, SIGTERM

from pydantic import ValidationError

from api.dependencies.aws.sqs import ReceivedMessage, SQSClient
from api.dependencies.db_session import DBSession
from api.repositories.enrichment_task import EnrichmentTaskRepository
from api.schemas.messages import EVENT_VERSION, EnrichmentEvent
from api.services.jobs import EnrichmentTaskService
from config import Config, cfg, configure_logging


class EnrichmentWorker:
    """Receives enrichment events from SQS and handles them one at a time.

    One process runs one consume loop as a single asyncio task. Messages are
    handled sequentially, never one task or process per message. SIGINT and
    SIGTERM cancel the loop, and the SQS client and database pool are closed on
    the way out.
    """

    logger = getLogger("worker")

    def __init__(self, config: Config, sqs: SQSClient | None = None) -> None:
        """Store the settings. Nothing connects until run().

        `sqs` lets tests hand in a client directly; run() always replaces it
        with a freshly connected one.
        """
        self.config = config
        self.queue_url = config.sqs.enrichment_queue_url
        self._sqs = sqs
        # The running consume loop, kept so stop() can cancel it.
        self._consumer: Task | None = None

    @property
    def sqs(self) -> SQSClient:
        """The connected SQS client. Raises if run() hasn't connected one yet."""
        if self._sqs is None:
            raise RuntimeError("Worker has no SQS client yet; call run() first")
        return self._sqs

    @classmethod
    def main(cls) -> None:
        """Entry point: configure logging and run the worker until SIGINT/SIGTERM."""
        configure_logging(cfg.log_level)
        asyncio_run(cls(cfg).run())

    async def run(self) -> None:
        """Connect to Postgres and SQS, check the queue, then consume until stopped.

        Returns normally when stop() cancels the loop. Raises if the queue can't
        be reached at startup. Either way, the SQS client and database pool are
        closed before returning.
        """
        try:
            # 1. Open the shared database engine (connections are made lazily).
            DBSession.create()
            # 2. Connect to SQS; the client stays open for the whole block and is
            #    closed on the way out, however the block ends.
            async with SQSClient.connect(self.config) as sqs:
                self._sqs = sqs
                # 3. Fail fast on a wrong queue URL instead of polling it forever.
                await sqs.verify_queue(self.queue_url)
                # 4. Start the consume loop as a task, so stop() has something
                #    to cancel, even mid long-poll.
                self._consumer = create_task(self.consume())

                # 5. Ctrl+C (SIGINT) or a container stop (SIGTERM) calls stop().
                loop = get_running_loop()
                for sig in (SIGINT, SIGTERM):
                    loop.add_signal_handler(sig, self.stop)

                # 6. Wait here until the loop is cancelled or crashes.
                await self._consumer
        except CancelledError:
            # Cancellation is the normal way to stop, not an error.
            self.logger.info("Worker stopping")
        finally:
            # 7. Close the database pool, whatever happened above.
            await DBSession.close()

    def stop(self) -> None:
        """Signal handler: cancel the consume loop, which makes run() return.

        A message being handled at that moment is not deleted, so SQS delivers
        it again after its visibility timeout.
        """
        if self._consumer is not None:
            self._consumer.cancel()

    async def consume(self) -> None:
        """Loop forever: receive a batch of messages, then process each in turn.

        Only ends when cancelled by stop(), or if receiving from SQS raises.
        """
        self.logger.info("Worker consuming from %s", self.queue_url)
        while True:
            # Long poll: waits up to `wait_time_seconds` for messages to arrive,
            # and returns up to `max_messages` (at most 10) at once.
            messages = await self.sqs.receive_messages(
                self.queue_url,
                max_messages=self.config.sqs.max_messages,
                wait_time_seconds=self.config.sqs.wait_time_seconds,
            )
            # Sequentially: the next message starts once this one is done.
            for received in messages:
                await self.process_message(received)

    async def process_message(self, received: ReceivedMessage) -> None:
        """Parse, handle and delete one message.

        A malformed message, or one with an event version this worker doesn't
        understand, is deleted, since retrying it can never succeed.
        If the handler raises, the message is kept, so SQS redelivers it after
        the visibility timeout (and moves it to the dead-letter queue eventually).
        Never raises.
        """
        # 1. Parse the body into a typed event; drop it if it doesn't parse.
        try:
            event = EnrichmentEvent.model_validate_json(received.body)
        except ValidationError:
            self.logger.error(
                "Dropping malformed message %s: %s", received.message_id, received.body
            )
            await self.sqs.delete_message(self.queue_url, received.receipt_handle)
            return

        # 2. Drop events in a format version this worker can't read.
        if event.version != EVENT_VERSION:
            self.logger.error(
                "Dropping message %s with unsupported event version %s (expected %s)",
                received.message_id,
                event.version,
                EVENT_VERSION,
            )
            await self.sqs.delete_message(self.queue_url, received.receipt_handle)
            return

        # 3. Handle the event. On failure, keep the message for redelivery.
        try:
            await self.handle_event(event)
        except Exception:
            self.logger.exception("Failed to handle message %s", received.message_id)
            return

        # 4. Handled: delete it so SQS doesn't deliver it again.
        await self.sqs.delete_message(self.queue_url, received.receipt_handle)

    async def handle_event(self, event: EnrichmentEvent) -> None:
        """Claim the event's task: PENDING -> IN_PROGRESS.

        Phase 3 will call the enrichment API here and save the result. A task
        that's already claimed (duplicate delivery) or whose job FAILED is skipped.
        Raises on database errors, so process_message() keeps the message.
        """
        payload = event.payload
        # One database session per event, closed as soon as the event is handled.
        async with DBSession.context() as session:
            # The worker isn't a FastAPI app, so it builds the service and
            # repository itself, on this session.
            tasks = EnrichmentTaskService(EnrichmentTaskRepository(session), session)
            # The claim is checked and committed by the service.
            claimed = await tasks.claim(payload.task_id, payload.job_id)

        if claimed:
            self.logger.info(
                "Task %s of job %s picked up", payload.task_id, payload.job_id
            )
        else:
            self.logger.info(
                "Task %s of job %s skipped: already handled or job failed",
                payload.task_id,
                payload.job_id,
            )


if __name__ == "__main__":
    EnrichmentWorker.main()
