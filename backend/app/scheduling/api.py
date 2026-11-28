"""SCH-01/TEN-01 frozen sittings and atomic candidate registration."""

from datetime import UTC
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select

from app.audit.service import record
from app.db.models import (
    ExamPublication,
    ExamSitting,
    Membership,
    RegistrationChange,
    RegistrationChangeReason,
    SittingCancellation,
    SittingRegistration,
    User,
)
from app.identity.api import Actor, Db
from app.identity.service import reject, tenant_membership
from app.question_bank.review import access
from assessment_core.scheduling import check_window, display_offset, start_readiness

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}", tags=["exam sittings"])


class SittingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    publication_id: UUID
    title: Annotated[str, Field(min_length=1, max_length=160)]
    opens_at: AwareDatetime
    closes_at: AwareDatetime
    display_timezone: str = "UTC"

    @field_validator("title")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Title must not be blank")
        return value.strip()

    @field_validator("display_timezone")
    @classmethod
    def timezone(cls, value):
        return display_offset(value)

    @model_validator(mode="after")
    def window(self):
        check_window(self.opens_at, self.closes_at, 1)
        return self


class CancellationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason_code: Literal["administrative", "schedule_error", "operational"]


def cancellation_response(row):
    return {"sitting_id": row.sitting_id, "reason_code": row.reason_code, "cancelled_at": row.created_at}


@router.put("/exam-sittings/{sitting_id}/cancellation")
def cancel(tenant_id: UUID, sitting_id: UUID, body: CancellationBody, actor: Actor, db: Db):
    access(db, tenant_id, actor, lock=True, permission="exams.manage")
    sitting = get_sitting(db, tenant_id, sitting_id)
    existing = db.get(SittingCancellation, (tenant_id, sitting_id))
    if existing is not None:
        if existing.reason_code != body.reason_code:
            reject(409, "cancellation_conflict", "Sitting already has a different cancellation")
        response = cancellation_response(existing)
        db.commit()
        return response
    if sitting.opens_at <= db.scalar(select(func.clock_timestamp())):
        reject(409, "cancellation_closed", "Cancellation is only available before the sitting opens")
    row = SittingCancellation(
        tenant_id=tenant_id, sitting_id=sitting_id, reason_code=body.reason_code, created_by=actor.user_id
    )
    db.add(row)
    record(
        db,
        "exam.sitting_cancelled",
        actor=actor.user_id,
        tenant=tenant_id,
        subject=str(sitting_id),
        before={},
        after={},
    )
    db.flush()
    response = cancellation_response(row)
    db.commit()
    return response


@router.get("/exam-sittings/{sitting_id}/cancellation")
def cancellation(tenant_id: UUID, sitting_id: UUID, actor: Actor, db: Db):
    access(db, tenant_id, actor, permission="exams.manage")
    get_sitting(db, tenant_id, sitting_id)
    row = db.get(SittingCancellation, (tenant_id, sitting_id))
    if row is None:
        reject(404, "cancellation_not_found", "Cancellation not found")
    return cancellation_response(row)


class RegistrationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    candidate_user_id: UUID
    extra_minutes: Annotated[int, Field(strict=True, ge=0, le=240)] = 0
    accommodation_reason: Annotated[str | None, Field(min_length=3, max_length=500)] = None

    @model_validator(mode="after")
    def reason(self):
        if self.extra_minutes and (
            self.accommodation_reason is None or len(self.accommodation_reason.strip()) < 3
        ):
            raise ValueError("Extra time requires a recorded reason")
        if not self.extra_minutes and self.accommodation_reason is not None:
            raise ValueError("A reason is only accepted with extra time")
        return self


class RegistrationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registrations: Annotated[list[RegistrationBody], Field(min_length=1, max_length=50)]

    @model_validator(mode="after")
    def unique(self):
        for field in ("id", "candidate_user_id"):
            if len({getattr(row, field) for row in self.registrations}) != len(self.registrations):
                raise ValueError("Duplicate candidate or registration ID")
        return self


def sitting_response(row):
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "publication_id",
            "title",
            "opens_at",
            "closes_at",
            "display_timezone",
            "duration_minutes",
            "policy",
        )
    }


def registration_response(row):
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "sitting_id",
            "candidate_user_id",
            "extra_minutes",
            "allowed_minutes",
            "accommodation_reason",
        )
    }


def get_sitting(db, tenant, identity):
    sitting = db.get(ExamSitting, (tenant, identity))
    if sitting is None:
        reject(404, "sitting_not_found", "Sitting not found")
    return sitting


