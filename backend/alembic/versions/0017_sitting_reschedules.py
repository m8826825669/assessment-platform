"""SCH-01/PUB-01 immutable links for atomic pre-opening sitting replacement."""

from alembic import op

revision = "0017_sitting_reschedules"
down_revision = "0016_registration_changes"
branch_labels = None
depends_on = None

TABLE_SQL = "\nCREATE TABLE sitting_reschedules (\n\ttenant_id UUID NOT NULL, \n\tsitting_id UUID NOT NULL, \n\treplacement_id UUID NOT NULL, \n\treason_code VARCHAR(20) NOT NULL, \n\tcreated_by UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_sitting_reschedules PRIMARY KEY (tenant_id, sitting_id), \n\tCONSTRAINT fk_reschedule_original FOREIGN KEY(tenant_id, sitting_id) REFERENCES exam_sittings (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_reschedule_replacement FOREIGN KEY(tenant_id, replacement_id) REFERENCES exam_sittings (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_reschedule_replacement UNIQUE (tenant_id, replacement_id), \n\tCONSTRAINT ck_sitting_reschedules_reschedule_distinct CHECK (sitting_id <> replacement_id), \n\tCONSTRAINT ck_sitting_reschedules_reschedule_reason CHECK (reason_code IN ('administrative', 'schedule_error', 'operational')), \n\tCONSTRAINT fk_sitting_reschedules_created_by_users FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE RESTRICT\n)\n\n"


def upgrade():
    op.execute(TABLE_SQL)
    op.execute("ALTER TABLE sitting_reschedules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sitting_reschedules FORCE ROW LEVEL SECURITY")
    staff = """tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid AND EXISTS (
        SELECT 1 FROM public.memberships m JOIN public.users u ON u.id=m.user_id
        JOIN public.institutions i ON i.id=m.tenant_id
        WHERE m.tenant_id=sitting_reschedules.tenant_id
        AND m.user_id=NULLIF(current_setting('app.actor_user_id',true),'')::uuid
        AND m.status='active' AND u.is_active AND i.status='active'
        AND m.role IN ('admin','coordinator'))"""
    op.execute(f"CREATE POLICY sitting_reschedules_read ON sitting_reschedules FOR SELECT USING ({staff})")
    op.execute(
        f"CREATE POLICY sitting_reschedules_create ON sitting_reschedules FOR INSERT WITH CHECK (({staff}) AND created_by=NULLIF(current_setting('app.actor_user_id',true),'')::uuid)"
    )
    op.execute("""
        CREATE FUNCTION sitting_reschedule_guard() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public AS $$
        DECLARE original public.exam_sittings%ROWTYPE;
                replacement public.exam_sittings%ROWTYPE;
                cancellation public.sitting_cancellations%ROWTYPE;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'Reschedule links are immutable' USING ERRCODE='42501';
            END IF;
            PERFORM 1 FROM public.institutions WHERE id=NEW.tenant_id FOR UPDATE;
            SELECT * INTO original FROM public.exam_sittings WHERE tenant_id=NEW.tenant_id AND id=NEW.sitting_id;
            SELECT * INTO replacement FROM public.exam_sittings WHERE tenant_id=NEW.tenant_id AND id=NEW.replacement_id;
            SELECT * INTO cancellation FROM public.sitting_cancellations WHERE tenant_id=NEW.tenant_id AND sitting_id=NEW.sitting_id;
            IF original.id IS NULL OR replacement.id IS NULL OR cancellation.sitting_id IS NULL
                OR original.opens_at <= clock_timestamp() OR replacement.opens_at <= clock_timestamp()
                OR cancellation.reason_code IS DISTINCT FROM NEW.reason_code
                OR cancellation.created_by IS DISTINCT FROM NEW.created_by
                OR replacement.created_by IS DISTINCT FROM NEW.created_by
                OR replacement.publication_id IS DISTINCT FROM original.publication_id
                OR replacement.policy IS DISTINCT FROM original.policy
                OR replacement.duration_minutes IS DISTINCT FROM original.duration_minutes
                OR replacement.title IS DISTINCT FROM original.title
                OR EXISTS (SELECT 1 FROM public.sitting_cancellations WHERE tenant_id=NEW.tenant_id AND sitting_id=NEW.replacement_id)
                OR EXISTS (SELECT 1 FROM public.sitting_registrations WHERE tenant_id=NEW.tenant_id AND sitting_id=NEW.replacement_id) THEN
                RAISE EXCEPTION 'Invalid sitting replacement relationship' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER sitting_reschedule_guard BEFORE INSERT OR UPDATE OR DELETE ON sitting_reschedules FOR EACH ROW EXECUTE FUNCTION sitting_reschedule_guard()"
    )


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM sitting_reschedules) THEN
                RAISE EXCEPTION 'Cannot discard sitting reschedule history';
            END IF;
        END $$
    """)
    op.execute("DROP TRIGGER sitting_reschedule_guard ON sitting_reschedules")
    op.execute("DROP FUNCTION sitting_reschedule_guard()")
    op.drop_table("sitting_reschedules")
