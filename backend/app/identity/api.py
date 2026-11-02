from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Institution, Membership
from app.identity import service
from app.identity.permissions import ROLE_PERMISSIONS

Role = Literal["admin", "coordinator", "author", "reviewer", "invigilator", "examiner", "candidate"]
MemberStatus = Literal["active", "suspended"]
router = APIRouter(prefix="/api/v1")
bearer = HTTPBearer(auto_error=False)


def get_db(request: Request):
    with request.app.state.database.sessions() as session:
        session.info["request_id"] = getattr(request.state, "request_id", None)
        yield session


Db = Annotated[Session, Depends(get_db)]


def get_principal(db: Db, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if credentials is None:
        service.reject(401, "invalid_session", "Authentication required")
    return service.authenticate(db, credentials.credentials)


Actor = Annotated[service.Principal, Depends(get_principal)]


class InputModel(BaseModel):
    model_config = {"extra": "forbid"}


class LoginBody(InputModel):
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if value.count("@") != 1 or any(character.isspace() for character in value):
            raise ValueError("A valid email address is required")
        return value


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MeResponse(BaseModel):
    user_id: UUID
    email: str
    display_name: str


class PasswordBody(InputModel):
    current_password: SecretStr = Field(min_length=1, max_length=1024)
    new_password: SecretStr = Field(min_length=15, max_length=1024)


class AccessResponse(BaseModel):
    tenant_id: UUID
    membership_id: UUID
    role: Role
    permissions: list[str]


class MembershipResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    user_id: UUID
    role: Role
    status: MemberStatus

    model_config = {"from_attributes": True}


class MembershipCreate(InputModel):
    user_id: UUID
    role: Role = "candidate"


class MembershipUpdate(InputModel):
    role: Role | None = None
    status: MemberStatus | None = None

    @model_validator(mode="after")
    def require_change(self):
        if self.role is None and self.status is None:
            raise ValueError("Specify role or status")
        return self


@router.post("/auth/login", response_model=TokenResponse, tags=["identity"])
def login(body: LoginBody, request: Request, db: Db) -> TokenResponse:
    token, lifetime = service.login(
        db,
        request.app.state.settings,
        body.email,
        body.password.get_secret_value(),
        request.client.host if request.client else "unknown",
    )
    return TokenResponse(access_token=token, expires_in=lifetime)


@router.get("/auth/me", response_model=MeResponse, tags=["identity"])
def me(actor: Actor) -> MeResponse:
    return MeResponse(user_id=actor.user_id, email=actor.email, display_name=actor.display_name)


@router.post("/auth/logout", status_code=204, tags=["identity"])
def logout(actor: Actor, db: Db) -> Response:
    service.logout(db, actor)
    return Response(status_code=204)


@router.post("/auth/change-password", status_code=204, tags=["identity"])
def change_password(body: PasswordBody, request: Request, actor: Actor, db: Db) -> Response:
    service.change_password(
        db,
        request.app.state.settings,
        actor,
        body.current_password.get_secret_value(),
        body.new_password.get_secret_value(),
    )
    return Response(status_code=204)


@router.get("/tenants/{tenant_id}/access", response_model=AccessResponse, tags=["institutions"])
def access(tenant_id: UUID, actor: Actor, db: Db) -> AccessResponse:
    member = service.tenant_membership(db, tenant_id, actor)
    return AccessResponse(
        tenant_id=tenant_id,
        membership_id=member.id,
        role=member.role,
        permissions=sorted(ROLE_PERMISSIONS[member.role]),
    )


@router.get(
    "/tenants/{tenant_id}/memberships", response_model=list[MembershipResponse], tags=["institutions"]
)
def list_memberships(tenant_id: UUID, actor: Actor, db: Db, offset: int = 0, limit: int = 100):
    service.tenant_membership(db, tenant_id, actor, "memberships.manage")
    if offset < 0 or not 1 <= limit <= 200:
        service.reject(422, "invalid_pagination", "Use offset >= 0 and limit between 1 and 200")
    return list(
        db.scalars(
            select(Membership)
            .where(Membership.tenant_id == tenant_id)
            .order_by(Membership.created_at, Membership.id)
            .offset(offset)
            .limit(limit)
        )
    )


@router.post(
    "/tenants/{tenant_id}/memberships",
    response_model=MembershipResponse,
    status_code=201,
    tags=["institutions"],
)
def create_membership(tenant_id: UUID, body: MembershipCreate, actor: Actor, db: Db):
    service.tenant_membership(db, tenant_id, actor, "memberships.manage", lock=True)
    member = Membership(tenant_id=tenant_id, user_id=body.user_id, role=body.role)
    db.add(member)
    try:
        db.flush()
        service.security_event(
            db,
            "membership.created",
            actor.user_id,
            tenant_id,
            str(member.id),
            after=service.membership_state(member),
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        service.reject(409, "membership_conflict", "Cannot create membership for this user")
    return member


@router.patch(
    "/tenants/{tenant_id}/memberships/{membership_id}",
    response_model=MembershipResponse,
    tags=["institutions"],
)
def update_membership(tenant_id: UUID, membership_id: UUID, body: MembershipUpdate, actor: Actor, db: Db):
    return service.update_membership(db, tenant_id, actor, membership_id, body.role, body.status)


class MyMembershipResponse(BaseModel):
    tenant_id: UUID
    institution_name: str
    role: Role


@router.get("/auth/institutions", response_model=list[MyMembershipResponse], tags=["identity"])
def my_institutions(actor: Actor, db: Db):
    db.execute(text("SELECT set_config('app.tenant_id', '', true)"))
    db.execute(text("SELECT set_config('app.actor_user_id', :actor, true)"), {"actor": str(actor.user_id)})
    rows = db.execute(
        select(Membership.tenant_id, Institution.name, Membership.role)
        .join(Institution, Institution.id == Membership.tenant_id)
        .where(
            Membership.user_id == actor.user_id, Membership.status == "active", Institution.status == "active"
        )
        .order_by(Institution.name, Membership.tenant_id)
        .limit(200)
    )
    return [
        MyMembershipResponse(tenant_id=tenant, institution_name=name, role=role)
        for tenant, name, role in rows
    ]
