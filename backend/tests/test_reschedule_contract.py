"""SCH-01 public rescheduling input boundaries."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.audit.service import clean_state
from app.scheduling.reschedule_api import RescheduleBody


def body():
    start = datetime(2030, 1, 1, tzinfo=UTC)
    return dict(
        replacement_id=uuid4(),
        opens_at=start,
        closes_at=start + timedelta(hours=2),
        reason_code="schedule_error",
    )


@pytest.mark.parametrize(
    "change",
    [
        {"publication_id": str(uuid4())},
        {"title": "Change content"},
        {"reason_code": "private custom text"},
        {"display_timezone": "Asia/Kolkata"},
        {"display_timezone": "UTC+14:01"},
        {"opens_at": "2030-01-01T10:00:00"},
        {"closes_at": "2029-01-01T10:00:00Z"},
        {"replacement_id": "bad"},
    ],
)
def test_reschedule_rejects_policy_changes_and_invalid_timing(change):
    with pytest.raises(ValidationError):
        RescheduleBody.model_validate({**body(), **change})


def test_display_offset_is_optional_and_fixed_when_supplied():
    assert RescheduleBody.model_validate(body()).display_timezone is None
    assert (
        RescheduleBody.model_validate({**body(), "display_timezone": "UTC+05:30"}).display_timezone
        == "UTC+05:30"
    )


def test_reschedule_audit_never_accepts_arbitrary_request_data():
    assert clean_state("exam.sitting_rescheduled", {}) == {}
    with pytest.raises(ValueError):
        clean_state("exam.sitting_rescheduled", {"reason": "Private input"})
