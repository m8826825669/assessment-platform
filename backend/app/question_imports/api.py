"""Bounded authenticated import documents. No client-controlled actor/tenant/approval fields."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool

from app.identity.api import Actor, Db
from app.identity.service import reject
from app.question_bank import service as questions
from app.question_imports import contracts, service

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/question-imports", tags=["question imports"])
BODY_DOCS = {
    "requestBody": {"required": True, "content": {"application/json": {"schema": contracts.request_schema()}}}
}


def preflight(db, tenant, actor):
    questions.authority(db, tenant, actor)
    db.rollback()  # No open authorization/read transaction while consuming the body stream.


async def document(request, tenant, actor, db):
    await run_in_threadpool(preflight, db, tenant, actor)
    if request.query_params:
        reject(422, "import_invalid", "Invalid import document")
    if (
        len(request.headers.getlist("content-type")) != 1
        or request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json"
    ):
        reject(415, "import_media_type", "Use an application/json import document")
    lengths = request.headers.getlist("content-length")
    if len(lengths) > 1 or (
        lengths
        and (len(lengths[0]) > 10 or not lengths[0].isdecimal() or int(lengths[0]) > contracts.MAX_BYTES)
    ):
        reject(413, "import_too_large", "Import document exceeds the size limit")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > contracts.MAX_BYTES:
            reject(413, "import_too_large", "Import document exceeds the size limit")
        data.extend(chunk)
    try:
        return contracts.parse(bytes(data))
    except ValidationError as error:
        raise RequestValidationError(contracts.safe_errors(error)) from None
    except (ValueError, UnicodeError, RecursionError):
        reject(422, "import_invalid", "Invalid import document")


class PreviewItem(BaseModel):
    index: int
    reference: str
    title: str
    taxonomy_count: int
    media_count: int
    preview: dict


class Preview(BaseModel):
    schema_version: Literal["assessment-question-import.v1"]
    valid: Literal[True]
    item_count: int
    items: list[PreviewItem]


class ImportedItem(BaseModel):
    reference: str
    question_id: UUID
    version_id: UUID


class Receipt(BaseModel):
    batch_id: UUID
    schema_version: Literal["assessment-question-import.v1"]
    created_at: datetime
    created_as: Literal["draft"]
    item_count: int
    items: list[ImportedItem]


@router.post("/preview", response_model=Preview, openapi_extra=BODY_DOCS)
async def preview(tenant_id: UUID, request: Request, actor: Actor, db: Db):
    body = await document(request, tenant_id, actor, db)
    return await run_in_threadpool(service.preview, db, tenant_id, actor, body)


@router.post(
    "",
    response_model=Receipt,
    status_code=201,
    responses={200: {"model": Receipt, "description": "Replay of a committed import"}},
    openapi_extra=BODY_DOCS,
)
async def commit(
    tenant_id: UUID,
    request: Request,
    response: Response,
    actor: Actor,
    db: Db,
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
):
    if len(request.headers.getlist("idempotency-key")) != 1:
        reject(422, "import_invalid", "Invalid import document")
    body = await document(request, tenant_id, actor, db)
    result, replay = await run_in_threadpool(service.commit, db, tenant_id, actor, body, key)
    response.status_code = 200 if replay else 201
    return result


@router.get("/{batch_id}", response_model=Receipt)
def receipt(tenant_id: UUID, batch_id: UUID, actor: Actor, db: Db):
    return service.get(db, tenant_id, actor, batch_id)
