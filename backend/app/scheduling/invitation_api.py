"""SCH-01/TEN-01 candidate invitation inbox and immutable acknowledgement."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, func, select

from app.audit.service import record
from app.db.models import (
    ExamSitting,
    RegistrationAcceptance,
    RegistrationChange,
    SittingCancellation,
    SittingRegistration,
)
from app.identity.api import Actor, Db
from app.identity.service import reject
from app.question_bank.review import access
from app.scheduling.api import candidate_eligibility, get_registration, get_sitting, registration_status

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}", tags=["exam invitations"])


class AcceptanceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


def acceptance_response(row):
    return {
        "registration_id": row.registration_id,
        "sitting_id": row.sitting_id,
        "registration_revision": row.registration_revision,
        "accepted_at": row.accepted_at,
    }


def own_registration(db, tenant_id, registration_id, actor):
    row = db.scalar(
        select(SittingRegistration).where(
            SittingRegistration.tenant_id == tenant_id,
            SittingRegistration.id == registration_id,
            SittingRegistration.candidate_user_id == actor.user_id,
        )
    )
    if row is None:
        reject(404, "invitation_not_found", "Invitation not found")
    return row


def invitation_view(sitting, registration, effective, now, cancelled, accepted):
    return {
        **candidate_eligibility(sitting, registration, effective, now, cancelled=cancelled),
        "registration_revision": effective["revision"],
        "registration_status": effective["status"],
        "acceptance": acceptance_response(accepted) if accepted is not None else None,
        "can_accept": accepted is None
        and not cancelled
        and effective["status"] != "withdrawn"
        and now < sitting.closes_at,
    }


@router.get("/exam-invitations")
def inbox(
    tenant_id: UUID,
    actor: Actor,
    db: Db,
    offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
):
    access(db, tenant_id, actor, permission="exams.take")
    selected = db.execute(
        select(SittingRegistration, ExamSitting)
        .join(
            ExamSitting,
            and_(
                ExamSitting.tenant_id == SittingRegistration.tenant_id,
                ExamSitting.id == SittingRegistration.sitting_id,
            ),
        )
        .where(
            SittingRegistration.tenant_id == tenant_id, SittingRegistration.candidate_user_id == actor.user_id
        )
        .order_by(ExamSitting.opens_at, ExamSitting.id, SittingRegistration.id)
        .offset(offset)
        .limit(limit + 1)
    ).all()
    has_more = len(selected) > limit
    selected = selected[:limit]
    identities = [registration.id for registration, _ in selected]
    changes, cancellations, acceptances = {}, set(), {}
    if identities:
        latest = db.scalars(
            select(RegistrationChange)
            .where(
                RegistrationChange.tenant_id == tenant_id,
                RegistrationChange.registration_id.in_(identities),
                RegistrationChange.candidate_user_id == actor.user_id,
            )
            .distinct(RegistrationChange.registration_id)
            .order_by(RegistrationChange.registration_id, RegistrationChange.revision.desc())
        )
        changes = {row.registration_id: row for row in latest}
        cancellations = set(
            db.scalars(
                select(SittingCancellation.sitting_id).where(
                    SittingCancellation.tenant_id == tenant_id,
                    SittingCancellation.sitting_id.in_([sitting.id for _, sitting in selected]),
                )
            )
        )
        acceptances = {
            row.registration_id: row
            for row in db.scalars(
                select(RegistrationAcceptance).where(
                    RegistrationAcceptance.tenant_id == tenant_id,
                    RegistrationAcceptance.registration_id.in_(identities),
                    RegistrationAcceptance.candidate_user_id == actor.user_id,
                )
            )
        }
    now = db.scalar(select(func.clock_timestamp()))
    items = []
    for registration, sitting in selected:
        change = changes.get(registration.id)
        effective = {
            "revision": change.revision if change else 1,
            "status": "withdrawn" if change and change.action == "withdraw" else "active",
            "allowed_minutes": change.allowed_minutes if change else registration.allowed_minutes,
        }
        items.append(
            invitation_view(
                sitting,
                registration,
                effective,
                now,
                sitting.id in cancellations,
                acceptances.get(registration.id),
            )
        )
    return {"items": items, "offset": offset, "limit": limit, "has_more": has_more, "server_time": now}


@router.get("/exam-invitations/{registration_id}")
def detail(tenant_id: UUID, registration_id: UUID, actor: Actor, db: Db):
    access(db, tenant_id, actor, permission="exams.take")
    registration = own_registration(db, tenant_id, registration_id, actor)
    sitting = get_sitting(db, tenant_id, registration.sitting_id)
    return invitation_view(
        sitting,
        registration,
        registration_status(db, registration),
        db.scalar(select(func.clock_timestamp())),
        db.get(SittingCancellation, (tenant_id, sitting.id)) is not None,
        db.get(RegistrationAcceptance, (tenant_id, registration_id)),
    )


@router.post("/exam-invitations/{registration_id}/accept")
def accept(
    tenant_id: UUID,
    registration_id: UUID,
    actor: Actor,
    db: Db,
    body: Annotated[AcceptanceBody, Body()] = AcceptanceBody(),
):
    access(db, tenant_id, actor, lock=True, permission="exams.take")
    registration = own_registration(db, tenant_id, registration_id, actor)
    existing = db.get(RegistrationAcceptance, (tenant_id, registration_id))
    if existing is not None:
        response = acceptance_response(existing)
        db.commit()
        return response
    sitting = get_sitting(db, tenant_id, registration.sitting_id)
    effective = registration_status(db, registration)
    if (
        db.get(SittingCancellation, (tenant_id, sitting.id)) is not None
        or effective["status"] == "withdrawn"
        or db.scalar(select(func.clock_timestamp())) >= sitting.closes_at
    ):
        reject(409, "invitation_unavailable", "Invitation cannot be accepted")
    row = RegistrationAcceptance(
        tenant_id=tenant_id,
        registration_id=registration_id,
        sitting_id=sitting.id,
        candidate_user_id=actor.user_id,
        registration_revision=effective["revision"],
    )
    db.add(row)
    record(
        db,
        "exam.invitation_accepted",
        actor=actor.user_id,
        tenant=tenant_id,
        subject=str(registration_id),
        before={},
        after={},
    )
    db.flush()
    response = acceptance_response(row)
    db.commit()
    return response


@router.get("/exam-sittings/{sitting_id}/registrations/{registration_id}/acceptance")
def staff_receipt(tenant_id: UUID, sitting_id: UUID, registration_id: UUID, actor: Actor, db: Db):
    access(db, tenant_id, actor, permission="exams.manage")
    get_registration(db, tenant_id, sitting_id, registration_id)
    row = db.get(RegistrationAcceptance, (tenant_id, registration_id))
    if row is None:
        reject(404, "acceptance_not_found", "Acceptance not found")
    return acceptance_response(row)
