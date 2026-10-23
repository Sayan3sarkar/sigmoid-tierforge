from uuid import UUID

from pydantic import BaseModel

from api.models.enums import JobStatus


class UploadResponse(BaseModel):
    upload_id: UUID
    row_count: int
    job_id: int
    job_status: JobStatus
