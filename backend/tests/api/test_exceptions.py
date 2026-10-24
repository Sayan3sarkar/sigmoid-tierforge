from pytest import mark

from api.exceptions import describe_validation_error
from api.schemas.errors import ErrorItem


class TestDescribeValidationError:
    @mark.parametrize(
        "loc, field",
        [
            (("body", "weights"), "weights"),
            (("body", "bars", "revenue"), "bars.revenue"),
            (("query", "page_size"), "page_size"),
            (("path", "job_id"), "job_id"),
            (("body", "items", 2, "store_id"), "items.2.store_id"),
        ],
    )
    def test_names_the_field_without_where_it_came_from(self, loc, field):
        error = {"loc": loc, "msg": "Field required"}

        assert describe_validation_error(error) == ErrorItem(
            field=field, message="Field required"
        )

    @mark.parametrize("loc", [("body",), ()])
    def test_an_error_about_the_whole_request_has_no_field(self, loc):
        error = {"loc": loc, "msg": "Field required"}

        assert describe_validation_error(error).field is None

    def test_drops_pydantics_prefix_from_our_own_messages(self):
        error = {
            "loc": ("body", "weights"),
            "msg": "Value error, weights must add up to 100, not 110",
        }

        assert describe_validation_error(error).message == (
            "weights must add up to 100, not 110"
        )
