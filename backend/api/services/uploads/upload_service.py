from logging import getLogger
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, UploadFile

from api.dependencies.db_session import DbSessionDep
from api.exceptions import (
    EnrichmentDispatchError,
    InvalidUploadError,
    UploadTooLargeError,
)
from api.repositories.store import StoreRepositoryDep
from api.schemas.uploads import UploadResponse
from api.services.jobs import EnrichmentJobServiceDep
from api.services.uploads.csv_parser import StoreCsvParserDep
from config import ConfigDep

logger = getLogger(__name__)


class UploadService:
    """Accepts a store CSV and starts its enrichment.

    1. Checks the file and validates its contents (all-or-nothing).
    2. Saves the stores, an enrichment job and one task per store, and commits.
    3. Sends one enrichment event per task to SQS; the job becomes RUNNING.
    """

    def __init__(
        self,
        parser: StoreCsvParserDep,
        store_repository: StoreRepositoryDep,
        jobs: EnrichmentJobServiceDep,
        session: DbSessionDep,
        config: ConfigDep,
    ) -> None:
        self._parser = parser
        self._store_repository = store_repository
        self._jobs_service = jobs
        self._session = session
        self._max_size_bytes = config.upload.max_size_bytes

    async def upload_stores(self, file: UploadFile) -> UploadResponse:
        self._check_file_name(file.filename)
        content = await self._read_limited(file)
        rows = self._parser.parse(content)

        upload_id = uuid4()
        store_ids = await self._store_repository.bulk_create(upload_id, rows)
        row_count = len(store_ids)
        job, task_ids = await self._jobs_service.create_job(upload_id, store_ids)
        # Stores, job and tasks are committed before any event is sent, so the
        # worker never receives an event for a row it can't see yet.
        await self._session.commit()
        logger.info(
            "Saved %d stores from %s as upload %s (job %s)",
            row_count,
            file.filename,
            upload_id,
            job.id,
        )

        try:
            job_status = await self._jobs_service.dispatch(job.id, task_ids)
        except Exception as e:
            raise EnrichmentDispatchError(
                f"The stores were saved as upload {upload_id}, but enrichment job "
                f"{job.id} could not be started: {e}"
            ) from e

        return UploadResponse(
            upload_id=upload_id,
            row_count=row_count,
            job_id=job.id,
            job_status=job_status,
        )

    @staticmethod
    def _check_file_name(file_name: str | None) -> None:
        if not file_name or not file_name.lower().endswith(".csv"):
            raise InvalidUploadError("Upload a .csv file.")

    async def _read_limited(self, file: UploadFile) -> bytes:
        # Reading one byte past the limit is enough to detect a too-large file.
        content = await file.read(self._max_size_bytes + 1)
        if len(content) > self._max_size_bytes:
            limit_mb = self._max_size_bytes / (1024 * 1024)
            raise UploadTooLargeError(f"The file is larger than {limit_mb:g} MB.")
        return content


UploadServiceDep = Annotated[UploadService, Depends()]
