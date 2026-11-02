from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import case, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.audit.service import membership_state, record
from app.config import Settings
from app.db.models import AuthSession, Institution, LoginBucket, Membership, SecurityEvent, User
from app.identity.permissions import allowed
from app.identity.security import (
    HASHER,
    TOKEN_PATTERN,
    hash_password,
    new_token,
    token_digest,
    verify_password,
)


def reject(status: int, code: str, message: str) -> None:
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    raise HTTPException(status_code=status, detail={"code": code, "message": message}, headers=headers)


def security_event(
    session: Session,
    action: str,
    actor: UUID | None = None,
    tenant: UUID | None = None,
    subject: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    session.add(SecurityEvent(action=action, actor_user_id=actor, tenant_id=tenant, subject_id=subject))
    record(session, action, actor, tenant, subject, before, after)


def throttle(session: Session, identifiers: dict[str, int], settings: Settings, now: datetime) -> bool:
    exceeded = False
    # Consistent lock order for concurrent requests sharing account/IP buckets.
    keys = sorted((sha256(key.encode()).hexdigest(), limit) for key, limit in identifiers.items())
    for key, limit in keys:
        reset = LoginBucket.window_started_at <= now - timedelta(seconds=settings.login_window_seconds)
        statement = insert(LoginBucket).values(bucket_key=key, window_started_at=now, attempts=1)
        statement = statement.on_conflict_do_update(
            index_elements=[LoginBucket.bucket_key],
            set_={
                "attempts": case((reset, 1), else_=func.least(LoginBucket.attempts + 1, 1000000)),
                "window_started_at": case((reset, now), else_=LoginBucket.window_started_at),
            },
        ).returning(LoginBucket.attempts)
        exceeded |= session.scalar(statement) > limit
    return exceeded


def login(session: Session, settings: Settings, email: str, password: str, peer: str) -> tuple[str, int]:
    now = session.scalar(select(func.now()))
    if throttle(
        session,
        {f"login:email:{email}": settings.login_account_limit, f"login:ip:{peer}": settings.login_ip_limit},
        settings,
        now,
    ):
        security_event(session, "login.throttled")
        session.commit()
        reject(429, "login_throttled", "Too many attempts; try again later")
    # Release shared IP/account bucket locks before the expensive password verification.
    session.commit()
    user = session.scalar(select(User).where(User.email == email).with_for_update())
    valid = verify_password(user.password_hash if user else None, password)
    if not valid or user is None or not user.is_active:
        security_event(session, "login.failed")
        session.commit()  # Preserve throttling even though authentication failed.
        reject(401, "invalid_credentials", "Invalid email or password")
    if HASHER.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    token = new_token()
    session.add(
        AuthSession(
            user_id=user.id,
            token_hash=token_digest(token),
            created_at=now,
            expires_at=now + timedelta(seconds=settings.session_lifetime_seconds),
        )
    )
    security_event(session, "login.succeeded", user.id)
    session.commit()
    return token, settings.session_lifetime_seconds


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    session_id: UUID
    email: str
    display_name: str


def authenticate(session: Session, token: str) -> Principal:
    if not TOKEN_PATTERN.fullmatch(token):
        reject(401, "invalid_session", "Authentication required")
    row = session.execute(
        select(AuthSession, User)
        .join(User, User.id == AuthSession.user_id)
        .where(
            AuthSession.token_hash == token_digest(token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > func.now(),
            User.is_active.is_(True),
        )
    ).one_or_none()
    if row is None:
        reject(401, "invalid_session", "Authentication required")
    auth_session, user = row
    return Principal(user.id, auth_session.id, user.email, user.display_name)


def logout(session: Session, principal: Principal) -> None:
    session.execute(
        update(AuthSession).where(AuthSession.id == principal.session_id).values(revoked_at=func.now())
    )
    security_event(session, "session.revoked", principal.user_id)
    session.commit()


def change_password(
    session: Session, settings: Settings, principal: Principal, old_password: str, new_password: str
) -> None:
    now = session.scalar(select(func.now()))
    if throttle(session, {f"password:{principal.user_id}": settings.login_account_limit}, settings, now):
        security_event(session, "password.throttled", principal.user_id)
        session.commit()
        reject(429, "password_throttled", "Too many attempts; try again later")
    session.commit()
    user = session.scalar(select(User).where(User.id == principal.user_id).with_for_update())
    if not verify_password(user.password_hash, old_password):
        security_event(session, "password.failed", principal.user_id)
        session.commit()
        reject(400, "invalid_current_password", "Current password is incorrect")
    user.password_hash = hash_password(new_password)
    session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    security_event(session, "password.changed", user.id)
    session.commit()


def set_tenant_context(session: Session, tenant_id: UUID, principal: Principal) -> None:
    session.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_id)})
    session.execute(
        text("SELECT set_config('app.actor_user_id', :actor, true)"), {"actor": str(principal.user_id)}
    )


def tenant_membership(
    session: Session,
    tenant_id: UUID,
    principal: Principal,
    permission: str = "institution.read",
    *,
    lock: bool = False,
) -> Membership:
    set_tenant_context(session, tenant_id, principal)
    query = select(Institution).where(Institution.id == tenant_id, Institution.status == "active")
    if lock:
        query = query.with_for_update()
    institution = session.scalar(query)
    member = session.scalar(
        select(Membership)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.user_id == principal.user_id,
            Membership.status == "active",
        )
        .execution_options(populate_existing=True)
    )
    if institution is None or member is None:
        reject(404, "institution_not_found", "Institution not found")
    if not allowed(member.role, permission):
        reject(403, "permission_denied", "Permission denied")
    return member


def update_membership(
    session: Session,
    tenant_id: UUID,
    principal: Principal,
    membership_id: UUID,
    role: str | None,
    status: str | None,
) -> Membership:
    # Serialize all administrative membership mutations on the institution row.
    tenant_membership(session, tenant_id, principal, "memberships.manage", lock=True)
    target = session.scalar(
        select(Membership)
        .where(
            Membership.id == membership_id,
            Membership.tenant_id == tenant_id,
        )
        .execution_options(populate_existing=True)
    )
    if target is None:
        reject(404, "membership_not_found", "Membership not found")
    next_role, next_status = role or target.role, status or target.status
    if (
        target.role == "admin"
        and target.status == "active"
        and session.scalar(
            select(User.id).where(
                User.id == target.user_id, User.is_active.is_(True), User.password_hash.is_not(None)
            )
        )
        is not None
        and (next_role != "admin" or next_status != "active")
    ):
        admins = session.scalar(
            select(func.count())
            .select_from(Membership)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.role == "admin",
                Membership.status == "active",
                User.is_active.is_(True),
                User.password_hash.is_not(None),
            )
        )
        if admins <= 1:
            reject(409, "last_admin", "At least one active institution administrator is required")
    before = membership_state(target)
    target.role, target.status = next_role, next_status
    security_event(
        session,
        "membership.changed",
        principal.user_id,
        tenant_id,
        str(target.id),
        before=before,
        after=membership_state(target),
    )
    session.commit()
    return target
