from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings

EXPECTED_DATABASE_REVISION = "0008_question_imports"

# The runtime must be neither migration owner nor a role that can bypass row policies.
RUNTIME_ROLE_SAFE = text("""
SELECT NOT r.rolsuper AND NOT r.rolbypassrls AND NOT r.rolcreatedb
   AND NOT r.rolcreaterole AND NOT r.rolreplication
   AND NOT EXISTS (SELECT 1 FROM pg_auth_members m WHERE m.member = r.oid)
   AND NOT has_schema_privilege(current_user, 'public', 'CREATE')
   AND NOT has_database_privilege(current_user, current_database(), 'CREATE')
   AND NOT EXISTS (
       SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
       WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
       AND pg_has_role(current_user, c.relowner, 'MEMBER')
   )
FROM pg_roles r WHERE r.rolname = current_user
""")
RLS_CONFIGURED = text("""
SELECT count(*) = 16 AND bool_and(c.relrowsecurity AND c.relforcerowsecurity)
AND (SELECT count(*) = 10 AND bool_and(t.tgenabled = 'O') FROM pg_trigger t
     WHERE NOT t.tgisinternal AND
     ((t.tgrelid = 'public.questions'::regclass AND t.tgname = 'question_identity_guard') OR
      (t.tgrelid = 'public.question_versions'::regclass AND t.tgname = 'question_version_guard') OR
      (t.tgrelid = 'public.question_review_events'::regclass AND t.tgname = 'question_review_guard') OR
      (t.tgrelid = 'public.question_selections'::regclass AND t.tgname = 'question_selection_guard') OR
      (t.tgrelid = 'public.question_review_events'::regclass AND t.tgname = 'question_review_projection_guard') OR
      (t.tgrelid = 'public.taxonomy_terms'::regclass AND t.tgname = 'taxonomy_term_guard') OR
      (t.tgrelid = 'public.question_version_taxa'::regclass AND t.tgname = 'version_taxon_guard') OR
      (t.tgrelid = 'public.media_assets'::regclass AND t.tgname = 'media_asset_guard') OR
      (t.tgrelid = 'public.question_version_media'::regclass AND t.tgname = 'version_media_guard') OR
      (t.tgrelid = 'public.question_import_receipts'::regclass AND t.tgname = 'question_import_receipt_guard')))
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relname IN ('institutions', 'memberships', 'security_events', 'audit_records', 'outbox_events', 'outbox_deliveries', 'consumer_receipts', 'questions', 'question_versions', 'question_review_events', 'question_selections', 'taxonomy_terms', 'question_version_taxa', 'media_assets', 'question_version_media', 'question_import_receipts')
""")


