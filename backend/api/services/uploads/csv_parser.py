from csv import Error as CsvError
from csv import reader
from io import StringIO
from typing import Annotated

from fastapi import Depends

from api.exceptions import InvalidUploadError
from api.schemas.stores import StoreRow

REQUIRED_COLUMNS = ("store_id", "store_name", "address", "city", "state", "country")


class StoreCsvParser:
    """Turns an uploaded store CSV into validated rows, or raises InvalidUploadError.

    Rules: the six required columns in any order and nothing else; every value
    non-blank (after trimming); store_id unique within the file; at least one row.
    The file is accepted or rejected as a whole.
    """

    MAX_REPORTED_ERRORS = 20

    def parse(self, content: bytes) -> list[StoreRow]:
        lines = reader(StringIO(self._decode(content)))
        try:
            header = next(lines, None)
            if header is None or not any(name.strip() for name in header):
                raise InvalidUploadError("The file is empty.")
            column_index = self._validate_header(header)
            rows, errors = self._parse_rows(lines, column_index, len(header))
        except CsvError as e:
            raise InvalidUploadError(f"The file is not valid CSV: {e}") from e

        if errors:
            raise InvalidUploadError(
                f"{len(errors)} invalid row(s); no stores were saved.",
                errors=self._truncate(errors),
            )
        if not rows:
            raise InvalidUploadError("The file has a header but no store rows.")
        return rows

    @staticmethod
    def _decode(content: bytes) -> str:
        try:
            return content.decode("utf-8-sig")  # tolerates Excel's byte-order mark
        except UnicodeDecodeError as e:
            raise InvalidUploadError("The file must be UTF-8 encoded.") from e

    @staticmethod
    def _validate_header(header: list[str]) -> dict[str, int]:
        names = [name.strip() for name in header]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        missing = [name for name in REQUIRED_COLUMNS if name not in names]
        unexpected = [name for name in names if name not in REQUIRED_COLUMNS]

        errors = []
        if missing:
            errors.append(f"Missing columns: {', '.join(missing)}")
        if unexpected:
            errors.append(f"Unexpected columns: {', '.join(unexpected)}")
        if duplicates:
            errors.append(f"Duplicate columns: {', '.join(duplicates)}")
        if errors:
            raise InvalidUploadError(
                f"Invalid header. Expected columns: {', '.join(REQUIRED_COLUMNS)}.",
                errors=errors,
            )
        return {name: names.index(name) for name in REQUIRED_COLUMNS}

    @staticmethod
    def _parse_rows(
        lines, column_index: dict[str, int], column_count: int
    ) -> tuple[list[StoreRow], list[str]]:
        rows: list[StoreRow] = []
        errors: list[str] = []
        first_seen: dict[str, int] = {}

        # Row numbers count the header as row 1, so they match a spreadsheet view.
        for row_number, values in enumerate(lines, start=2):
            if not any(value.strip() for value in values):
                continue  # blank line
            if len(values) != column_count:
                errors.append(
                    f"Row {row_number}: expected {column_count} values,"
                    f" found {len(values)}"
                )
                continue

            record = {
                name: values[index].strip() for name, index in column_index.items()
            }
            blank = [name for name, value in record.items() if not value]
            if blank:
                errors.append(f"Row {row_number}: empty {', '.join(blank)}")
                continue

            store_id = record["store_id"]
            if store_id in first_seen:
                errors.append(
                    f"Row {row_number}: duplicate store_id {store_id} "
                    f"(first seen in row {first_seen[store_id]})"
                )
                continue
            first_seen[store_id] = row_number
            rows.append(StoreRow(**record))

        return rows, errors

    @classmethod
    def _truncate(cls, errors: list[str]) -> list[str]:
        if len(errors) <= cls.MAX_REPORTED_ERRORS:
            return errors
        hidden = len(errors) - cls.MAX_REPORTED_ERRORS
        return [*errors[: cls.MAX_REPORTED_ERRORS], f"...and {hidden} more"]


StoreCsvParserDep = Annotated[StoreCsvParser, Depends()]
