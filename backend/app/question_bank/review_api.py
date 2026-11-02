"""Authenticated review and coordinator selection routes."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from app.identity.api import Actor, Db
from app.media.api import PublicMedia
from app.question_bank import review
from app.question_bank.api import Filters, Limit, Offset, QuestionDetail, TaxonSnapshot, VersionMetadata
from app.question_bank.contracts import Label

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}", tags=["question review"])


class ReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    action: Literal["submit", "return", "approve", "retire"]
    expected_revision: Annotated[StrictInt, Field(ge=1, le=2147483647)]
    expected_review_revision: Annotated[StrictInt, Field(ge=0, le=2147483646)]
    content_hash: Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
    reason: Label | None = None

    @model_validator(mode="after")
    def reason_policy(self):
        if (self.action in {"return", "retire"}) != (self.reason is not None):
            raise ValueError("Return/retire require a reason; other actions must omit it")
        return self


class Decision(BaseModel):
    id: UUID
    sequence: int
    action: str
    state: str
    actor_user_id: UUID
    reason: str | None
    created_at: datetime


class ReviewDetail(QuestionDetail):
    decisions: list[Decision]


class SelectedContent(BaseModel):
    taxonomy: list[TaxonSnapshot]
    media: list[PublicMedia]
    question_id: UUID
    version_id: UUID
    title: str
    content: dict


@router.get("/question-reviews", response_model=list[VersionMetadata])
def queue(tenant_id: UUID, actor: Actor, db: Db, filters: Filters, offset: Offset = 0, limit: Limit = 100):
    return review.queue(db, tenant_id, actor, offset, limit, filters)


@router.get("/question-reviews/{question_id}/versions/{version_id}", response_model=ReviewDetail)
def detail(
    tenant_id: UUID,
    question_id: UUID,
    version_id: UUID,
    actor: Actor,
    db: Db,
    offset: Offset = 0,
    limit: Limit = 100,
):
    return review.detail(db, tenant_id, actor, question_id, version_id, offset, limit)


@router.post("/question-reviews/{question_id}/versions/{version_id}", response_model=QuestionDetail)
def decide(tenant_id: UUID, question_id: UUID, version_id: UUID, body: ReviewBody, actor: Actor, db: Db):
    return review.decide(db, tenant_id, actor, question_id, version_id, body)


@router.get("/question-selections", response_model=list[SelectedContent])
def selections(
    tenant_id: UUID, actor: Actor, db: Db, filters: Filters, offset: Offset = 0, limit: Limit = 100
):
    return review.selections(db, tenant_id, actor, offset, limit, filters=filters)


@router.get("/question-selections/{version_id}", response_model=SelectedContent)
def selection(tenant_id: UUID, version_id: UUID, actor: Actor, db: Db):
    return review.selections(db, tenant_id, actor, 0, 1, version_id)[0]
