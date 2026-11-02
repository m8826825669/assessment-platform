from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from pydantic import BaseModel

from app.audit.api import router as audit_router
from app.config import Settings
from app.db.database import Database
from app.errors import ERROR_STATUSES, Problem, install
from app.identity.api import router


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
        version="0.4.0",
        lifespan=lifespan,
        responses={
            code: {"model": Problem, "description": "Structured API problem"} for code in ERROR_STATUSES
        },
    )
    app.state.database = database
    app.state.settings = resolved_settings
    app.include_router(router)

    app.include_router(audit_router)
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
        is_ready = all(value == "ok" for value in dependencies.values())
        response.status_code = 200 if is_ready else 503
        response.headers["Cache-Control"] = "no-store"
        return Readiness(
            status="ready" if is_ready else "not_ready",
            service="assessment-api",
            dependencies=dependencies,
        )

    return app
