"""Staff-only saved-draft endpoints. No candidate/public or approval routes."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.identity.api import Actor, Db
from app.question_bank import service
from app.question_bank.contracts import Content, Label

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/questions", tags=["question bank"])
Offset = Annotated[int, Query(ge=0, le=1000000)]
Limit = Annotated[int, Query(ge=1, le=200)]


class QuestionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    title: Annotated[Label, Field(max_length=200)]
    content: Content


class QuestionRevise(QuestionCreate):
    expected_revision: Annotated[StrictInt, Field(ge=1, le=2147483646)]


class VersionMetadata(BaseModel):
    question_id: UUID
    version_id: UUID
    version_number: int
    title: str
    schema_version: str
    content_hash: str
    authored_by: UUID
    created_at: datetime
    state: Literal["draft"]


class QuestionDetail(VersionMetadata):
    tenant_id: UUID
    created_by: UUID
    revision: int
    content: dict


class QuestionPreview(BaseModel):
    question_id: UUID
    version_id: UUID
    content: dict


@router.post("", response_model=QuestionDetail, status_code=201)
def create(tenant_id: UUID, body: QuestionCreate, actor: Actor, db: Db):
    return service.create(db, tenant_id, actor, body.title, body.content)


@router.get("", response_model=list[VersionMetadata])
def listing(tenant_id: UUID, actor: Actor, db: Db, offset: Offset = 0, limit: Limit = 100):
    return service.listing(db, tenant_id, actor, offset, limit)


@router.get("/{question_id}", response_model=QuestionDetail)
def get(tenant_id: UUID, question_id: UUID, actor: Actor, db: Db):
    return service.get(db, tenant_id, actor, question_id)


@router.post("/{question_id}/versions", response_model=QuestionDetail, status_code=201)
def revise(tenant_id: UUID, question_id: UUID, body: QuestionRevise, actor: Actor, db: Db):
    return service.revise(db, tenant_id, actor, question_id, body.expected_revision, body.title, body.content)


@router.get("/{question_id}/versions", response_model=list[VersionMetadata])
def history(tenant_id: UUID, question_id: UUID, actor: Actor, db: Db, offset: Offset = 0, limit: Limit = 100):
    return service.history(db, tenant_id, actor, question_id, offset, limit)


@router.get("/{question_id}/versions/{version_id}", response_model=QuestionDetail)
def get_version(tenant_id: UUID, question_id: UUID, version_id: UUID, actor: Actor, db: Db):
    return service.get(db, tenant_id, actor, question_id, version_id)


@router.get("/{question_id}/preview", response_model=QuestionPreview)
def preview(tenant_id: UUID, question_id: UUID, actor: Actor, db: Db, version_id: UUID | None = None):
    return service.preview(db, tenant_id, actor, question_id, version_id)
