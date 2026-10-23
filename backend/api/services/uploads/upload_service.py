from logging import getLogger
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, UploadFile

from api.exceptions import InvalidUploadError, UploadTooLargeError
from api.repositories.store import StoreRepositoryDep
from api.schemas.uploads import UploadResponse
from api.services.uploads.csv_parser import StoreCsvParserDep
from config import ConfigDep

logger = getLogger(__name__)


class UploadService:
    """Accepts a store CSV: checks the file, validates its contents, saves the stores.

    All-or-nothing: either every row is saved under a new upload_id, or none is.
    """

    def __init__(
        self,
        parser: StoreCsvParserDep,
        repository: StoreRepositoryDep,
        config: ConfigDep,
    ) -> None:
        self._parser = parser
        self._repository = repository
        self._max_size_bytes = config.upload.max_size_bytes

    async def upload_stores(self, file: UploadFile) -> UploadResponse:
        self._check_file_name(file.filename)
        content = await self._read_limited(file)
        rows = self._parser.parse(content)

        upload_id = uuid4()
        row_count = await self._repository.bulk_create(upload_id, rows)
        logger.info(
            "Saved %d stores from %s as upload %s", row_count, file.filename, upload_id
        )
        return UploadResponse(upload_id=upload_id, row_count=row_count)

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
