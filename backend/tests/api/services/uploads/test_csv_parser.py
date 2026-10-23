from pytest import fixture, raises

from api.exceptions import InvalidUploadError
from api.schemas.stores import StoreRow
from api.services.uploads.csv_parser import StoreCsvParser

HEADER = "store_id,store_name,address,city,state,country"
ROW_1 = "ST000001,Fresh Supermarket #1,71 Church Street,New Delhi,Delhi,India"
ROW_2 = "ST000002,City Pharmacy #2,27 Hill Street,New Delhi,Delhi,India"


def csv_bytes(*lines: str) -> bytes:
    return "\n".join(lines).encode()


class TestStoreCsvParserValidFiles:
    @fixture
    def parser(self):
        return StoreCsvParser()

    def test_parses_every_row(self, parser):
        rows = parser.parse(csv_bytes(HEADER, ROW_1, ROW_2))

        assert rows == [
            StoreRow(
                store_id="ST000001",
                store_name="Fresh Supermarket #1",
                address="71 Church Street",
                city="New Delhi",
                state="Delhi",
                country="India",
            ),
            StoreRow(
                store_id="ST000002",
                store_name="City Pharmacy #2",
                address="27 Hill Street",
                city="New Delhi",
                state="Delhi",
                country="India",
            ),
        ]

    def test_accepts_columns_in_any_order(self, parser):
        rows = parser.parse(
            csv_bytes(
                "country,state,city,address,store_name,store_id",
                "India,Delhi,New Delhi,71 Church Street,Fresh Supermarket #1,ST000001",
            )
        )

        assert rows[0].store_id == "ST000001"
        assert rows[0].country == "India"

    def test_trims_whitespace_in_header_and_values(self, parser):
        rows = parser.parse(
            csv_bytes(
                " store_id , store_name,address,city,state,country ",
                " ST000001 , Fresh #1 ,71 Church Street,New Delhi,Delhi,India",
            )
        )

        assert rows[0].store_id == "ST000001"
        assert rows[0].store_name == "Fresh #1"

    def test_accepts_excel_byte_order_mark(self, parser):
        rows = parser.parse(b"\xef\xbb\xbf" + csv_bytes(HEADER, ROW_1))

        assert rows[0].store_id == "ST000001"

    def test_accepts_quoted_values_with_commas(self, parser):
        rows = parser.parse(
            csv_bytes(HEADER, 'ST000001,"Fresh, Daily",71 Church Street,Delhi,DL,India')
        )

        assert rows[0].store_name == "Fresh, Daily"

    def test_skips_blank_lines(self, parser):
        rows = parser.parse(csv_bytes(HEADER, ROW_1, "", ROW_2, ""))

        assert [row.store_id for row in rows] == ["ST000001", "ST000002"]


class TestStoreCsvParserInvalidFiles:
    @fixture
    def parser(self):
        return StoreCsvParser()

    def test_rejects_empty_file(self, parser):
        with raises(InvalidUploadError, match="The file is empty"):
            parser.parse(b"")

    def test_rejects_header_without_rows(self, parser):
        with raises(InvalidUploadError, match="no store rows"):
            parser.parse(csv_bytes(HEADER))

    def test_rejects_non_utf8_file(self, parser):
        with raises(InvalidUploadError, match="UTF-8"):
            parser.parse("store_id\nSté".encode("latin-1"))

    def test_lists_missing_and_unexpected_columns(self, parser):
        with raises(InvalidUploadError) as error:
            parser.parse(csv_bytes("store_id,name,address,city,state", ROW_1))

        assert error.value.detail.startswith("Invalid header")
        assert error.value.errors == [
            "Missing columns: store_name, country",
            "Unexpected columns: name",
        ]

    def test_rejects_duplicate_columns(self, parser):
        with raises(InvalidUploadError) as error:
            parser.parse(csv_bytes(HEADER + ",city", ROW_1 + ",Delhi"))

        assert "Duplicate columns: city" in error.value.errors

    def test_rejects_row_with_blank_value(self, parser):
        with raises(InvalidUploadError) as error:
            parser.parse(
                csv_bytes(HEADER, ROW_1, "ST000002,,27 Hill St,  ,Delhi,India")
            )

        assert error.value.errors == ["Row 3: empty store_name, city"]

    def test_rejects_row_with_wrong_number_of_values(self, parser):
        with raises(InvalidUploadError) as error:
            parser.parse(csv_bytes(HEADER, "ST000001,Fresh,71 Church Street"))

        assert error.value.errors == ["Row 2: expected 6 values, found 3"]

    def test_rejects_duplicate_store_id(self, parser):
        with raises(InvalidUploadError) as error:
            parser.parse(csv_bytes(HEADER, ROW_1, ROW_2, ROW_1))

        assert error.value.errors == [
            "Row 4: duplicate store_id ST000001 (first seen in row 2)"
        ]

    def test_reports_at_most_twenty_errors(self, parser):
        bad_rows = [f"ST{n:06d},,a,b,c,d" for n in range(25)]

        with raises(InvalidUploadError) as error:
            parser.parse(csv_bytes(HEADER, *bad_rows))

        assert error.value.detail == "25 invalid row(s); no stores were saved."
        assert len(error.value.errors) == 21
        assert error.value.errors[-1] == "...and 5 more"
