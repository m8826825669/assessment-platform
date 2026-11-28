"""SCH-01 bounded UTF-8 CSV profile for existing candidate registrations."""

import csv
import io
import re
from dataclasses import dataclass
from uuid import UUID

MAX_BYTES = 65536
MAX_ROWS = 50
COLUMNS = ("id", "candidate_user_id", "extra_minutes", "accommodation_reason")


@dataclass(frozen=True)
class CsvDiagnostic:
    row: int | None
    column: str | None
    code: str


class RegistrationCsvError(ValueError):
    def __init__(self, row, column, code):
        self.diagnostic = CsvDiagnostic(row, column, code)
        # Never retain raw cells or parser exception text.
        super().__init__(code)


def parse_registration_csv(data: bytes) -> list[dict]:
    if len(data) > MAX_BYTES:
        raise RegistrationCsvError(None, None, "csv_too_large")
    try:
        document = data.decode("utf-8-sig")
    except UnicodeError:
        raise RegistrationCsvError(None, None, "csv_encoding") from None
    if "\x00" in document:
        raise RegistrationCsvError(None, None, "csv_nul")
    reader = csv.reader(io.StringIO(document, newline=""), strict=True)
    row_number = 1
    rows, identities, candidates = [], set(), set()
    try:
        header = next(reader, None)
        if header is None or tuple(cell.strip() for cell in header) != COLUMNS:
            raise RegistrationCsvError(1, None, "csv_header")
        for row_number, cells in enumerate(reader, start=2):
            if len(rows) >= MAX_ROWS:
                raise RegistrationCsvError(row_number, None, "csv_row_limit")
            if len(cells) != len(COLUMNS):
                raise RegistrationCsvError(row_number, None, "csv_column_count")
            cells = [cell.strip() for cell in cells]
            ids = []
            for column, value in zip(COLUMNS[:2], cells[:2], strict=True):
                try:
                    ids.append(UUID(value))
                except ValueError:
                    raise RegistrationCsvError(row_number, column, "csv_uuid") from None
            for column, identity, seen in zip(COLUMNS[:2], ids, (identities, candidates), strict=True):
                if identity in seen:
                    raise RegistrationCsvError(row_number, column, "csv_duplicate")
                seen.add(identity)
            minutes = cells[2] or "0"
            if re.fullmatch(r"0|[1-9][0-9]{0,2}", minutes) is None or int(minutes) > 240:
                raise RegistrationCsvError(row_number, "extra_minutes", "csv_extra_minutes")
            minutes = int(minutes)
            reason = cells[3] or None
            if (minutes and (reason is None or not 3 <= len(reason) <= 500)) or (
                not minutes and reason is not None
            ):
                raise RegistrationCsvError(row_number, "accommodation_reason", "csv_reason")
            rows.append(
                dict(
                    id=str(ids[0]),
                    candidate_user_id=str(ids[1]),
                    extra_minutes=minutes,
                    accommodation_reason=reason,
                )
            )
    except csv.Error:
        raise RegistrationCsvError(row_number + 1, None, "csv_syntax") from None
    if not rows:
        raise RegistrationCsvError(2, None, "csv_empty")
    return rows
