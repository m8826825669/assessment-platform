"""SCH-01 timing boundaries and candidate-safe contract validation."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.audit.service import clean_state
from app.scheduling.api import RegistrationBatch, RegistrationBody, SittingBody
from assessment_core.scheduling import check_window, display_offset, start_readiness

START = datetime(2027, 1, 1, 10, tzinfo=UTC)
END = START + timedelta(hours=1)


@pytest.mark.parametrize("zone", ["UTC", "UTC+05:30", "UTC-12:00", "UTC+14:00"])
def test_fixed_display_offsets(zone):
    assert display_offset(zone) == zone


@pytest.mark.parametrize("zone", ["local", "Asia/Kolkata", "UTC+14:01", "UTC+05:60", "UTC+5:30", "UTC+25:00"])
def test_unsupported_or_invalid_display_offset(zone):
    with pytest.raises(ValueError):
        display_offset(zone)


@pytest.mark.parametrize("offset,state", [(-1, "upcoming"), (0, "open"), (3599, "open"), (3600, "closed")])
def test_server_window_boundaries(offset, state):
    result = start_readiness(START, END, START + timedelta(seconds=offset), 45)
    assert result["window_state"] == state
    assert result["can_start"] == (state == "open")
    if state == "open":
        assert result["deadline_if_started_now"] <= END
    else:
        assert result["deadline_if_started_now"] is None


def test_extra_time_never_exceeds_hard_close():
    result = start_readiness(START, END, END - timedelta(minutes=2), 90)
    assert result["deadline_if_started_now"] == END


@pytest.mark.parametrize("minutes", [61, 1440])
def test_window_must_fit_effective_duration(minutes):
    with pytest.raises(ValueError):
        check_window(START, END, minutes)


def test_timezone_naive_schedule_rejected():
    with pytest.raises(ValidationError):
        SittingBody(publication_id=uuid4(), title="Exam", opens_at=START.replace(tzinfo=None), closes_at=END)


@pytest.mark.parametrize("minutes", [-1, True, "15", 241])
def test_invalid_accommodation_minutes(minutes):
    with pytest.raises(ValidationError):
        RegistrationBody(
            id=uuid4(),
            candidate_user_id=uuid4(),
            extra_minutes=minutes,
            accommodation_reason="Approved extra time",
        )


def test_extra_time_requires_reason_and_duplicate_import_rejected():
    with pytest.raises(ValidationError):
        RegistrationBody(id=uuid4(), candidate_user_id=uuid4(), extra_minutes=15)
    row = RegistrationBody(id=uuid4(), candidate_user_id=uuid4())
    with pytest.raises(ValidationError):
        RegistrationBatch(registrations=[row, row])


@pytest.mark.parametrize("action", ["exam.sitting_created", "exam.candidate_registered"])
def test_scheduling_audit_rejects_private_data(action):
    assert clean_state(action, {}) == {}
    with pytest.raises(ValueError):
        clean_state(action, {"accommodation_reason": "Private candidate information"})
