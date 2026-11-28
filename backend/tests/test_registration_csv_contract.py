"""SCH-01 portable CSV limits, syntax, normalization and private diagnostics."""

import csv
import io
from dataclasses import asdict
from uuid import uuid4

import pytest

from app.scheduling.api import RegistrationBatch
from assessment_core.registration_csv import COLUMNS, MAX_BYTES, RegistrationCsvError, parse_registration_csv


def document(rows, header=COLUMNS):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows(rows)
    return output.getvalue().encode()


def row(extra="", reason=""):
    return [str(uuid4()), str(uuid4()), extra, reason]


@pytest.mark.parametrize("bom", [False, True])
def test_round_trip_normalization_matches_existing_json_contract(bom):
    first = row("20", "  Approved synthetic, reason\nwith continuation  ")
    second = row()
    data = document([first, second])
    if bom:
        data = b"\xef\xbb\xbf" + data
    parsed = parse_registration_csv(data)
    batch = RegistrationBatch(registrations=parsed)
    assert batch.registrations[0].extra_minutes == 20
    assert batch.registrations[0].accommodation_reason == first[3].strip()
    assert batch.registrations[1].extra_minutes == 0
    assert batch.registrations[1].accommodation_reason is None


@pytest.mark.parametrize(
    "header",
    [
        (),
        COLUMNS[:-1],
        COLUMNS + ("email",),
        ("id", "id", "extra_minutes", "accommodation_reason"),
        tuple(reversed(COLUMNS)),
    ],
)
def test_exact_header_required(header):
    with pytest.raises(RegistrationCsvError) as error:
        parse_registration_csv(document([row()], header=header))
    assert error.value.diagnostic.code == "csv_header"


@pytest.mark.parametrize("minutes", ["-1", "241", "1000", "1.0", "01", "+1", "True", "١", "1e1"])
def test_minutes_are_bounded_ascii_integers(minutes):
    with pytest.raises(RegistrationCsvError) as error:
        parse_registration_csv(document([row(minutes, "Approved reason")]))
    assert error.value.diagnostic.column == "extra_minutes"


@pytest.mark.parametrize(
    "minutes,reason", [("0", "Unexpected reason"), ("20", ""), ("20", "   "), ("20", "ab"), ("20", "x" * 501)]
)
def test_reason_contract_is_preserved(minutes, reason):
    with pytest.raises(RegistrationCsvError) as error:
        parse_registration_csv(document([row(minutes, reason)]))
    assert error.value.diagnostic.code == "csv_reason"


@pytest.mark.parametrize("column", [0, 1])
def test_duplicate_semantic_uuid_rejected(column):
    first, second = row(), row()
    second[column] = first[column].replace("-", "")
    with pytest.raises(RegistrationCsvError) as error:
        parse_registration_csv(document([first, second]))
    assert asdict(error.value.diagnostic) == {"row": 3, "column": COLUMNS[column], "code": "csv_duplicate"}


@pytest.mark.parametrize("column", [0, 1])
def test_bad_uuid_diagnostic_does_not_retain_raw_value(column):
    cells = row()
    cells[column] = "PRIVATE_INVALID_VALUE"
    with pytest.raises(RegistrationCsvError) as error:
        parse_registration_csv(document([cells]))
    assert error.value.diagnostic.column == COLUMNS[column]
    assert "PRIVATE_INVALID_VALUE" not in str(error.value) + str(asdict(error.value.diagnostic))


@pytest.mark.parametrize(
    "data,code",
    [
        (b"", "csv_header"),
        (b"\xff", "csv_encoding"),
        (b"a\x00b", "csv_nul"),
        (b"x" * (MAX_BYTES + 1), "csv_too_large"),
    ],
)
def test_invalid_documents_fail_safely(data, code):
    with pytest.raises(RegistrationCsvError) as error:
        parse_registration_csv(data)
    assert error.value.diagnostic.code == code


def test_empty_body_rows_extra_columns_and_row_cap():
    with pytest.raises(RegistrationCsvError, match="csv_empty"):
        parse_registration_csv(document([]))
    for cells in ([], row() + ["extra"], row()[:-1]):
        with pytest.raises(RegistrationCsvError, match="csv_column_count"):
            parse_registration_csv(document([cells]))
    assert len(parse_registration_csv(document([row() for _ in range(50)]))) == 50
    with pytest.raises(RegistrationCsvError, match="csv_row_limit"):
        parse_registration_csv(document([row() for _ in range(51)]))


def test_malformed_quoted_record_reports_logical_record_number():
    data = document([row()]) + b'"unclosed,PRIVATE_REASON'
    with pytest.raises(RegistrationCsvError) as error:
        parse_registration_csv(data)
    assert error.value.diagnostic.row == 3 and error.value.diagnostic.code == "csv_syntax"
    assert "PRIVATE_REASON" not in str(error.value)