@router.put("/exam-sittings/{sitting_id}")
def schedule(tenant_id: UUID, sitting_id: UUID, body: SittingBody, actor: Actor, db: Db):
    access(db, tenant_id, actor, lock=True, permission="exams.manage")
    payload = body.model_dump()
    payload["opens_at"] = body.opens_at.astimezone(UTC)
    payload["closes_at"] = body.closes_at.astimezone(UTC)
    existing = db.get(ExamSitting, (tenant_id, sitting_id))
    if existing is not None:
        if any(getattr(existing, key) != value for key, value in payload.items()):
            reject(409, "sitting_conflict", "Sitting ID already contains a different schedule")
        response = sitting_response(existing)
        db.commit()
        return response
    publication = db.get(ExamPublication, (tenant_id, body.publication_id))
    if publication is None:
        reject(404, "exam_publication_not_found", "Exam publication not found")
    policy = publication.snapshot["policy"]
    minutes = policy.get("duration_minutes")
    if type(minutes) is not int or not 1 <= minutes <= 1440:
        reject(409, "sitting_policy_unavailable", "Publication timing policy is unavailable")
    try:
        check_window(body.opens_at, body.closes_at, minutes)
    except ValueError:
        reject(422, "sitting_window_too_short", "Sitting window does not fit the publication duration")
    if body.opens_at <= db.scalar(select(func.clock_timestamp())):
        reject(409, "sitting_already_open", "A new sitting must open in the future")
    row = ExamSitting(
        tenant_id=tenant_id,
        id=sitting_id,
        duration_minutes=minutes,
        policy=dict(policy),
        created_by=actor.user_id,
        **payload,
    )
    db.add(row)
    record(
        db,
        "exam.sitting_created",
        actor=actor.user_id,
        tenant=tenant_id,
        subject=str(sitting_id),
        before={},
        after={},
    )
    response = sitting_response(row)
    db.commit()
    return response


@router.get("/exam-sittings/{sitting_id}")
def detail(tenant_id: UUID, sitting_id: UUID, actor: Actor, db: Db):
    access(db, tenant_id, actor, permission="exams.manage")
    return sitting_response(get_sitting(db, tenant_id, sitting_id))


@router.get("/exam-sittings")
def listing(
    tenant_id: UUID,
    actor: Actor,
    db: Db,
    offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    access(db, tenant_id, actor, permission="exams.manage")
    return [
        sitting_response(row)
        for row in db.scalars(
            select(ExamSitting)
            .where(ExamSitting.tenant_id == tenant_id)
            .order_by(ExamSitting.opens_at, ExamSitting.id)
            .offset(offset)
            .limit(limit)
        )
    ]


def plan_registration_batch(db, tenant_id, sitting_id, body, actor):
    sitting = get_sitting(db, tenant_id, sitting_id)
    pending, result = [], []
    for candidate in body.registrations:
        existing = db.get(SittingRegistration, (tenant_id, candidate.id))
        expected = candidate.model_dump(exclude={"id"})
        if existing is not None:
            if existing.sitting_id != sitting_id or any(
                getattr(existing, key) != value for key, value in expected.items()
            ):
                reject(409, "registration_conflict", "Registration ID already contains different data")
            result.append(existing)
            continue
        duplicate = db.scalar(
            select(SittingRegistration.id).where(
                SittingRegistration.tenant_id == tenant_id,
                SittingRegistration.sitting_id == sitting_id,
                SittingRegistration.candidate_user_id == candidate.candidate_user_id,
            )
        )
        if duplicate is not None:
            reject(409, "registration_conflict", "Candidate is already registered")
        eligible = db.scalar(
            select(Membership.id)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.user_id == candidate.candidate_user_id,
                Membership.role == "candidate",
                Membership.status == "active",
                User.is_active.is_(True),
            )
        )
        if eligible is None:
            reject(409, "candidate_unavailable", "Candidate is not eligible in this institution")
        allowed = sitting.duration_minutes + candidate.extra_minutes
        try:
            check_window(sitting.opens_at, sitting.closes_at, allowed)
        except ValueError:
            reject(409, "accommodation_window_too_short", "Sitting window does not fit the accommodation")
        row = SittingRegistration(
            tenant_id=tenant_id,
            id=candidate.id,
            sitting_id=sitting_id,
            allowed_minutes=allowed,
            created_by=actor.user_id,
            **expected,
        )
        pending.append(row)
        result.append(row)
    if pending and db.get(SittingCancellation, (tenant_id, sitting_id)) is not None:
        reject(409, "sitting_cancelled", "Sitting is cancelled")
    if pending and sitting.opens_at <= db.scalar(select(func.clock_timestamp())):
        reject(409, "registration_closed", "New registrations close when the sitting opens")
    return pending, result


