"""Institution taxonomy catalogue; candidates do not have catalogue access."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.identity.api import Actor, Db
from app.question_bank import service, taxonomy
from app.question_bank.api import Limit, Offset

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/taxonomy", tags=["question taxonomy"])


class TermResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    kind: taxonomy.Kind
    code: str
    label: str
    parent_id: UUID | None
    state: Literal["active", "retired"]
    revision: int
    created_by: UUID
    created_at: datetime


@router.post("", response_model=TermResponse, status_code=201)
def create(tenant_id: UUID, body: taxonomy.TermCreate, actor: Actor, db: Db):
    return taxonomy.create_term(db, tenant_id, actor, body)


@router.get("", response_model=list[TermResponse])
def catalogue(
    tenant_id: UUID,
    actor: Actor,
    db: Db,
    kind: taxonomy.Kind | None = None,
    state: Literal["active", "retired"] | None = "active",
    offset: Offset = 0,
    limit: Limit = 100,
):
    return taxonomy.catalogue(db, tenant_id, actor, kind, state, offset, limit)


@router.get("/{term_id}", response_model=TermResponse)
def detail(tenant_id: UUID, term_id: UUID, actor: Actor, db: Db):
    service.authority(db, tenant_id, actor, permission="taxonomy.read")
    return taxonomy.get_term(db, tenant_id, term_id)


@router.patch("/{term_id}", response_model=TermResponse)
def update(tenant_id: UUID, term_id: UUID, body: taxonomy.TermUpdate, actor: Actor, db: Db):
    return taxonomy.update_term(db, tenant_id, actor, term_id, body)
