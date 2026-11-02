"""RFC 9457 problem details. No request payloads or exception strings are echoed."""

import logging
from http import HTTPStatus
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from app.request_context import request_id

LOGGER = logging.getLogger("assessment.errors")
MESSAGES = {
    "invalid_credentials": "Invalid email or password",
    "invalid_session": "Authentication required",
    "login_throttled": "Too many attempts; try again later",
    "password_throttled": "Too many attempts; try again later",
    "invalid_current_password": "Current password is incorrect",
    "institution_not_found": "Institution not found",
    "permission_denied": "Permission denied",
    "membership_not_found": "Membership not found",
    "last_admin": "At least one active institution administrator is required",
    "membership_conflict": "Cannot create membership for this user",
    "invalid_pagination": "Use offset >= 0 and limit between 1 and 200",
}
ERROR_STATUSES = (400, 401, 403, 404, 405, 409, 422, 429, 500, 503)


class FieldProblem(BaseModel):
    location: list[str | int]
    code: str
    message: str


class Problem(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
    request_id: UUID
    errors: list[FieldProblem] = Field(default_factory=list)


def problem(
    request: Request,
    status: int,
    code: str,
    message: str,
    headers: dict | None = None,
    fields: list[FieldProblem] | None = None,
) -> JSONResponse:
    correlation = getattr(request.state, "request_id", None) or uuid4()
    body = Problem(
        type="urn:assessment:error:" + code,
        title=HTTPStatus(status).phrase,
        status=status,
        detail=message,
        instance="urn:assessment:request:" + str(correlation),
        code=code,
        request_id=correlation,
        errors=fields or [],
    )
    response_headers = dict(headers or {})
    response_headers.update({"Cache-Control": "no-store", "X-Request-ID": str(correlation)})
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content=body.model_dump(mode="json"),
        headers=response_headers,
    )


def install(app):
    @app.middleware("http")
    async def correlate(request, call_next):
        correlation = uuid4()  # A caller supplied header is never an identity or trusted correlation value.
        request.state.request_id = correlation
        context_token = request_id.set(correlation)
        try:
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Request-ID"] = str(correlation)
            return response
        finally:
            request_id.reset(context_token)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        candidate = exc.detail.get("code") if isinstance(exc.detail, dict) else None
        code = candidate if candidate in MESSAGES else "http_" + str(exc.status_code)
        message = MESSAGES.get(code, HTTPStatus(exc.status_code).phrase)
        headers = dict(exc.headers or {})
        if exc.status_code == 429:
            headers.setdefault("Retry-After", str(request.app.state.settings.login_window_seconds))
        return problem(request, exc.status_code, code, message, headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        fields = [
            FieldProblem(
                location=list(error["loc"]),
                code=error["type"],
                message="Field required" if error["type"] == "missing" else "Invalid value",
            )
            for error in exc.errors()
        ]
        return problem(request, 422, "validation_error", "Request validation failed", fields=fields)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        LOGGER.warning("database_not_ready request_id=%s", getattr(request.state, "request_id", None))
        return problem(
            request, 503, "database_not_ready", "Database is unavailable or runtime configuration is unsafe"
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        # Exception messages and tracebacks can contain passwords or SQL parameters.
        LOGGER.error(
            "internal_error request_id=%s exception_type=%s",
            getattr(request.state, "request_id", None),
            type(exc).__name__,
        )
        return problem(request, 500, "internal_error", "An unexpected server error occurred")

    def openapi():
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
            for path in schema["paths"].values():
                for operation in path.values():
                    if not isinstance(operation, dict):
                        continue
                    for response in operation.get("responses", {}).values():
                        content = response.get("content", {})
                        declared = content.get("application/json", {})
                        if declared.get("schema", {}).get("$ref", "").endswith("/Problem"):
                            response["content"] = {"application/problem+json": declared}
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi
