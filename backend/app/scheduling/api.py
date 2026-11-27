"""SCH-01/TEN-01 frozen sittings and atomic candidate registration."""

from datetime import UTC
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select

from app.audit.service import record
from app.db.models import ExamPublication, ExamSitting, Membership, SittingRegistration, User
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


@router.post("/exam-sittings/{sitting_id}/registrations")
def register(tenant_id: UUID, sitting_id: UUID, body: RegistrationBatch, actor: Actor, db: Db):
    access(db, tenant_id, actor, lock=True, permission="exams.manage")
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
    if pending and sitting.opens_at <= db.scalar(select(func.clock_timestamp())):
        reject(409, "registration_closed", "New registrations close when the sitting opens")
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
    return {
        "sitting_id": sitting.id,
        "publication_id": sitting.publication_id,
        "title": sitting.title,
        "registration_id": registration.id,
        "allowed_minutes": registration.allowed_minutes,
        "opens_at": sitting.opens_at,
        "closes_at": sitting.closes_at,
        "display_timezone": sitting.display_timezone,
        **start_readiness(
            sitting.opens_at,
            sitting.closes_at,
            db.scalar(select(func.clock_timestamp())),
            registration.allowed_minutes,
        ),
    }
