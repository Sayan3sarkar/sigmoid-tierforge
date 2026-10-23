"""Enrichment worker: long-polls the SQS queue and enriches one store per event.

For each event it claims the store's task, waits for the rate limiter, calls the
enrichment API once, and saves the metrics (SUCCEEDED) or the reason (FAILED).
When a job's last task finishes, the job is marked COMPLETED or
COMPLETED_WITH_FAILURES. Run with `poe worker`.
"""

from asyncio import (
    CancelledError,
    Queue,
    Task,
    TaskGroup,
    create_task,
    get_running_loop,
)
from asyncio import run as asyncio_run
from logging import getLogger
from signal import SIGINT, SIGTERM

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.aws.sqs import ReceivedMessage, SQSClient
from api.dependencies.db_session import DBSession
from api.dependencies.enrichment import EnrichmentClient
from api.exceptions import EnrichmentCallError
from api.repositories.enrichment_task import EnrichmentTaskRepository
from api.repositories.job import JobRepository
from api.repositories.store import StoreRepository
from api.repositories.store_score import StoreScoreRepository
from api.schemas.enrichment import EnrichResponse
from api.schemas.messages import EVENT_VERSION, EnrichmentEvent
from api.services.jobs import EnrichmentJobService, EnrichmentTaskService
from config import Config, cfg, configure_logging
from worker.rate_limiter import TokenBucket