API_GRANTS_READY = text("""
SELECT has_table_privilege(current_user, 'audit_records', 'SELECT')
   AND has_table_privilege(current_user, 'audit_records', 'INSERT')
   AND has_table_privilege(current_user, 'outbox_events', 'INSERT')
   AND has_table_privilege(current_user, 'outbox_deliveries', 'INSERT')
   AND has_table_privilege(current_user, 'users', 'SELECT')
   AND NOT has_table_privilege(current_user, 'outbox_deliveries', 'SELECT')
   AND NOT has_table_privilege(current_user, 'consumer_receipts', 'INSERT')
   AND has_table_privilege(current_user, 'questions', 'SELECT')
   AND has_table_privilege(current_user, 'questions', 'INSERT')
   AND has_column_privilege(current_user, 'questions', 'revision', 'UPDATE')
   AND has_table_privilege(current_user, 'question_versions', 'SELECT')
   AND has_table_privilege(current_user, 'question_versions', 'INSERT')
   AND NOT has_table_privilege(current_user, 'question_versions', 'UPDATE, DELETE, TRUNCATE')
   AND NOT has_table_privilege(current_user, 'questions', 'DELETE, TRUNCATE')
   AND NOT has_column_privilege(current_user, 'questions', 'created_by', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'questions', 'tenant_id', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'questions', 'id', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'questions', 'created_at', 'UPDATE')
   AND NOT has_any_column_privilege(current_user, 'question_versions', 'UPDATE')
   AND has_table_privilege(current_user, 'question_review_events', 'SELECT')
   AND has_table_privilege(current_user, 'question_review_events', 'INSERT')
   AND NOT has_any_column_privilege(current_user, 'question_review_events', 'UPDATE')
   AND NOT has_table_privilege(current_user, 'question_review_events', 'DELETE, TRUNCATE')
   AND has_table_privilege(current_user, 'question_selections', 'SELECT')
   AND has_table_privilege(current_user, 'question_selections', 'INSERT')
   AND has_column_privilege(current_user, 'question_selections', 'state', 'UPDATE')
   AND has_column_privilege(current_user, 'question_selections', 'last_event_id', 'UPDATE')
   AND NOT has_table_privilege(current_user, 'question_selections', 'DELETE, TRUNCATE')
   AND NOT has_column_privilege(current_user, 'question_selections', 'public_content', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'question_selections', 'title', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'question_selections', 'version_id', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'question_selections', 'tenant_id', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'question_selections', 'question_id', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'question_selections', 'created_at', 'UPDATE')
   AND has_table_privilege(current_user, 'taxonomy_terms', 'SELECT')
   AND has_table_privilege(current_user, 'taxonomy_terms', 'INSERT')
   AND has_column_privilege(current_user, 'taxonomy_terms', 'label', 'UPDATE')
   AND has_column_privilege(current_user, 'taxonomy_terms', 'state', 'UPDATE')
   AND has_column_privilege(current_user, 'taxonomy_terms', 'revision', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'taxonomy_terms', 'id', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'taxonomy_terms', 'tenant_id', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'taxonomy_terms', 'parent_id', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'taxonomy_terms', 'kind', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'taxonomy_terms', 'code', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'taxonomy_terms', 'created_by', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'taxonomy_terms', 'created_at', 'UPDATE')
   AND NOT has_table_privilege(current_user, 'taxonomy_terms', 'DELETE, TRUNCATE')
   AND has_table_privilege(current_user, 'question_version_taxa', 'SELECT')
   AND has_table_privilege(current_user, 'question_version_taxa', 'INSERT')
   AND NOT has_any_column_privilege(current_user, 'question_version_taxa', 'UPDATE')
   AND NOT has_table_privilege(current_user, 'question_version_taxa', 'DELETE, TRUNCATE')
   AND has_table_privilege(current_user, 'media_assets', 'SELECT')
   AND has_table_privilege(current_user, 'media_assets', 'INSERT')
   AND has_table_privilege(current_user, 'question_version_media', 'SELECT')
   AND has_table_privilege(current_user, 'question_version_media', 'INSERT')
   AND NOT has_any_column_privilege(current_user, 'question_version_media', 'UPDATE')
   AND NOT has_table_privilege(current_user, 'media_assets', 'DELETE, TRUNCATE')
   AND NOT has_table_privilege(current_user, 'question_version_media', 'DELETE, TRUNCATE')
   AND has_column_privilege(current_user, 'media_assets', 'state', 'UPDATE')
   AND has_column_privilege(current_user, 'media_assets', 'revision', 'UPDATE')
   AND has_column_privilege(current_user, 'media_assets', 'object_key', 'UPDATE')
   AND has_column_privilege(current_user, 'media_assets', 'object_version', 'UPDATE')
   AND has_column_privilege(current_user, 'media_assets', 'digest', 'UPDATE')
   AND has_column_privilege(current_user, 'media_assets', 'byte_length', 'UPDATE')
   AND has_column_privilege(current_user, 'media_assets', 'width', 'UPDATE')
   AND has_column_privilege(current_user, 'media_assets', 'height', 'UPDATE')
   AND has_column_privilege(current_user, 'media_assets', 'scanner_version', 'UPDATE')
   AND has_column_privilege(current_user, 'media_assets', 'error_code', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'media_assets', 'id', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'media_assets', 'tenant_id', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'media_assets', 'created_by', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'media_assets', 'filename', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'media_assets', 'mime_type', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'media_assets', 'description', 'UPDATE')
   AND NOT has_column_privilege(current_user, 'media_assets', 'created_at', 'UPDATE')
   AND has_table_privilege(current_user, 'question_import_receipts', 'SELECT')
   AND has_table_privilege(current_user, 'question_import_receipts', 'INSERT')
   AND NOT has_any_column_privilege(current_user, 'question_import_receipts', 'UPDATE')
   AND NOT has_table_privilege(current_user, 'question_import_receipts', 'DELETE, TRUNCATE')
""")
WORKER_GRANTS_READY = text("""
SELECT has_table_privilege(current_user, 'outbox_events', 'SELECT')
   AND has_table_privilege(current_user, 'outbox_deliveries', 'SELECT')
   AND has_column_privilege(current_user, 'outbox_deliveries', 'status', 'UPDATE')
   AND has_table_privilege(current_user, 'consumer_receipts', 'SELECT')
   AND has_table_privilege(current_user, 'consumer_receipts', 'INSERT')
   AND NOT has_table_privilege(current_user, 'users', 'SELECT')
   AND NOT has_table_privilege(current_user, 'audit_records', 'INSERT')
   AND NOT has_table_privilege(current_user, 'questions', 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE')
   AND NOT has_table_privilege(current_user, 'question_versions', 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE')
   AND NOT has_any_column_privilege(current_user, 'questions', 'SELECT, INSERT, UPDATE')
   AND NOT has_any_column_privilege(current_user, 'question_versions', 'SELECT, INSERT, UPDATE')
   AND NOT has_any_column_privilege(current_user, 'question_review_events', 'SELECT, INSERT, UPDATE')
   AND NOT has_any_column_privilege(current_user, 'question_selections', 'SELECT, INSERT, UPDATE')
   AND NOT has_table_privilege(current_user, 'question_review_events', 'DELETE, TRUNCATE')
   AND NOT has_table_privilege(current_user, 'question_selections', 'DELETE, TRUNCATE')
   AND NOT has_any_column_privilege(current_user, 'taxonomy_terms', 'SELECT, INSERT, UPDATE')
   AND NOT has_any_column_privilege(current_user, 'question_version_taxa', 'SELECT, INSERT, UPDATE')
   AND NOT has_table_privilege(current_user, 'taxonomy_terms', 'DELETE, TRUNCATE')
   AND NOT has_table_privilege(current_user, 'question_version_taxa', 'DELETE, TRUNCATE')
   AND NOT has_any_column_privilege(current_user, 'media_assets', 'SELECT, INSERT, UPDATE')
   AND NOT has_table_privilege(current_user, 'media_assets', 'DELETE, TRUNCATE')
   AND NOT has_any_column_privilege(current_user, 'question_version_media', 'SELECT, INSERT, UPDATE')
   AND NOT has_table_privilege(current_user, 'question_version_media', 'DELETE, TRUNCATE')
   AND NOT has_any_column_privilege(current_user, 'question_import_receipts', 'SELECT, INSERT, UPDATE')
   AND NOT has_table_privilege(current_user, 'question_import_receipts', 'DELETE, TRUNCATE')
""")


