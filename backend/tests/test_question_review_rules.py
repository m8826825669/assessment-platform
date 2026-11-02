"""Workflow, command and safe-audit contracts; real database tests are separate."""

from itertools import product

import pytest
from pydantic import ValidationError

from app.audit.service import clean_state
from app.question_bank.review import TRANSITIONS, transition
from app.question_bank.review_api import ReviewBody


@pytest.mark.parametrize(
    "state,action",
    list(
        product(
            ["draft", "in_review", "returned", "approved", "retired", "superseded"],
            ["submit", "return", "approve", "retire", "supersede"],
        )
    ),
)
def test_workflow_allows_only_registered_transitions(state, action):
    if (state, action) in TRANSITIONS:
        assert transition(state, action) == TRANSITIONS[state, action]
    else:
        with pytest.raises(ValueError):
            transition(state, action)


@pytest.mark.parametrize(
    "change",
    [
        {"action": "supersede"},
        {"expected_revision": True},
        {"expected_revision": 0},
        {"expected_review_revision": True},
        {"expected_review_revision": -1},
        {"content_hash": "bad"},
        {"reason": "Unrequested text"},
        {"state": "approved"},
        {"action": "return"},
        {"action": "retire"},
    ],
)
def test_review_command_rejects_invalid_or_privileged_input(change):
    with pytest.raises(ValidationError):
        ReviewBody.model_validate(
            {
                "action": "submit",
                "expected_revision": 1,
                "expected_review_revision": 0,
                "content_hash": "a" * 64,
                **change,
            }
        )


@pytest.mark.parametrize("action", ["return", "retire"])
def test_reasons_are_required_and_bounded(action):
    base = {"action": action, "expected_revision": 1, "expected_review_revision": 1, "content_hash": "a" * 64}
    assert ReviewBody.model_validate({**base, "reason": "Please clarify the prompt."}).reason
    for reason in ["", " ", "x" * 1001, "bad\x00text"]:
        with pytest.raises(ValidationError):
            ReviewBody.model_validate({**base, "reason": reason})


@pytest.mark.parametrize("action", ["submitted", "returned", "approved", "retired", "superseded"])
def test_review_audit_forbids_feedback_and_content(action):
    registered = "question.review_" + action
    assert clean_state(registered, {"review_revision": 0, "review_state": "draft"})
    for key in ["reason", "content", "prompt", "rubric", "title"]:
        with pytest.raises(ValueError):
            clean_state(registered, {key: "private"})
    for invalid in [{"review_state": "unknown"}, {"review_revision": True}, {"review_revision": -1}]:
        with pytest.raises(ValueError):
            clean_state(registered, invalid)
