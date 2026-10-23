from uuid import UUID

from pydantic import BaseModel


class UploadResponse(BaseModel):
    upload_id: UUID
    row_count: int