class UnsafeRuntimeRole(SQLAlchemyError):
    pass


def assert_runtime_role(connection: Connection) -> None:
    if not connection.scalar(RUNTIME_ROLE_SAFE) or not connection.scalar(RLS_CONFIGURED):
        raise UnsafeRuntimeRole("Restricted runtime role and forced tenant row policies are required")


class RuntimeSession(Session):
    """Reject privileged credentials at each transaction boundary."""


@event.listens_for(RuntimeSession, "after_begin")
def guard_runtime_transaction(session, transaction, connection):
    assert_runtime_role(connection)
    policy = WORKER_GRANTS_READY if session.info.get("role") == "worker" else API_GRANTS_READY
    if not connection.scalar(policy):
        raise UnsafeRuntimeRole("Required role-specific grants are missing or not separated")


class Database:
    def __init__(self, settings: Settings, *, role: str = "api") -> None:
        if role not in {"api", "worker"}:
            raise ValueError("Unknown database role mode")
        self.role = role
        self.engine = create_engine(
            settings.database_url.get_secret_value(),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            pool_timeout=settings.database_pool_timeout,
            hide_parameters=True,
            connect_args={
                "connect_timeout": settings.database_connect_timeout,
                "options": f"-c timezone=UTC -c search_path=public -c statement_timeout={settings.database_statement_timeout_ms}",
            },
        )
        self.sessions = sessionmaker(
            bind=self.engine, class_=RuntimeSession, expire_on_commit=False, info={"role": role}
        )

    def readiness(self) -> dict[str, str]:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                try:
                    revisions = set(
                        connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
                    )
                    tables_exist = connection.scalar(
                        text(
                            "SELECT to_regclass('institutions') IS NOT NULL AND to_regclass('users') IS NOT NULL "
                            "AND to_regclass('memberships') IS NOT NULL AND to_regclass('auth_sessions') IS NOT NULL "
                            "AND to_regclass('login_buckets') IS NOT NULL AND to_regclass('security_events') IS NOT NULL "
                            "AND to_regclass('audit_records') IS NOT NULL AND to_regclass('outbox_events') IS NOT NULL "
                            "AND to_regclass('outbox_deliveries') IS NOT NULL AND to_regclass('consumer_receipts') IS NOT NULL "
                            "AND to_regclass('questions') IS NOT NULL AND to_regclass('question_versions') IS NOT NULL "
                            "AND to_regclass('question_review_events') IS NOT NULL AND to_regclass('question_selections') IS NOT NULL "
                            "AND to_regclass('taxonomy_terms') IS NOT NULL AND to_regclass('question_version_taxa') IS NOT NULL "
                            "AND to_regclass('media_assets') IS NOT NULL AND to_regclass('question_version_media') IS NOT NULL "
                            "AND to_regclass('question_import_receipts') IS NOT NULL"
                        )
                    )
                    if revisions != {EXPECTED_DATABASE_REVISION} or not tables_exist:
                        return {"postgresql": "ok", "schema": "not_ready", "runtime_role": "unknown"}
                except SQLAlchemyError:
                    return {"postgresql": "ok", "schema": "not_ready", "runtime_role": "unknown"}
                try:
                    assert_runtime_role(connection)
                    role = (
                        "ok"
                        if connection.scalar(
                            WORKER_GRANTS_READY if self.role == "worker" else API_GRANTS_READY
                        )
                        else "missing_grants"
                    )
                except UnsafeRuntimeRole:
                    role = "unsafe"
                return {"postgresql": "ok", "schema": "ok", "runtime_role": role}
        except SQLAlchemyError:
            return {"postgresql": "unavailable", "schema": "unknown", "runtime_role": "unknown"}

    def close(self) -> None:
        self.engine.dispose()
