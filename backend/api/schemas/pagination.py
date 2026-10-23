from typing import Annotated, Generic, TypeAlias, TypeVar

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field

ItemT = TypeVar("ItemT", bound=BaseModel)

MAX_PAGE_SIZE = 200


class PageParams(BaseModel):
    """`page` and `page_size` query parameters of a paginated list."""

    # No extra="forbid": several query models share one query string, and
    # each would reject the others' parameters.
    model_config = ConfigDict(frozen=True)

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=MAX_PAGE_SIZE)

    @property
    def offset(self) -> int:
        """Rows to skip before this page."""
        return (self.page - 1) * self.page_size


class Page(BaseModel, Generic[ItemT]):
    """One page of a list, with the number of matching items across all pages.

    The page and page size aren't echoed back: the client sent them (or relies
    on the defaults, page 1 and 50 per page).
    """

    model_config = ConfigDict(frozen=True)

    items: list[ItemT]
    # Items matching the filters across all pages.
    total_count: int


# FastAPI dependency: reads `page` and `page_size` from the query string.
PageParamsDep: TypeAlias = Annotated[PageParams, Query()]
