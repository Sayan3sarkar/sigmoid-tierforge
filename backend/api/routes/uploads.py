from fastapi import APIRouter, UploadFile, status

from api.schemas.errors import ErrorResponse
from api.schemas.uploads import UploadResponse
from api.services.uploads import UploadServiceDep

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=UploadResponse,
    responses={
        413: {"model": ErrorResponse, "description": "File larger than the limit"},
        422: {"model": ErrorResponse, "description": "Not a valid store CSV"},
    },
)
async def upload_stores(file: UploadFile, service: UploadServiceDep) -> UploadResponse:
    """Upload a store CSV (store_id, store_name, address, city, state, country).

    Every row is saved under a new upload_id, or the whole file is rejected.
    """
    return await service.upload_stores(file)
