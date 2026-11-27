"""SCH-01/GOV-01 permanent pre-opening sitting cancellations."""

import sqlalchemy as sa

from alembic import op

revision = "0015_sitting_cancellations"
down_revision = "0014_exam_sittings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sitting_cancellations",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("sitting_id", sa.Uuid(), nullable=False),
        sa.Column("reason_code", sa.String(20), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "sitting_id", name="pk_sitting_cancellations"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sitting_id"],
            ["exam_sittings.tenant_id", "exam_sittings.id"],
            name="fk_cancellation_sitting",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_sitting_cancellations_created_by_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "reason_code IN ('administrative', 'schedule_error', 'operational')",
            name=op.f("ck_sitting_cancellations_cancellation_reason"),
        ),
    )
    op.execute("ALTER TABLE sitting_cancellations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sitting_cancellations FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY sitting_cancellations_read ON sitting_cancellations FOR SELECT USING (
            tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid AND EXISTS (
                SELECT 1 FROM public.memberships m JOIN public.users u ON u.id=m.user_id
                JOIN public.institutions i ON i.id=m.tenant_id
                WHERE m.tenant_id=sitting_cancellations.tenant_id
                AND m.user_id=NULLIF(current_setting('app.actor_user_id',true),'')::uuid
                AND m.status='active' AND u.is_active AND i.status='active'
                AND (m.role IN ('admin','coordinator') OR (m.role='candidate' AND EXISTS (
                    SELECT 1 FROM public.sitting_registrations r
                    WHERE r.tenant_id=sitting_cancellations.tenant_id
                    AND r.sitting_id=sitting_cancellations.sitting_id AND r.candidate_user_id=m.user_id
                )))
            )
        )
    """)
    op.execute("""
        CREATE POLICY sitting_cancellations_create ON sitting_cancellations FOR INSERT WITH CHECK (
            tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid
            AND created_by=NULLIF(current_setting('app.actor_user_id',true),'')::uuid
            AND EXISTS (
                SELECT 1 FROM public.memberships m JOIN public.users u ON u.id=m.user_id
                JOIN public.institutions i ON i.id=m.tenant_id
                WHERE m.tenant_id=sitting_cancellations.tenant_id
                AND m.user_id=NULLIF(current_setting('app.actor_user_id',true),'')::uuid
                AND m.status='active' AND u.is_active AND i.status='active'
                AND m.role IN ('admin','coordinator')
            )
        )
    """)
    op.execute("""
        CREATE FUNCTION sitting_cancellation_guard() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public AS $$
        DECLARE opening timestamptz;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'Cancellations are immutable' USING ERRCODE='42501';
            END IF;
            PERFORM 1 FROM public.institutions WHERE id=NEW.tenant_id FOR UPDATE;
            SELECT opens_at INTO opening FROM public.exam_sittings
                WHERE tenant_id=NEW.tenant_id AND id=NEW.sitting_id;
            IF opening IS NULL OR opening <= clock_timestamp() THEN
                RAISE EXCEPTION 'Cancellation requires an unopened sitting' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE FUNCTION registration_cancellation_guard() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public AS $$
        BEGIN
            PERFORM 1 FROM public.institutions WHERE id=NEW.tenant_id FOR UPDATE;
            IF EXISTS (SELECT 1 FROM public.sitting_cancellations
                       WHERE tenant_id=NEW.tenant_id AND sitting_id=NEW.sitting_id) THEN
                RAISE EXCEPTION 'Cannot register for a cancelled sitting' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER sitting_cancellation_guard BEFORE INSERT OR UPDATE OR DELETE ON sitting_cancellations FOR EACH ROW EXECUTE FUNCTION sitting_cancellation_guard()"
    )
    op.execute(
        "CREATE TRIGGER registration_cancellation_guard BEFORE INSERT ON sitting_registrations FOR EACH ROW EXECUTE FUNCTION registration_cancellation_guard()"
    )


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM sitting_cancellations) THEN
                RAISE EXCEPTION 'Cannot discard existing sitting cancellations during downgrade';
            END IF;
        END $$
    """)
    op.execute("DROP TRIGGER registration_cancellation_guard ON sitting_registrations")
    op.execute("DROP TRIGGER sitting_cancellation_guard ON sitting_cancellations")
    op.execute("DROP FUNCTION registration_cancellation_guard()")
    op.execute("DROP FUNCTION sitting_cancellation_guard()")
    op.drop_table("sitting_cancellations")
