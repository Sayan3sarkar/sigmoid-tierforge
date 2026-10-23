from pydantic import ValidationError
from pytest import mark, raises

from api.schemas.pagination import MAX_PAGE_SIZE, PageParams


class TestPageParams:
    def test_defaults_to_the_first_page_of_50(self):
        page = PageParams()

        assert (page.page, page.page_size, page.offset) == (1, 50, 0)

    @mark.parametrize(
        "page, page_size, offset", [(1, 50, 0), (2, 50, 50), (3, 20, 40), (1, 1, 0)]
    )
    def test_offset_skips_the_earlier_pages(self, page, page_size, offset):
        assert PageParams(page=page, page_size=page_size).offset == offset

    def test_accepts_the_largest_page_size(self):
        assert PageParams(page_size=MAX_PAGE_SIZE).page_size == 200

    @mark.parametrize(
        "values", [{"page": 0}, {"page_size": 0}, {"page_size": MAX_PAGE_SIZE + 1}]
    )
    def test_rejects_out_of_range_values(self, values):
        with raises(ValidationError):
            PageParams(**values)
