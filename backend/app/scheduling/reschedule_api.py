"""SCH-01/PUB-01/GOV-01 atomic replacement of unopened sittings."""

from datetime import UTC
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select

from app.audit.service import record
from app.db.models import ExamSitting, SittingCancellation, SittingReschedule
from app.identity.api import Actor, Db
from app.identity.service import reject
from app.question_bank.review import access
from app.scheduling.api import get_sitting, sitting_response
from assessment_core.scheduling import check_window, display_offset

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}", tags=["exam sittings"])


class RescheduleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    replacement_id: UUID
    opens_at: AwareDatetime
    closes_at: AwareDatetime
    display_timezone: Annotated[str | None, Field(max_length=9)] = None
    reason_code: Literal["administrative", "schedule_error", "operational"]

    @field_validator("display_timezone")
    @classmethod
    def timezone(cls, value):
        return display_offset(value) if value is not None else value

    @model_validator(mode="after")
    def window(self):
        check_window(self.opens_at, self.closes_at, 1)
        return self


def receipt(db, link):
    replacement = get_sitting(db, link.tenant_id, link.replacement_id)
    return {
        "sitting_id": link.sitting_id,
        "replacement_id": link.replacement_id,
        "reason_code": link.reason_code,
        "rescheduled_at": link.created_at,
        "replacement": sitting_response(replacement),
    }


@router.get("/exam-sittings/{sitting_id}/reschedule")
def detail(tenant_id: UUID, sitting_id: UUID, actor: Actor, db: Db):
    access(db, tenant_id, actor, permission="exams.manage")
    get_sitting(db, tenant_id, sitting_id)
    link = db.get(SittingReschedule, (tenant_id, sitting_id))
    if link is None:
        reject(404, "reschedule_not_found", "Reschedule not found")
    return receipt(db, link)


@router.post("/exam-sittings/{sitting_id}/reschedule")
def reschedule(tenant_id: UUID, sitting_id: UUID, body: RescheduleBody, actor: Actor, db: Db):
    access(db, tenant_id, actor, lock=True, permission="exams.manage")
    original = get_sitting(db, tenant_id, sitting_id)
    opening, closing = body.opens_at.astimezone(UTC), body.closes_at.astimezone(UTC)
    zone = body.display_timezone or original.display_timezone
    existing = db.get(SittingReschedule, (tenant_id, sitting_id))
    if existing is not None:
        replacement = get_sitting(db, tenant_id, existing.replacement_id)
        if (
            existing.replacement_id != body.replacement_id
            or existing.reason_code != body.reason_code
            or replacement.opens_at != opening
            or replacement.closes_at != closing
            or replacement.display_timezone != zone
        ):
            reject(409, "reschedule_conflict", "Sitting already has a different replacement")
        response = receipt(db, existing)
        db.commit()
        return response
    if body.replacement_id == sitting_id or db.get(ExamSitting, (tenant_id, body.replacement_id)) is not None:
        reject(409, "reschedule_conflict", "Use a new replacement sitting ID")
    if db.get(SittingCancellation, (tenant_id, sitting_id)) is not None:
        reject(409, "sitting_cancelled", "Sitting is already cancelled")
    now = db.scalar(select(func.clock_timestamp()))
    if original.opens_at <= now or opening <= now:
        reject(409, "reschedule_closed", "Both sittings must be unopened")
    try:
        check_window(opening, closing, original.duration_minutes)
    except ValueError:
        reject(422, "sitting_window_too_short", "Replacement window does not fit publication duration")
    replacement = ExamSitting(
        tenant_id=tenant_id,
        id=body.replacement_id,
        publication_id=original.publication_id,
        title=original.title,
        opens_at=opening,
        closes_at=closing,
        display_timezone=zone,
        duration_minutes=original.duration_minutes,
        policy=dict(original.policy),
        created_by=actor.user_id,
    )
    db.add(replacement)
    record(
        db,
        "exam.sitting_created",
        actor=actor.user_id,
        tenant=tenant_id,
        subject=str(body.replacement_id),
        before={},
        after={},
    )
    db.add(
        SittingCancellation(
            tenant_id=tenant_id, sitting_id=sitting_id, reason_code=body.reason_code, created_by=actor.user_id
        )
    )
    record(
        db,
        "exam.sitting_cancelled",
        actor=actor.user_id,
        tenant=tenant_id,
        subject=str(sitting_id),
        before={},
        after={},
    )
    link = SittingReschedule(
        tenant_id=tenant_id,
        sitting_id=sitting_id,
        replacement_id=body.replacement_id,
        reason_code=body.reason_code,
        created_by=actor.user_id,
    )
    db.add(link)
    record(
        db,
        "exam.sitting_rescheduled",
        actor=actor.user_id,
        tenant=tenant_id,
        subject=str(sitting_id),
        before={},
        after={},
    )
    db.flush()
    response = receipt(db, link)
    db.commit()
    return response
