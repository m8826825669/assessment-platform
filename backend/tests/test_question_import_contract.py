"""P2-006 internal profile, canonical retries and bounded/redacted JSON."""

import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.audit.service import clean_state
from app.question_imports.contracts import (
    MAX_BYTES,
    PROFILE,
    Batch,
    fingerprint,
    parse,
    request_schema,
    safe_errors,
)

EXAMPLES = json.loads(
    (Path(__file__).resolve().parents[2] / "docs/QUESTION_CONTENT_EXAMPLES.json").read_text()
)


def payload(content=None):
    return {
        "schema_version": PROFILE,
        "items": [{"reference": "first", "title": "Fixture", "content": deepcopy(content or EXAMPLES[0])}],
    }


@pytest.mark.parametrize("content", EXAMPLES, ids=[c["kind"] for c in EXAMPLES])
def test_import_reuses_all_seven_content_contracts(content):
    batch = parse(json.dumps(payload(content)).encode())
    assert batch.items[0].content.kind == content["kind"]
    assert len(fingerprint(batch)) == 64


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": "unknown"},
        {"items": []},
        {"actor_user_id": str(uuid4())},
        {"items": [{"reference": "first", "title": "Fixture", "content": EXAMPLES[0], "state": "approved"}]},
        {
            "items": [
                {"reference": "first", "title": "Fixture", "content": EXAMPLES[0], "expected_revision": 1}
            ]
        },
    ],
)
def test_import_rejects_authority_updates_or_unsupported_profiles(change):
    with pytest.raises(ValidationError):
        Batch.model_validate({**payload(), **change})


def test_duplicate_references_and_batch_count_and_media_totals_are_bounded():
    item = payload()["items"][0]
    for items in [
        [item, item],
        [{**item, "reference": "row_" + str(n)} for n in range(51)],
        [
            {**item, "reference": "a", "media_ids": [str(uuid4()) for _ in range(9)]},
            {**item, "reference": "b", "media_ids": [str(uuid4()) for _ in range(8)]},
        ],
    ]:
        with pytest.raises(ValidationError):
            Batch.model_validate({"schema_version": PROFILE, "items": items})


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"{",
        b"\xff",
        b"NaN",
        b'{"a":1,"a":2}',
        b'{"items":[],"content":{"key":1,"key":2}}',
        b"[" * 70 + b"0" + b"]" * 70,
        b"x" * (MAX_BYTES + 1),
    ],
)
def test_malformed_ambiguous_deep_or_unbounded_json_is_rejected(data):
    with pytest.raises((ValueError, UnicodeError)):
        parse(data)


def test_encoding_whitespace_property_order_and_decimal_spelling_are_retry_equivalent():
    first = payload()
    second = deepcopy(first)
    second["items"][0]["content"]["points"] = "1.00"
    first["items"][0]["content"]["points"] = "1"
    assert fingerprint(parse(json.dumps(first).encode())) == fingerprint(
        parse(b"\xef\xbb\xbf" + json.dumps(second, indent=4, sort_keys=True).encode())
    )


@pytest.mark.parametrize("field", ["title", "reference", "answer", "taxonomy", "media", "row_order"])
def test_changed_meaning_or_row_order_changes_fingerprint(field):
    original = payload()
    original["items"].append({**deepcopy(original["items"][0]), "reference": "second"})
    changed = deepcopy(original)
    if field == "answer":
        item = changed["items"][0]["content"]
        item["correct_option_id"] = next(
            x["id"] for x in item["options"] if x["id"] != item["correct_option_id"]
        )
    elif field in {"taxonomy", "media"}:
        changed["items"][0][field + "_ids"] = [str(uuid4())]
    elif field == "row_order":
        changed["items"].reverse()
    else:
        changed["items"][0][field] = "changed"
    assert fingerprint(Batch.model_validate(original)) != fingerprint(Batch.model_validate(changed))


def test_reference_array_order_is_not_semantic():
    original = payload()
    original["items"][0]["taxonomy_ids"] = [str(uuid4()), str(uuid4())]
    changed = deepcopy(original)
    changed["items"][0]["taxonomy_ids"].reverse()
    assert fingerprint(Batch.model_validate(original)) == fingerprint(Batch.model_validate(changed))


def test_unknown_property_names_and_raw_scoring_values_are_redacted_from_errors():
    invalid = payload()
    invalid["items"][0]["PRIVATE_SECRET_VALUE"] = "PRIVATE_ANSWER"
    try:
        Batch.model_validate(invalid)
    except ValidationError as error:
        safe = safe_errors(error)
    assert "PRIVATE" not in json.dumps(safe)
    assert safe[0]["loc"][-1] == "unknown_field"


def test_manual_streaming_body_has_complete_reference_free_openapi_schema():
    schema = request_schema()
    encoded = json.dumps(schema)
    assert "$ref" not in encoded and "$defs" not in encoded
    assert schema["additionalProperties"] is False
    assert schema["properties"]["items"]["maxItems"] == 50


def test_import_audit_excludes_keys_private_bodies_and_client_references():
    action = "question.import_committed"
    assert clean_state(action, {"batch_id": str(uuid4()), "item_count": 1})
    for body in [
        {"content": "secret"},
        {"idempotency_key": str(uuid4())},
        {"reference": "secret"},
        {"request_hash": "a" * 64},
        {"item_count": True},
        {"item_count": 51},
    ]:
        with pytest.raises(ValueError):
            clean_state(action, body)
