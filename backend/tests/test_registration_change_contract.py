"""SCH-01 input/privacy boundaries for registration decisions."""

import pytest
from pydantic import ValidationError

from app.audit.service import clean_state
from app.scheduling.api import RegistrationChangeBody


@pytest.mark.parametrize(
    "body",
    [
        {"expected_revision": 0, "action": "withdraw", "reason": "Approved"},
        {"expected_revision": True, "action": "withdraw", "reason": "Approved"},
        {"expected_revision": 1, "action": "restore", "reason": "Approved"},
        {"expected_revision": 1, "action": "withdraw", "extra_minutes": 1, "reason": "Approved"},
        {"expected_revision": 1, "action": "amend_accommodation", "reason": "Approved"},
        {
            "expected_revision": 1,
            "action": "amend_accommodation",
            "extra_minutes": True,
            "reason": "Approved",
        },
        {"expected_revision": 1, "action": "amend_accommodation", "extra_minutes": 241, "reason": "Approved"},
        {"expected_revision": 1, "action": "amend_accommodation", "extra_minutes": -1, "reason": "Approved"},
        {"expected_revision": 1, "action": "withdraw", "reason": "   "},
        {"expected_revision": 1, "action": "withdraw", "reason": "x" * 501},
        {"expected_revision": 1, "action": "withdraw", "reason": "Approved", "candidate_user_id": "extra"},
    ],
)
def test_invalid_decisions_fail_closed(body):
    with pytest.raises(ValidationError):
        RegistrationChangeBody.model_validate(body)


def test_allowance_removal_is_explicit_and_reason_is_normalized():
    body = RegistrationChangeBody(
        expected_revision=2,
        action="amend_accommodation",
        extra_minutes=0,
        reason="  Reviewed allowance removal  ",
    )
    assert body.extra_minutes == 0 and body.reason == "Reviewed allowance removal"


@pytest.mark.parametrize("action", ["exam.registration_withdrawn", "exam.registration_accommodation_changed"])
def test_private_decision_data_cannot_enter_audit_state(action):
    assert clean_state(action, {}) == {}
    with pytest.raises(ValueError):
        clean_state(action, {"reason": "Private synthetic record"})
