"""SCH-01 acceptance input and candidate projection privacy."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.audit.service import clean_state
from app.scheduling.invitation_api import AcceptanceBody, invitation_view


@pytest.mark.parametrize(
    "body",
    [
        {"candidate_user_id": str(uuid4())},
        {"registration_revision": 10},
        {"accepted_at": "2030-01-01"},
        {"policy": {}},
        {"reason": "private"},
    ],
)
def test_candidate_cannot_choose_acknowledgement_identity_revision_or_time(body):
    with pytest.raises(ValidationError):
        AcceptanceBody.model_validate(body)


def view(*, cancelled=False, status="active", accepted=None, offset=-1):
    start = datetime(2030, 1, 1, tzinfo=UTC)
    sitting = SimpleNamespace(
        id=uuid4(),
        publication_id=uuid4(),
        title="Safe title",
        opens_at=start,
        closes_at=start + timedelta(hours=1),
        display_timezone="UTC",
        policy={"secret": "forbidden"},
    )
    registration = SimpleNamespace(id=uuid4(), accommodation_reason="PRIVATE_REASON")
    effective = {"revision": 2, "status": status, "allowed_minutes": 45}
    return invitation_view(
        sitting, registration, effective, start + timedelta(seconds=offset), cancelled, accepted
    )


def test_inbox_projection_omits_private_policy_and_reasons():
    body = view()
    assert body["can_accept"] is True and body["can_start"] is False
    assert "PRIVATE_REASON" not in str(body) and "secret" not in str(body)
    assert set(body) == {
        "sitting_id",
        "publication_id",
        "title",
        "registration_id",
        "allowed_minutes",
        "opens_at",
        "closes_at",
        "display_timezone",
        "window_state",
        "can_start",
        "server_time",
        "deadline_if_started_now",
        "registration_revision",
        "registration_status",
        "acceptance",
        "can_accept",
    }


@pytest.mark.parametrize(
    "cancelled,status,offset,state",
    [
        (True, "active", 0, "cancelled"),
        (False, "withdrawn", 0, "withdrawn"),
        (False, "active", 3600, "closed"),
    ],
)
def test_unavailable_invitations_cannot_be_accepted(cancelled, status, offset, state):
    body = view(cancelled=cancelled, status=status, offset=offset)
    assert body["can_accept"] is False and body["can_start"] is False and body["window_state"] == state


def test_acceptance_is_not_a_start_or_a_required_eligibility_gate():
    receipt = SimpleNamespace(
        registration_id=uuid4(),
        sitting_id=uuid4(),
        registration_revision=1,
        accepted_at=datetime(2030, 1, 1, tzinfo=UTC),
    )
    accepted = view(accepted=receipt)
    assert accepted["can_accept"] is False and accepted["can_start"] is False
    assert view(offset=0)["can_start"] is True


def test_acceptance_audit_rejects_arbitrary_fields():
    assert clean_state("exam.invitation_accepted", {}) == {}
    with pytest.raises(ValueError):
        clean_state("exam.invitation_accepted", {"reason": "private"})
