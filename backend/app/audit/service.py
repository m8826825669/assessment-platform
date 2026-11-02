import re
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AuditRecord, OutboxDelivery, OutboxEvent
from app.identity.permissions import ROLE_PERMISSIONS
from app.request_context import request_id

EMPTY_ACTIONS = frozenset(
    {
        "login.succeeded",
        "login.failed",
        "login.throttled",
        "session.revoked",
        "password.changed",
        "password.failed",
        "password.throttled",
        "operator.user_created",
        "operator.institution_created",
        "operator.password_reset",
    }
)
MEMBERSHIP_ACTIONS = frozenset({"membership.created", "membership.changed", "operator.membership_created"})
REQUEUE_ACTION = "operator.outbox_requeued"
QUESTION_ACTIONS = frozenset({"question.created", "question.revised"})
ACTIONS = EMPTY_ACTIONS | MEMBERSHIP_ACTIONS | QUESTION_ACTIONS | {REQUEUE_ACTION}
REASONS = frozenset({"handler_fixed", "transient_failure_reviewed"})


def clean_state(action: str, state: dict | None) -> dict:
    if action not in ACTIONS:
        raise ValueError("Unregistered audit action")
    state = dict(state or {})
    allowed = {"role", "status", "user_id"} if action in MEMBERSHIP_ACTIONS else set()
    if action in QUESTION_ACTIONS:
        allowed = {"version_id", "revision", "content_hash"}
    if action == REQUEUE_ACTION:
        allowed = {"status", "attempts", "reason_code"}
    if state.keys() - allowed:
        raise ValueError("Unapproved audit state field")
    for key, value in state.items():
        if key == "version_id":
            state[key] = str(UUID(str(value)))
        if key == "revision" and (type(value) is not int or not 1 <= value <= 2147483647):
            raise ValueError("Invalid audited revision")
        if key == "content_hash" and (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)):
            raise ValueError("Invalid audited content hash")
        if key == "role" and value not in ROLE_PERMISSIONS:
            raise ValueError("Invalid audited role")
        if key == "status":
            choices = {"pending", "dead"} if action == REQUEUE_ACTION else {"active", "suspended"}
            if value not in choices:
                raise ValueError("Invalid audited status")
        if key == "user_id":
            state[key] = str(UUID(str(value)))
        if key == "attempts" and (type(value) is not int or not 0 <= value <= 20):
            raise ValueError("Invalid audited attempt count")
        if key == "reason_code" and value not in REASONS:
            raise ValueError("Invalid audited reason")
    return state


def membership_state(member) -> dict:
    return {"user_id": str(member.user_id), "role": member.role, "status": member.status or "active"}


def record(
    session: Session,
    action: str,
    actor: UUID | None = None,
    tenant: UUID | None = None,
    subject: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> UUID:
    before, after = clean_state(action, before), clean_state(action, after)
    subject_id = UUID(subject) if subject else None
    audit_id, event_id = uuid4(), uuid4()
    candidate = request_id.get() or session.info.get("request_id")
    correlation = candidate if isinstance(candidate, UUID) else None
    operator = action.startswith("operator.")
    reference = session.scalar(select(func.current_user())) if operator else str(actor) if actor else None
    scope = str(tenant) if tenant else "global"
    session.add(
        AuditRecord(
            id=audit_id,
            tenant_id=tenant,
            scope_key=scope,
            actor_user_id=actor,
            actor_kind="operator" if operator else "user" if actor else "anonymous",
            actor_reference=reference,
            action=action,
            subject_id=subject_id,
            before_state=before,
            after_state=after,
            request_id=correlation,
        )
    )
    session.flush()  # Flush pending business changes too; do not commit here.
    payload = {
        "schema_version": 1,
        "event_id": str(event_id),
        "audit_id": str(audit_id),
        "tenant_id": str(tenant) if tenant else None,
        "action": action,
        "subject_id": str(subject_id) if subject_id else None,
        "request_id": str(correlation) if correlation else None,
        "before": before,
        "after": after,
    }
    session.add(
        OutboxEvent(
            id=event_id,
            audit_id=audit_id,
            tenant_id=tenant,
            scope_key=scope,
            event_type="audit.recorded.v1",
            payload=payload,
        )
    )
    session.flush()
    session.add(OutboxDelivery(event_id=event_id))
    session.flush()
    return event_id