class EnrichmentWorker:
    """Receives enrichment events from SQS and handles up to
    `enrichment.concurrency` of them at once.

    One receiver loop long-polls SQS and feeds a small in-memory buffer; a fixed
    number of handler tasks take messages from it. All handlers share one rate
    limiter, so the process never exceeds `enrichment.rate_per_second` calls to
    the enrichment API, however many handlers are waiting. SIGINT and SIGTERM
    cancel everything, and the clients and database pool are closed on the way
    out.
    """

    logger = getLogger("worker")

    def __init__(
        self,
        config: Config,
        sqs: SQSClient | None = None,
        enrichment: EnrichmentClient | None = None,
        rate_limiter: TokenBucket | None = None,
    ) -> None:
        """Store the settings and create the rate limiter. Nothing connects
        until run().

        `sqs`, `enrichment` and `rate_limiter` let tests hand in their own; run()
        always replaces the two clients with freshly connected ones.
        """
        self._config = config
        self._queue_url = config.sqs.enrichment_queue_url
        self._sqs_client = sqs
        self._enrichment_client = enrichment
        # Shared by every handler: caps calls/s for the whole process.
        self._rate_limiter = rate_limiter or TokenBucket(
            config.enrichment.rate_per_second
        )
        # The running consume loop, kept so stop() can cancel it.
        self._consumer: Task | None = None

    @property
    def sqs(self) -> SQSClient:
        """The connected SQS client. Raises if run() hasn't connected one yet."""
        if self._sqs_client is None:
            raise RuntimeError("Worker has no SQS client yet; call run() first")
        return self._sqs_client

    @property
    def enrichment_client(self) -> EnrichmentClient:
        """The enrichment API client. Raises if run() hasn't connected one yet."""
        if self._enrichment_client is None:
            raise RuntimeError("Worker has no enrichment client yet; call run() first")
        return self._enrichment_client

    @classmethod
    def main(cls) -> None:
        """Entry point: configure logging and run the worker until SIGINT/SIGTERM."""
        configure_logging(cfg.log_level)
        asyncio_run(cls(cfg).run())

    async def run(self) -> None:
        """Connect to Postgres, SQS and the enrichment API, check the queue, then
        consume until stopped.

        Returns normally when stop() cancels the loop. Raises if the queue can't
        be reached at startup. Either way, both clients and the database pool are
        closed before returning.
        """
        try:
            # 1. Open the shared database engine (connections are made lazily).
            DBSession.create()
            # 2. Open the SQS and enrichment clients; both stay open for the whole
            #    block and are closed on the way out, however the block ends.
            async with (
                SQSClient.connect(self._config) as sqs,
                EnrichmentClient.connect(self._config) as enrichment,
            ):
                self._sqs_client = sqs
                self._enrichment_client = enrichment
                # 3. Fail fast on a wrong queue URL instead of polling it forever.
                await sqs.verify_queue(self._queue_url)
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
        """Signal handler: cancel the consume loop and its handlers, which makes
        run() return.

        Messages being handled at that moment are not deleted, so SQS delivers
        them again after their visibility timeout. A task that was already
        claimed then stays IN_PROGRESS: reclaiming it is phase 6 work.
        """
        if self._consumer is not None:
            self._consumer.cancel()

    async def consume(self) -> None:
        """Receive messages and hand them to `enrichment.concurrency` handlers.

        The buffer between them is as small as the number of handlers, so the
        receiver only fetches more once handlers are free. That bounds how long
        a received message waits before it's handled, keeping it well within
        the queue's visibility timeout. Only ends when cancelled by stop(), or
        if receiving or deleting raises.
        """
        concurrency = self._config.enrichment.concurrency
        buffer: Queue[ReceivedMessage] = Queue(maxsize=concurrency)
        self.logger.info(
            "Worker consuming from %s (%d handlers, %g calls/s)",
            self._queue_url,
            concurrency,
            self._rate_limiter.rate,
        )
        # The task group cancels every handler when this loop ends, and ends this
        # loop if a handler crashes.
        async with TaskGroup() as handlers:
            for _ in range(concurrency):
                handlers.create_task(self.handle_messages(buffer))

            while True:
                # Long poll: waits up to `wait_time_seconds` for messages to
                # arrive, and returns up to `max_messages` (at most 10) at once.
                messages = await self.sqs.receive_messages(
                    self._queue_url,
                    max_messages=self._config.sqs.max_messages,
                    wait_time_seconds=self._config.sqs.wait_time_seconds,
                )
                # Waits while the buffer is full, i.e. every handler is busy.
                for received in messages:
                    await buffer.put(received)

    async def handle_messages(self, buffer: Queue[ReceivedMessage]) -> None:
        """One handler: take messages from the buffer and process each in turn,
        forever. Several of these run at once."""
        while True:
            received = await buffer.get()
            await self.process_message(received)

    async def process_message(self, received: ReceivedMessage) -> None:
        """Parse, handle and delete one message.

        A malformed message, or one with an event version this worker doesn't
        understand, is deleted, since retrying it can never succeed.
        If the handler raises, the message is kept, so SQS redelivers it after
        the visibility timeout (and moves it to the dead-letter queue eventually).
        Only raises if deleting the message fails.
        """
        # 1. Parse the body into a typed event; drop it if it doesn't parse.
        try:
            event = EnrichmentEvent.model_validate_json(received.body)
        except ValidationError:
            self.logger.error(
                "Dropping malformed message %s: %s", received.message_id, received.body
            )
            await self.sqs.delete_message(self._queue_url, received.receipt_handle)
            return

        # 2. Drop events in a format version this worker can't read.
        if event.version != EVENT_VERSION:
            self.logger.error(
                "Dropping message %s with unsupported event version %s (expected %s)",
                received.message_id,
                event.version,
                EVENT_VERSION,
            )
            await self.sqs.delete_message(self._queue_url, received.receipt_handle)
            return

        # 3. Handle the event. On failure, keep the message for redelivery.
        try:
            await self.handle_event(event)
        except Exception:
            self.logger.exception("Failed to handle message %s", received.message_id)
            return

        # 4. Handled: delete it so SQS doesn't deliver it again.
        await self.sqs.delete_message(self._queue_url, received.receipt_handle)

    async def handle_event(self, event: EnrichmentEvent) -> None:
        """Enrich the event's store: claim, call the API once, record the outcome,
        and finish the job if this was its last task.

        A task that's already claimed (duplicate delivery) or whose job FAILED
        is skipped without calling the API. A failed call is recorded as a
        FAILED task, not raised. Raises on database errors, so
        process_message() keeps the message.
        """
        payload = event.payload

        # 1. Claim the task (PENDING -> IN_PROGRESS) and load its store. The
        #    session is closed again before the slow API call, so a waiting
        #    handler doesn't hold a database connection.
        async with DBSession.context() as session:
            task = await self._task_service(session).claim(
                payload.task_id, payload.job_id
            )
        if task is None:
            self.logger.info(
                "Task %s of job %s skipped: already handled or job failed",
                payload.task_id,
                payload.job_id,
            )
            return

        # 2. Wait for a rate-limiter token, shared with every other handler.
        await self._rate_limiter.acquire()

        # 3. Call the enrichment API once. Any failure (429, 500, timeout,
        #    connection, bad body) comes back as an EnrichmentCallError.
        result: EnrichResponse | None = None
        reason = ""
        try:
            result = await self.enrichment_client.enrich(task.request)
        except EnrichmentCallError as e:
            reason = str(e)

        async with DBSession.context() as session:
            # 4. Record the outcome: SUCCEEDED with metrics, or FAILED with why.
            tasks = self._task_service(session)
            if result is not None:
                await tasks.record_success(task, result)
            else:
                await tasks.record_failure(task, reason)

            # 5. If that was the job's last unfinished task, finish the job.
            job_status = await self._job_service(session).finish_if_complete(
                task.job_id
            )

        if result is not None:
            self.logger.info(
                "Task %s of job %s succeeded (store %s)",
                task.task_id,
                task.job_id,
                task.request.store_id,
            )
        else:
            self.logger.warning(
                "Task %s of job %s failed (store %s): %s",
                task.task_id,
                task.job_id,
                task.request.store_id,
                reason,
            )
        if job_status is not None:
            self.logger.info("Job %s finished: %s", task.job_id, job_status)

    @staticmethod
    def _task_service(session: AsyncSession) -> EnrichmentTaskService:
        """The task service on `session`. The worker isn't a FastAPI app, so it
        builds services and repositories itself."""
        return EnrichmentTaskService(
            EnrichmentTaskRepository(session), StoreRepository(session), session
        )

    def _job_service(self, session: AsyncSession) -> EnrichmentJobService:
        """The job service on `session`, built like _task_service()."""
        return EnrichmentJobService(
            JobRepository(session),
            EnrichmentTaskRepository(session),
            StoreScoreRepository(session),
            self.sqs,
            session,
            self._config,
        )


if __name__ == "__main__":
    EnrichmentWorker.main()
