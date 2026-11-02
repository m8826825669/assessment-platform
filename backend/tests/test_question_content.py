"""QBK-01/QBK-02/PUB-01 content validation and secret-projection boundaries only."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.question_bank.contracts import CONTENT_ADAPTER, candidate_view, content_hash, validate_content

EXAMPLES = json.loads(
    (Path(__file__).resolve().parents[2] / "docs/QUESTION_CONTENT_EXAMPLES.json").read_text()
)
KINDS = [item["kind"] for item in EXAMPLES]


@pytest.mark.parametrize("example", EXAMPLES, ids=KINDS)
def test_supported_content_validates_and_roundtrips(example):
    item = validate_content(example)
    assert CONTENT_ADAPTER.validate_json(item.model_dump_json()) == item
    assert len(content_hash(item)) == 64


@pytest.mark.parametrize("example", EXAMPLES, ids=KINDS)
def test_candidate_projection_excludes_all_secret_fields_recursively(example):
    forbidden = {
        "correct_option_id",
        "correct_option_ids",
        "expected",
        "absolute_tolerance",
        "accepted_answers",
        "normalization",
        "rubric",
        "marker_guidance",
        "scoring",
    }

    def inspect(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)

    item = validate_content(example)
    view = candidate_view(item)
    inspect(view)
    assert view["kind"] == example["kind"]
    assert view["prompt"] == example["prompt"]


@pytest.mark.parametrize("example", EXAMPLES, ids=KINDS)
def test_unregistered_fields_are_rejected(example):
    with pytest.raises(ValidationError):
        validate_content({**example, "arbitrary_script": "do something"})


@pytest.mark.parametrize("points", ["0", "-1", "NaN", "Infinity", "10001", "1.001", True, 1.1])
def test_invalid_points_rejected(points):
    with pytest.raises(ValidationError):
        validate_content({**EXAMPLES[0], "points": points})


@pytest.mark.parametrize("prompt", ["", " \n ", "bad\x00text", "bad\ud800text", "x" * 16001])
def test_invalid_text_rejected(prompt):
    with pytest.raises(ValidationError):
        validate_content({**EXAMPLES[0], "prompt": prompt})


@pytest.mark.parametrize(
    "index,changes",
    [
        (0, {"correct_option_id": "missing"}),
        (0, {"options": [{"id": "a", "text": "One"}]}),
        (0, {"options": [{"id": "a", "text": "One"}, {"id": "a", "text": "Two"}]}),
        (0, {"options": [{"id": "a", "text": "One"}, {"id": "b", "text": " ONE "}]}),
        (1, {"correct_option_ids": []}),
        (1, {"correct_option_ids": ["a", "a"]}),
        (1, {"correct_option_ids": ["missing"]}),
        (1, {"scoring": "partial_credit"}),
        (2, {"expected": "NaN"}),
        (2, {"expected": "0.0000001"}),
        (2, {"expected": 3.1}),
        (2, {"absolute_tolerance": "-0.01"}),
        (3, {"accepted_answers": ["Paris", " PARIS "]}),
        (3, {"accepted_answers": ["Paris"], "max_response_characters": 3}),
        (3, {"normalization": {"case_sensitive": "false"}}),
        (4, {"rubric": []}),
        (4, {"rubric": [{"id": "reasoning", "description": "Reasoning", "max_points": "1"}]}),
        (5, {"allowed_extensions": [".exe"]}),
        (5, {"allowed_extensions": [".pdf", ".pdf"]}),
        (5, {"max_files": True}),
        (5, {"max_bytes_per_file": 20971521}),
        (6, {"points": "3"}),
        (6, {"children": []}),
    ],
)
def test_incoherent_type_specific_content_rejected(index, changes):
    with pytest.raises(ValidationError):
        validate_content({**EXAMPLES[index], **changes})


def test_group_rejects_nested_groups_and_repeated_identifiers():
    group = copy.deepcopy(EXAMPLES[6])
    group["children"] = [copy.deepcopy(EXAMPLES[6])]
    with pytest.raises(ValidationError):
        validate_content(group)
    group["children"] = [copy.deepcopy(EXAMPLES[0]), copy.deepcopy(EXAMPLES[0])]
    group["points"] = "4"
    with pytest.raises(ValidationError):
        validate_content(group)
    group["children"] = [{**EXAMPLES[0], "item_id": "passage_one"}]
    group["points"] = "2"
    with pytest.raises(ValidationError):
        validate_content(group)


def test_validated_content_is_detached_and_frozen_at_nested_levels():
    payload = copy.deepcopy(EXAMPLES[6])
    item = validate_content(payload)
    original = content_hash(item)
    payload["children"][0]["options"][0]["text"] = "Changed source"
    assert content_hash(item) == original
    with pytest.raises(ValidationError):
        item.children[0].options[0].text = "Changed model"
    with pytest.raises(ValidationError):
        item.prompt = "Changed prompt"
    assert isinstance(item.children, tuple)
    assert isinstance(item.children[0].options, tuple)
    view = candidate_view(item)
    view["children"][0]["options"][0]["text"] = "Changed view"
    assert content_hash(item) == original


def test_key_change_changes_full_hash_but_not_candidate_payload():
    first = validate_content(EXAMPLES[0])
    second = validate_content({**EXAMPLES[0], "correct_option_id": "b"})
    assert candidate_view(first) == candidate_view(second)
    assert content_hash(first) != content_hash(second)


def test_hash_is_independent_of_input_field_order_and_decimal_spelling():
    first = validate_content(EXAMPLES[2])
    second = validate_content(
        dict(reversed(list({**EXAMPLES[2], "points": "2.00", "expected": "3.0"}.items())))
    )
    assert content_hash(first) == content_hash(second)


def test_short_answer_matching_policy_is_explicit():
    item = validate_content(EXAMPLES[3])
    assert item.normalization.apply(" ＰＡＲＩＳ \n") == "paris"
    # Accents and punctuation are preserved, not silently discarded.
    assert item.normalization.apply("Páris!") == "páris!"
    assert validate_content(
        {**EXAMPLES[3], "accepted_answers": ["Paris", "PARIS"], "normalization": {"case_sensitive": True}}
    )


def test_unknown_kind_and_missing_discriminator_rejected():
    with pytest.raises(ValidationError):
        validate_content({**EXAMPLES[0], "kind": "arbitrary_code"})
    with pytest.raises(ValidationError):
        validate_content({key: value for key, value in EXAMPLES[0].items() if key != "kind"})
