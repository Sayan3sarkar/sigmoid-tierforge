from pydantic import BaseModel


class ErrorItem(BaseModel):
    """One problem with a request."""

    # Dotted path of the input the problem is about, e.g. "weights" or
    # "bars.revenue"; null when it isn't about one input (e.g. a CSV row).
    field: str | None = None
    message: str


class ErrorResponse(BaseModel):
    """Body of every error response."""

    detail: str
    errors: list[ErrorItem] = []