def persist_registration_batch(db, tenant_id, actor, pending, result):
    for row in pending:
        db.add(row)
        record(
            db,
            "exam.candidate_registered",
            actor=actor.user_id,
            tenant=tenant_id,
            subject=str(row.id),
            before={},
            after={},
        )
    response = [registration_response(row) for row in result]
    db.commit()
    return response


@router.post("/exam-sittings/{sitting_id}/registrations")
def register(tenant_id: UUID, sitting_id: UUID, body: RegistrationBatch, actor: Actor, db: Db):
    access(db, tenant_id, actor, lock=True, permission="exams.manage")
    pending, result = plan_registration_batch(db, tenant_id, sitting_id, body, actor)
    return persist_registration_batch(db, tenant_id, actor, pending, result)


@router.get("/exam-sittings/{sitting_id}/registrations")
def registrations(
    tenant_id: UUID,
    sitting_id: UUID,
    actor: Actor,
    db: Db,
    offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    access(db, tenant_id, actor, permission="exams.manage")
    get_sitting(db, tenant_id, sitting_id)
    return [
        registration_response(row)
        for row in db.scalars(
            select(SittingRegistration)
            .where(SittingRegistration.tenant_id == tenant_id, SittingRegistration.sitting_id == sitting_id)
            .order_by(SittingRegistration.id)
            .offset(offset)
            .limit(limit)
        )
    ]


@router.get("/exam-sittings/{sitting_id}/eligibility")
def eligibility(tenant_id: UUID, sitting_id: UUID, actor: Actor, db: Db):
    tenant_membership(db, tenant_id, actor, permission="exams.take")
    sitting = get_sitting(db, tenant_id, sitting_id)
    registration = db.scalar(
        select(SittingRegistration).where(
            SittingRegistration.tenant_id == tenant_id,
            SittingRegistration.sitting_id == sitting_id,
            SittingRegistration.candidate_user_id == actor.user_id,
        )
    )
    if registration is None:
        reject(404, "sitting_not_found", "Sitting not found")
    effective = registration_status(db, registration)
    return candidate_eligibility(
        sitting,
        registration,
        effective,
        db.scalar(select(func.clock_timestamp())),
        cancelled=db.get(SittingCancellation, (tenant_id, sitting_id)) is not None,
    )


def candidate_eligibility(sitting, registration, effective, now, *, cancelled=False):
    readiness = start_readiness(
        sitting.opens_at,
        sitting.closes_at,
        now,
        effective["allowed_minutes"],
    )
    if cancelled:
        readiness.update(window_state="cancelled", can_start=False, deadline_if_started_now=None)
    if effective["status"] == "withdrawn" and readiness["window_state"] != "cancelled":
        readiness.update(window_state="withdrawn", can_start=False, deadline_if_started_now=None)
    return {
        "sitting_id": sitting.id,
        "publication_id": sitting.publication_id,
        "title": sitting.title,
        "registration_id": registration.id,
        "allowed_minutes": effective["allowed_minutes"],
        "opens_at": sitting.opens_at,
        "closes_at": sitting.closes_at,
        "display_timezone": sitting.display_timezone,
        **readiness,
    }


class RegistrationChangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: Annotated[int, Field(strict=True, ge=1, lt=1000000)]
    action: Literal["amend_accommodation", "withdraw"]
    extra_minutes: Annotated[int | None, Field(strict=True, ge=0, le=240)] = None
    reason: Annotated[str, Field(min_length=3, max_length=500)]

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value):
        value = value.strip()
        if len(value) < 3:
            raise ValueError("A recorded reason is required")
        return value

    @model_validator(mode="after")
    def allowance(self):
        if (self.action == "withdraw") != (self.extra_minutes is None):
            raise ValueError("Only an accommodation amendment requires extra_minutes")
        return self


def latest_registration_change(db, registration):
    return db.scalar(
        select(RegistrationChange)
        .where(
            RegistrationChange.tenant_id == registration.tenant_id,
            RegistrationChange.registration_id == registration.id,
        )
        .order_by(RegistrationChange.revision.desc())
        .limit(1)
    )


def registration_status(db, registration):
    latest = latest_registration_change(db, registration)
    return {
        "registration_id": registration.id,
        "revision": latest.revision if latest else 1,
        "status": "withdrawn" if latest and latest.action == "withdraw" else "active",
        "extra_minutes": latest.extra_minutes if latest else registration.extra_minutes,
        "allowed_minutes": latest.allowed_minutes if latest else registration.allowed_minutes,
    }


def get_registration(db, tenant_id, sitting_id, registration_id):
    get_sitting(db, tenant_id, sitting_id)
    row = db.get(SittingRegistration, (tenant_id, registration_id))
    if row is None or row.sitting_id != sitting_id:
        reject(404, "registration_not_found", "Registration not found")
    return row


