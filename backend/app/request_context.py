from contextvars import ContextVar
from uuid import UUID

request_id: ContextVar[UUID | None] = ContextVar("assessment_request_id", default=None)
