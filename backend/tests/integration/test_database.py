from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.config import Settings
from app.db.database import EXPECTED_DATABASE_REVISION
from app.db.models import Base, Institution, Membership, User
from app.main import create_app

pytestmark = pytest.mark.integration


def seed(engine):
    with Session(engine) as session, session.begin():
        institution = Institution(id=uuid4(), slug="pilot-school", name="Pilot School")
        session.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(institution.id)}
        )
        user = User(email="coordinator@example.test", display_name="Coordinator")
        session.add_all([institution, user])
        session.flush()
        membership = Membership(tenant_id=institution.id, user_id=user.id)
        session.add(membership)
        session.flush()
        return institution.id, user.id


def test_migrate_from_zero_and_metadata_match(test_database):
    _, engine, config, migrate = test_database
    assert inspect(engine).get_table_names() == []
    migrate()
    assert set(inspect(engine).get_table_names()) == {"alembic_version", *Base.metadata.tables}
    with engine.begin() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version")) == EXPECTED_DATABASE_REVISION
        )
        config.attributes["connection"] = connection
        command.check(config)
    config.attributes.pop("connection", None)


def test_second_upgrade_preserves_existing_data(test_database):
    _, engine, _, migrate = test_database
    migrate()
    tenant_id, _ = seed(engine)
    migrate()
    with engine.connect() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_id)}
        )
        assert connection.scalar(text("SELECT count(*) FROM memberships")) == 1


def test_schema_has_named_constraints(test_database):
    _, engine, _, migrate = test_database
    migrate()
    names = {row["name"] for row in inspect(engine).get_check_constraints("institutions")}
    assert names == {
        "ck_institutions_slug_format",
        "ck_institutions_name_not_blank",
        "ck_institutions_status_values",
    }


def test_readiness_rejects_missing_schema_and_migration_owner(test_database):
    url, _, _, migrate = test_database
    app = create_app(Settings(_env_file=None, database_url=url))
    with TestClient(app) as client:
        response = client.get("/api/v1/ready")
        assert response.status_code == 503
        assert response.json()["dependencies"] == {
            "postgresql": "ok",
            "schema": "not_ready",
            "runtime_role": "unknown",
        }
        migrate()
        response = client.get("/api/v1/ready")
        assert response.status_code == 503  # A migration owner is not a runtime account.
        assert response.json()["dependencies"]["schema"] == "ok"
        assert response.json()["dependencies"]["runtime_role"] == "unsafe"


def test_readiness_rejects_an_unexpected_revision(test_database):
    url, engine, _, migrate = test_database
    migrate()
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'unexpected'"))
    with TestClient(create_app(Settings(_env_file=None, database_url=url))) as client:
        assert client.get("/api/v1/ready").status_code == 503


def test_timestamp_and_committed_data_roundtrip(test_database):
    _, engine, _, migrate = test_database
    migrate()
    tenant_id, user_id = seed(engine)
    with Session(engine) as session:
        session.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_id)})
        institution = session.get(Institution, tenant_id)
        assert institution.created_at.tzinfo is not None
        assert institution.status == "active"
        assert session.get(User, user_id).is_active is True
        assert session.query(Membership).one().tenant_id == tenant_id


def test_duplicate_membership_rejected(test_database):
    _, engine, _, migrate = test_database
    migrate()
    tenant_id, user_id = seed(engine)
    with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
        session.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_id)})
        session.add(Membership(tenant_id=tenant_id, user_id=user_id))
        session.flush()


def test_membership_requires_existing_tenant_and_user(test_database):
    _, engine, _, migrate = test_database
    migrate()
    with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
        missing_tenant = uuid4()
        session.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(missing_tenant)}
        )
        session.add(Membership(tenant_id=missing_tenant, user_id=uuid4()))
        session.flush()


@pytest.mark.parametrize(
    "values",
    [
        {"slug": "UPPER_CASE", "name": "School"},
        {"slug": "school", "name": "   "},
        {"slug": "school", "name": "School", "status": "invalid"},
    ],
)
def test_institution_constraints_are_enforced_by_postgresql(test_database, values):
    _, engine, _, migrate = test_database
    migrate()
    with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
        tenant_id = uuid4()
        session.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_id)})
        session.add(Institution(id=tenant_id, **values))
        session.flush()


def test_email_requires_normalized_value(test_database):
    _, engine, _, migrate = test_database
    migrate()
    with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
        session.add(User(email="UPPER@example.test", display_name="User"))
        session.flush()


def test_failed_transaction_does_not_partially_commit(test_database):
    _, engine, _, migrate = test_database
    migrate()
    with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
        tenant_id = uuid4()
        session.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_id)})
        session.add(Institution(id=tenant_id, slug="valid-school", name="School"))
        session.flush()
        missing_tenant = uuid4()
        session.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(missing_tenant)}
        )
        session.add(Membership(tenant_id=missing_tenant, user_id=uuid4()))
        session.flush()
    with engine.connect() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_id)}
        )
        assert connection.scalar(text("SELECT count(*) FROM institutions")) == 0


def test_migration_downgrade_and_reupgrade_on_disposable_database(test_database):
    _, engine, config, migrate = test_database
    migrate()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
    config.attributes.pop("connection", None)
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    migrate()
    assert "memberships" in inspect(engine).get_table_names()


def test_stamped_revision_without_tables_is_not_ready(test_database):
    url, engine, _, migrate = test_database
    migrate()
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE auth_sessions"))
    with TestClient(create_app(Settings(_env_file=None, database_url=url))) as client:
        assert client.get("/api/v1/ready").status_code == 503
