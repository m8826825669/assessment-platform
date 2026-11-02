"""Create and delete only random test databases, never migrate the input database."""

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from alembic import command
from alembic.config import Config


@pytest.fixture
def test_database(request):
    admin_url = os.environ.get("ASSESSMENT_TEST_ADMIN_URL")
    if not admin_url and request.config.getoption("--require-postgres"):
        pytest.fail("PostgreSQL is required; configure ASSESSMENT_TEST_ADMIN_URL")
    if not admin_url:
        pytest.skip("Set ASSESSMENT_TEST_ADMIN_URL to enable real PostgreSQL tests")
    if os.environ.get("ASSESSMENT_ALLOW_TEST_DATABASE_CREATION") != "1":
        pytest.fail("Set ASSESSMENT_ALLOW_TEST_DATABASE_CREATION=1 for disposable database creation")
    parsed = make_url(admin_url)
    if parsed.drivername != "postgresql+psycopg":
        pytest.fail("Test admin URL must use postgresql+psycopg")
    dbname = "assessment_test_" + uuid4().hex
    dbapi_url = parsed.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dbapi_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    url = parsed.set(database=dbname).render_as_string(hide_password=False)
    engine = create_engine(url, poolclass=NullPool, hide_parameters=True)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))

    def migrate(target="head"):
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, target)
        config.attributes.pop("connection", None)

    try:
        yield url, engine, config, migrate
    finally:
        engine.dispose()
        with psycopg.connect(dbapi_url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(dbname)))


@pytest.fixture
def security_database(test_database):
    """Use a real restricted PostgreSQL login role, never the migration owner, for API checks."""
    from contextlib import suppress
    from types import SimpleNamespace

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.db.models import Institution, Membership, User
    from app.db.provisioning import create_runtime
    from app.identity.security import hash_password
    from app.main import create_app

    url, admin_engine, _, migrate = test_database
    migrate()
    role = "assessment_test_runtime_" + uuid4().hex[:20]
    password = "Test runtime only " + uuid4().hex
    parsed = make_url(url)
    admin_dsn = parsed.set(drivername="postgresql").render_as_string(hide_password=False)
    try:
        with psycopg.connect(admin_dsn) as connection:
            create_runtime(connection, role, password)
    except psycopg.errors.InsufficientPrivilege:
        pytest.fail(
            "Security tests require CREATEROLE and ownership/grant authority on the disposable test database"
        )
    runtime_url = parsed.set(username=role, password=password).render_as_string(hide_password=False)
    runtime_engine = create_engine(runtime_url, poolclass=NullPool, hide_parameters=True)
    test_password = "Fixture password only 2026!"
    ids = {
        name: uuid4()
        for name in [
            "tenant_a",
            "tenant_b",
            "admin_a",
            "admin_b",
            "candidate",
            "outsider",
            "membership_a",
            "membership_b",
            "membership_candidate",
        ]
    }
    try:
        shared_hash = hash_password(test_password)
        with Session(admin_engine) as session, session.begin():
            for name in ["admin_a", "admin_b", "candidate", "outsider"]:
                session.add(
                    User(
                        id=ids[name],
                        email=f"{name}@example.test",
                        display_name=name,
                        password_hash=shared_hash,
                    )
                )
            session.flush()
            for suffix in ["a", "b"]:
                tenant_id = ids[f"tenant_{suffix}"]
                session.execute(
                    text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_id)}
                )
                session.add(
                    Institution(
                        id=tenant_id, slug=f"institution-{suffix}", name=f"Institution {suffix.upper()}"
                    )
                )
                session.flush()
                session.add(
                    Membership(
                        id=ids[f"membership_{suffix}"],
                        tenant_id=tenant_id,
                        user_id=ids[f"admin_{suffix}"],
                        role="admin",
                    )
                )
                if suffix == "a":
                    session.add(
                        Membership(
                            id=ids["membership_candidate"],
                            tenant_id=tenant_id,
                            user_id=ids["candidate"],
                            role="candidate",
                        )
                    )
                session.flush()
        settings = Settings(_env_file=None, database_url=runtime_url, login_account_limit=3)
        app = create_app(settings)
        with TestClient(app) as client:

            def login(name, password_value=test_password):
                response = client.post(
                    "/api/v1/auth/login",
                    json={
                        "email": f"{name}@example.test",
                        "password": password_value,
                    },
                )
                assert response.status_code == 200, response.text
                return {"Authorization": "Bearer " + response.json()["access_token"]}

            yield SimpleNamespace(
                client=client,
                login=login,
                ids=ids,
                runtime_engine=runtime_engine,
                admin_engine=admin_engine,
                runtime_url=runtime_url,
                settings=settings,
                password=test_password,
            )
    finally:
        runtime_engine.dispose()
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            # Only this randomly generated role and its test-database grants are touched.
            with suppress(psycopg.Error):
                connection.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            connection.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


@pytest.fixture
def outbox_database(security_database):
    from contextlib import suppress

    from app.config import Settings
    from app.db.database import Database
    from app.db.provisioning import create_worker
    from app.outbox.worker import Worker

    db = security_database
    parsed = make_url(db.admin_engine.url)
    admin_dsn = parsed.set(drivername="postgresql").render_as_string(hide_password=False)
    role = "assessment_test_worker_" + uuid4().hex[:20]
    password = "Worker fixture only " + uuid4().hex
    with psycopg.connect(admin_dsn) as connection:
        create_worker(connection, role, password)
    url = parsed.set(username=role, password=password).render_as_string(hide_password=False)
    database = Database(Settings(_env_file=None, database_url=url), role="worker")
    try:
        db.worker_database = database
        db.worker = Worker(database.sessions, lease_seconds=5, retry_base=1)
        yield db
    finally:
        database.close()
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            with suppress(psycopg.Error):
                connection.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            connection.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
