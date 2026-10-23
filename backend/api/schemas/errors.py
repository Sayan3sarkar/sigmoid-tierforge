from pydantic import BaseModel


class ErrorResponse(BaseModel):
    detail: str
    errors: list[str] = []
