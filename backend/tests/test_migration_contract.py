from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.db.database import EXPECTED_DATABASE_REVISION
from app.db.models import Base


def config():
    return Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))


def test_database_revision_matches_single_alembic_head():
    assert ScriptDirectory.from_config(config()).get_heads() == [EXPECTED_DATABASE_REVISION]


def test_offline_sql_generation(monkeypatch):
    monkeypatch.setenv("ASSESSMENT_DATABASE_URL", "postgresql+psycopg://local@localhost/disposable")
    settings = config()
    output = StringIO()
    settings.output_buffer = output
    command.upgrade(settings, "head", sql=True)
    script = output.getvalue()
    assert "CREATE TABLE institutions" in script
    assert "CREATE TABLE users" in script
    assert "CREATE TABLE memberships" in script
    assert "FOREIGN KEY(tenant_id) REFERENCES institutions" in script
    assert "TIMESTAMP WITH TIME ZONE" in script
    assert "0001_foundation" in script
    assert "BEGIN;" in script and "COMMIT;" in script
    assert "ck_institutions_ck_" not in script


def test_metadata_records_explicit_membership_ownership():
    table = Base.metadata.tables["memberships"]
    assert table.c.tenant_id.nullable is False
    assert {fk.target_fullname for fk in table.foreign_keys} == {"institutions.id", "users.id"}


def test_identity_migration_enables_forced_policies_and_does_not_embed_runtime_passwords(monkeypatch):
    monkeypatch.setenv("ASSESSMENT_DATABASE_URL", "postgresql+psycopg://local@localhost/disposable")
    settings = config()
    output = StringIO()
    settings.output_buffer = output
    command.upgrade(settings, "head", sql=True)
    script = output.getvalue()
    assert "FORCE ROW LEVEL SECURITY" in script
    assert "CREATE POLICY tenant_boundary" in script
    assert "CREATE POLICY own_memberships" in script
    assert "CREATE POLICY own_institutions" in script
    assert "current_setting('app.tenant_id', true)" in script
    assert "CREATE ROLE" not in script
    assert "password_hash" in script
    assert "0002_identity_tenancy" in script


def test_audit_outbox_migration_has_scope_fk_and_no_transport_credentials(monkeypatch):
    monkeypatch.setenv("ASSESSMENT_DATABASE_URL", "postgresql+psycopg://local@localhost/disposable")
    settings = config()
    output = StringIO()
    settings.output_buffer = output
    command.upgrade(settings, "head", sql=True)
    script = output.getvalue()
    assert "FOREIGN KEY(audit_id, scope_key) REFERENCES audit_records (id, scope_key)" in script
    assert "CREATE TABLE consumer_receipts" in script
    assert "CREATE POLICY tenant_audit_read" in script
    assert "CREATE TABLE outbox_deliveries" in script
    assert "CREATE ROLE" not in script
    assert "0003_audit_outbox" in script


def test_question_schema_has_scoped_current_version_fk_and_immutable_guards(monkeypatch):
    monkeypatch.setenv("ASSESSMENT_DATABASE_URL", "postgresql+psycopg://local@localhost/disposable")
    settings = config()
    output = StringIO()
    settings.output_buffer = output
    command.upgrade(settings, "head", sql=True)
    script = output.getvalue()
    assert "DEFERRABLE INITIALLY DEFERRED" in script
    assert "FOREIGN KEY(tenant_id, id, revision)" in script
    assert "FOREIGN KEY(tenant_id, question_id) REFERENCES questions (tenant_id, id)" in script
    assert "CREATE TRIGGER question_version_guard" in script
    assert "CREATE TRIGGER question_identity_guard" in script
    assert "CREATE POLICY question_version_append" in script
    assert "SECURITY DEFINER" not in script
