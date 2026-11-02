from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from pydantic import BaseModel

from app.audit.api import router as audit_router
from app.config import Settings
from app.db.database import Database
from app.errors import ERROR_STATUSES, Problem, install
from app.identity.api import router
from app.media.adapters import Gateway
from app.media.api import router as media_router
from app.question_bank.api import router as questions_router
from app.question_bank.review_api import router as review_router
from app.question_bank.taxonomy_api import router as taxonomy_router
from app.question_imports.api import router as imports_router


class Liveness(BaseModel):
    status: str
    service: str


class Readiness(BaseModel):
    status: str
    service: str
    dependencies: dict[str, str]


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings if settings is not None else Settings()
    database = Database(resolved_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        yield
        database.close()

    app = FastAPI(
        title="Institutional Assessment API",
        version="0.11.0",
        lifespan=lifespan,
        responses={
            code: {"model": Problem, "description": "Structured API problem"} for code in ERROR_STATUSES
        },
    )
    app.state.database = database
    app.state.settings = resolved_settings
    app.state.media = Gateway(resolved_settings) if resolved_settings.media_enabled else None
    app.include_router(router)

    app.include_router(audit_router)
    app.include_router(questions_router)
    app.include_router(review_router)
    app.include_router(taxonomy_router)
    app.include_router(media_router)
    app.include_router(imports_router)
    install(app)

    @app.get("/api/v1/health", response_model=Liveness, tags=["operations"])
    def health(response: Response) -> Liveness:
        response.headers["Cache-Control"] = "no-store"
        return Liveness(status="ok", service="assessment-api")

    @app.get(
        "/api/v1/ready",
        response_model=Readiness,
        tags=["operations"],
        responses={503: {"model": Readiness, "description": "Dependency readiness report"}},
    )
    def ready(response: Response) -> Readiness:
        dependencies = database.readiness()
        if app.state.media is not None:
            dependencies.update(app.state.media.ready())
        is_ready = all(value == "ok" for value in dependencies.values())
        response.status_code = 200 if is_ready else 503
        response.headers["Cache-Control"] = "no-store"
        return Readiness(
            status="ready" if is_ready else "not_ready",
            service="assessment-api",
            dependencies=dependencies,
        )

    return app
