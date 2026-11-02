from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.identity.api import Actor, Db
from app.identity.service import reject
from app.media import service
from app.media.adapters import MAX_BYTES
from app.media.contracts import Fence, Reserve

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/media", tags=["private authoring media"])


class PublicMedia(BaseModel):
    asset_id: UUID
    mime_type: str
    description: str
    width: int | None
    height: int | None


class AssetResponse(PublicMedia):
    filename: str
    state: str
    revision: int
    byte_length: int | None
    error_code: str | None


@router.post("", response_model=AssetResponse, status_code=201)
def reserve(tenant_id: UUID, body: Reserve, actor: Actor, db: Db):
    return service.reserve(db, tenant_id, actor, body)


@router.get("/{asset_id}", response_model=AssetResponse | PublicMedia)
def detail(tenant_id: UUID, asset_id: UUID, actor: Actor, db: Db):
    return service.details(db, tenant_id, actor, asset_id)


@router.put("/{asset_id}/content", response_model=AssetResponse)
async def upload(
    tenant_id: UUID,
    asset_id: UUID,
    request: Request,
    actor: Actor,
    db: Db,
    expected_revision: Annotated[int, Query(ge=1, le=2147483646)],
):
    # Authenticate and check ownership before reading the stream. Recheck after the mutation lock below.
    await run_in_threadpool(service.preflight, db, tenant_id, actor, asset_id)
    service.gateway(db)
    declared = request.headers.get("content-length")
    if declared is not None and (len(declared) > 10 or not declared.isdecimal() or int(declared) > MAX_BYTES):
        reject(413, "media_too_large", "Media exceeds the upload limit")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_BYTES:
            reject(413, "media_too_large", "Media exceeds the upload limit")
        data.extend(chunk)
    return await run_in_threadpool(
        service.upload,
        db,
        tenant_id,
        actor,
        asset_id,
        expected_revision,
        request.headers.get("content-type", ""),
        bytes(data),
    )


@router.post("/{asset_id}/scan", response_model=AssetResponse)
def scan(tenant_id: UUID, asset_id: UUID, body: Fence, actor: Actor, db: Db):
    return service.scan(db, tenant_id, actor, asset_id, body.expected_revision)


@router.get(
    "/{asset_id}/content",
    response_class=Response,
    responses={
        200: {"description": "Authorized clean image bytes", "content": {"image/png": {}, "image/jpeg": {}}}
    },
)
def download(tenant_id: UUID, asset_id: UUID, actor: Actor, db: Db):
    mime, data = service.download(db, tenant_id, actor, asset_id)
    return Response(
        data,
        media_type=mime,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "attachment; filename=authoring-image."
            + ("png" if mime == "image/png" else "jpg"),
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
