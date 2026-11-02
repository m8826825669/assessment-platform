"""Transactional audit and durable outbox. GOV-01, INT-01, IAM-01, TEN-01."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_audit_outbox"
down_revision = "0002_identity_tenancy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("scope_key", sa.String(36), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_kind", sa.String(20), nullable=False),
        sa.Column("actor_reference", sa.String(128), nullable=True),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column("before_state", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("after_state", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("request_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_audit_records"),
        sa.UniqueConstraint("id", "scope_key", name="uq_audit_records_id"),
        sa.CheckConstraint(
            "scope_key = COALESCE(tenant_id::text, 'global')",
            name=op.f("ck_audit_records_scope_matches_tenant"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(before_state) = 'object' AND jsonb_typeof(after_state) = 'object'",
            name=op.f("ck_audit_records_state_objects"),
        ),
        sa.CheckConstraint(
            "actor_kind IN ('user', 'operator', 'anonymous')", name=op.f("ck_audit_records_actor_kind_values")
        ),
    )
    op.create_index("ix_audit_records_tenant_created", "audit_records", ["tenant_id", "created_at", "id"])
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("scope_key", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
        sa.UniqueConstraint("audit_id", name="uq_outbox_events_audit_id"),
        sa.ForeignKeyConstraint(
            ["audit_id", "scope_key"],
            ["audit_records.id", "audit_records.scope_key"],
            ondelete="RESTRICT",
            name="fk_outbox_events_audit_id_audit_records",
        ),
        sa.CheckConstraint(
            "scope_key = COALESCE(tenant_id::text, 'global')",
            name=op.f("ck_outbox_events_scope_matches_tenant"),
        ),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name=op.f("ck_outbox_events_payload_object")),
    )
    op.create_table(
        "outbox_deliveries",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.PrimaryKeyConstraint("event_id", name="pk_outbox_deliveries"),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["outbox_events.id"],
            ondelete="RESTRICT",
            name="fk_outbox_deliveries_event_id_outbox_events",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'delivered', 'dead')",
            name=op.f("ck_outbox_deliveries_status_values"),
        ),
        sa.CheckConstraint(
            "max_attempts BETWEEN 1 AND 20 AND attempts BETWEEN 0 AND max_attempts",
            name=op.f("ck_outbox_deliveries_attempt_bounds"),
        ),
        sa.CheckConstraint(
            "(status = 'processing' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status <> 'processing' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name=op.f("ck_outbox_deliveries_lease_matches_status"),
        ),
        sa.CheckConstraint(
            "(status = 'delivered') = (delivered_at IS NOT NULL)",
            name=op.f("ck_outbox_deliveries_delivery_matches_status"),
        ),
    )
    op.create_index("ix_outbox_deliveries_ready", "outbox_deliveries", ["status", "available_at"])
    op.create_table(
        "consumer_receipts",
        sa.Column("consumer", sa.String(80), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("consumer", "event_id", name="pk_consumer_receipts"),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["outbox_events.id"],
            ondelete="RESTRICT",
            name="fk_consumer_receipts_event_id_outbox_events",
        ),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_consumer_receipts_hash_format")),
    )
    for table in ["audit_records", "outbox_events", "outbox_deliveries", "consumer_receipts"]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    scope = "tenant_id IS NULL OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    for table in ["audit_records", "outbox_events"]:
        op.execute(f"CREATE POLICY scoped_append ON {table} FOR INSERT WITH CHECK ({scope})")
    op.execute("""CREATE POLICY tenant_audit_read ON audit_records FOR SELECT USING (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    )""")
    op.execute("""CREATE POLICY operator_audit_read ON audit_records FOR SELECT USING (
        pg_has_role(current_user, pg_get_userbyid((SELECT relowner FROM pg_class
            WHERE oid = 'public.audit_records'::regclass)), 'MEMBER')
    )""")
    op.execute("CREATE POLICY worker_read ON outbox_events FOR SELECT USING (true)")
    op.execute("CREATE POLICY enqueue ON outbox_deliveries FOR INSERT WITH CHECK (true)")
    op.execute("CREATE POLICY worker_read ON outbox_deliveries FOR SELECT USING (true)")
    op.execute("CREATE POLICY worker_update ON outbox_deliveries FOR UPDATE USING (true) WITH CHECK (true)")
    op.execute("CREATE POLICY worker_read ON consumer_receipts FOR SELECT USING (true)")
    op.execute("CREATE POLICY worker_append ON consumer_receipts FOR INSERT WITH CHECK (true)")
    # Privileges distinguish API enqueuers from workers; policies never grant SQL privileges.


def downgrade() -> None:
    # Destructive, disposable-development use only. Existing evidence must not be removed in production.
    op.drop_table("consumer_receipts")
    op.drop_index("ix_outbox_deliveries_ready", table_name="outbox_deliveries")
    op.drop_table("outbox_deliveries")
    op.drop_table("outbox_events")
    op.drop_index("ix_audit_records_tenant_created", table_name="audit_records")
    op.drop_table("audit_records")