def change_response(db, row):
    reason = db.get(RegistrationChangeReason, (row.tenant_id, row.id))
    return {
        "id": row.id,
        "registration_id": row.registration_id,
        "revision": row.revision,
        "action": row.action,
        "extra_minutes": row.extra_minutes,
        "allowed_minutes": row.allowed_minutes,
        "reason": reason.reason,
        "created_at": row.created_at,
    }


@router.get("/exam-sittings/{sitting_id}/registrations/{registration_id}/status")
def current_registration(tenant_id: UUID, sitting_id: UUID, registration_id: UUID, actor: Actor, db: Db):
    access(db, tenant_id, actor, permission="exams.manage")
    return registration_status(db, get_registration(db, tenant_id, sitting_id, registration_id))


@router.get("/exam-sittings/{sitting_id}/registrations/{registration_id}/changes")
def registration_history(
    tenant_id: UUID,
    sitting_id: UUID,
    registration_id: UUID,
    actor: Actor,
    db: Db,
    offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    access(db, tenant_id, actor, permission="exams.manage")
    get_registration(db, tenant_id, sitting_id, registration_id)
    return [
        change_response(db, row)
        for row in db.scalars(
            select(RegistrationChange)
            .where(
                RegistrationChange.tenant_id == tenant_id,
                RegistrationChange.registration_id == registration_id,
            )
            .order_by(RegistrationChange.revision)
            .offset(offset)
            .limit(limit)
        )
    ]


@router.put("/exam-sittings/{sitting_id}/registrations/{registration_id}/changes/{change_id}")
def change_registration(
    tenant_id: UUID,
    sitting_id: UUID,
    registration_id: UUID,
    change_id: UUID,
    body: RegistrationChangeBody,
    actor: Actor,
    db: Db,
):
    access(db, tenant_id, actor, lock=True, permission="exams.manage")
    registration = get_registration(db, tenant_id, sitting_id, registration_id)
    existing = db.get(RegistrationChange, (tenant_id, change_id))
    if existing is not None:
        reason = db.get(RegistrationChangeReason, (tenant_id, change_id))
        if (
            existing.registration_id != registration_id
            or existing.action != body.action
            or existing.revision != body.expected_revision + 1
            or reason.reason != body.reason
            or (body.action == "amend_accommodation" and existing.extra_minutes != body.extra_minutes)
        ):
            reject(409, "registration_change_conflict", "Change ID already contains different data")
        response = change_response(db, existing)
        db.commit()
        return response
    sitting = get_sitting(db, tenant_id, sitting_id)
    current = registration_status(db, registration)
    if current["revision"] != body.expected_revision:
        reject(409, "registration_revision_conflict", "Registration revision is stale")
    if current["status"] == "withdrawn":
        reject(409, "registration_withdrawn", "Registration is withdrawn")
    if db.get(SittingCancellation, (tenant_id, sitting_id)) is not None:
        reject(409, "sitting_cancelled", "Sitting is cancelled")
    if sitting.opens_at <= db.scalar(select(func.clock_timestamp())):
        reject(409, "registration_changes_closed", "Registration changes close when the sitting opens")
    extra = current["extra_minutes"]
    if body.action == "amend_accommodation":
        eligible = db.scalar(
            select(Membership.id)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.user_id == registration.candidate_user_id,
                Membership.role == "candidate",
                Membership.status == "active",
                User.is_active.is_(True),
            )
        )
        if eligible is None:
            reject(409, "candidate_unavailable", "Candidate is not eligible in this institution")
        extra = body.extra_minutes
        if extra == current["extra_minutes"]:
            reject(409, "accommodation_unchanged", "Accommodation allowance is unchanged")
    allowed = sitting.duration_minutes + extra
    try:
        check_window(sitting.opens_at, sitting.closes_at, allowed)
    except ValueError:
        reject(409, "accommodation_window_too_short", "Sitting window does not fit the accommodation")
    row = RegistrationChange(
        tenant_id=tenant_id,
        id=change_id,
        registration_id=registration_id,
        sitting_id=sitting_id,
        candidate_user_id=registration.candidate_user_id,
        revision=current["revision"] + 1,
        action=body.action,
        extra_minutes=extra,
        allowed_minutes=allowed,
        created_by=actor.user_id,
    )
    db.add(row)
    db.flush()
    db.add(RegistrationChangeReason(tenant_id=tenant_id, change_id=change_id, reason=body.reason))
    record(
        db,
        "exam.registration_" + ("withdrawn" if body.action == "withdraw" else "accommodation_changed"),
        actor=actor.user_id,
        tenant=tenant_id,
        subject=str(registration_id),
        before={},
        after={},
    )
    db.flush()
    response = change_response(db, row)
    db.commit()
    return response
