from datetime import datetime
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.db.models import AuditRecord
from app.identity.api import Actor, Db
from app.identity.service import reject, tenant_membership

router = APIRouter(prefix="/api/v1", tags=["audit"])


class AuditResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    actor_user_id: UUID | None
    actor_kind: str
    actor_reference: str | None
    action: str
    subject_id: UUID | None
    before_state: dict
    after_state: dict
    request_id: UUID | None
    created_at: datetime
    model_config = {"from_attributes": True}


@router.get("/tenants/{tenant_id}/audit", response_model=list[AuditResponse])
def audit_history(tenant_id: UUID, actor: Actor, db: Db, offset: int = 0, limit: int = 100):
    tenant_membership(db, tenant_id, actor, "audit.read")
    if offset < 0 or not 1 <= limit <= 200:
        reject(422, "invalid_pagination", "Use offset >= 0 and limit between 1 and 200")
    return list(
        db.scalars(
            select(AuditRecord)
            .where(AuditRecord.tenant_id == tenant_id)
            .order_by(AuditRecord.created_at.desc(), AuditRecord.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
