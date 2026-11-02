"""Identity sessions, tenant roles and enforced database row policies.

Requirements IAM-01, TEN-01, SEC-01.
"""

import sqlalchemy as sa

from alembic import op

revision = "0002_identity_tenancy"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(512), nullable=True))
    op.add_column("memberships", sa.Column("role", sa.String(30), server_default="candidate", nullable=False))
    op.create_check_constraint(
        op.f("ck_memberships_role_values"),
        "memberships",
        "role IN ('admin', 'coordinator', 'author', 'reviewer', 'invigilator', 'examiner', 'candidate')",
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="RESTRICT", name="fk_auth_sessions_user_id_users"
        ),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_auth_sessions_token_hash_format")),
        sa.CheckConstraint("expires_at > created_at", name=op.f("ck_auth_sessions_expiry_after_creation")),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_table(
        "login_buckets",
        sa.Column("bucket_key", sa.String(64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("bucket_key", name="pk_login_buckets"),
        sa.CheckConstraint("attempts > 0", name=op.f("ck_login_buckets_positive_attempts")),
    )
    op.create_table(
        "security_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_security_events"),
    )
    op.create_index("ix_security_events_tenant_id", "security_events", ["tenant_id"])
    # Transaction-local context is set by the application only after authenticating the bearer.
    for table, column in [("institutions", "id"), ("memberships", "tenant_id")]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        expression = f"{column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
        op.execute(f"CREATE POLICY tenant_boundary ON {table} USING ({expression}) WITH CHECK ({expression})")
    op.execute("""CREATE POLICY own_memberships ON memberships FOR SELECT USING (
        NULLIF(current_setting('app.tenant_id', true), '') IS NULL
        AND user_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid
    )""")
    op.execute("""CREATE POLICY own_institutions ON institutions FOR SELECT USING (
        NULLIF(current_setting('app.tenant_id', true), '') IS NULL
        AND EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = institutions.id
            AND m.user_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid
            AND m.status = 'active')
    )""")
    op.execute("ALTER TABLE security_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE security_events FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY security_event_append ON security_events FOR INSERT WITH CHECK (
        tenant_id IS NULL OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    )""")
    op.execute("""CREATE POLICY security_event_operator_read ON security_events FOR SELECT USING (
        pg_has_role(current_user, pg_get_userbyid((SELECT relowner FROM pg_class
            WHERE oid = 'public.security_events'::regclass)), 'MEMBER')
    )""")
    # Runtime receives INSERT only; the migration owner can inspect security history.


def downgrade() -> None:
    # Destructive, disposable-development use only.
    op.execute("DROP POLICY security_event_operator_read ON security_events")
    op.execute("DROP POLICY security_event_append ON security_events")
    op.drop_index("ix_security_events_tenant_id", table_name="security_events")
    op.drop_table("security_events")
    op.execute("DROP POLICY own_institutions ON institutions")
    op.execute("DROP POLICY own_memberships ON memberships")
    for table in ["memberships", "institutions"]:
        op.execute(f"DROP POLICY tenant_boundary ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.drop_table("login_buckets")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_constraint(op.f("ck_memberships_role_values"), "memberships", type_="check")
    op.drop_column("memberships", "role")
    op.drop_column("users", "password_hash")
