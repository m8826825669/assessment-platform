"""SCH-01/GOV-01 immutable acknowledgements by registered candidates."""

from alembic import op

revision = "0018_invitation_acceptances"
down_revision = "0017_sitting_reschedules"
branch_labels = None
depends_on = None
TABLE_SQL = "\nCREATE TABLE registration_acceptances (\n\ttenant_id UUID NOT NULL, \n\tregistration_id UUID NOT NULL, \n\tsitting_id UUID NOT NULL, \n\tcandidate_user_id UUID NOT NULL, \n\tregistration_revision INTEGER NOT NULL, \n\taccepted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_registration_acceptances PRIMARY KEY (tenant_id, registration_id), \n\tCONSTRAINT fk_acceptance_registration FOREIGN KEY(tenant_id, registration_id) REFERENCES sitting_registrations (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_registration_acceptances_acceptance_revision CHECK (registration_revision BETWEEN 1 AND 1000000)\n)\n\n"


def upgrade():
    op.execute(TABLE_SQL)
    op.execute("ALTER TABLE registration_acceptances ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE registration_acceptances FORCE ROW LEVEL SECURITY")
    active = """tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid AND EXISTS (
        SELECT 1 FROM public.memberships m JOIN public.users u ON u.id=m.user_id
        JOIN public.institutions i ON i.id=m.tenant_id WHERE m.tenant_id=registration_acceptances.tenant_id
        AND m.user_id=NULLIF(current_setting('app.actor_user_id',true),'')::uuid
        AND m.status='active' AND u.is_active AND i.status='active'
        AND (m.role IN ('admin','coordinator') OR (m.role='candidate' AND registration_acceptances.candidate_user_id=m.user_id)))"""
    op.execute(
        f"CREATE POLICY registration_acceptances_read ON registration_acceptances FOR SELECT USING ({active})"
    )
    candidate = """tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid
        AND candidate_user_id=NULLIF(current_setting('app.actor_user_id',true),'')::uuid AND EXISTS (
        SELECT 1 FROM public.memberships m JOIN public.users u ON u.id=m.user_id
        JOIN public.institutions i ON i.id=m.tenant_id WHERE m.tenant_id=registration_acceptances.tenant_id
        AND m.user_id=registration_acceptances.candidate_user_id
        AND m.role='candidate' AND m.status='active' AND u.is_active AND i.status='active')"""
    op.execute(
        f"CREATE POLICY registration_acceptances_create ON registration_acceptances FOR INSERT WITH CHECK ({candidate})"
    )
    op.execute("""
        CREATE FUNCTION registration_acceptance_guard() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public AS $$
        DECLARE registration public.sitting_registrations%ROWTYPE;
                sitting public.exam_sittings%ROWTYPE;
                latest_revision integer; latest_action text; eligible boolean; ack_time timestamptz;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'Invitation acceptance receipts are immutable' USING ERRCODE='42501';
            END IF;
            PERFORM 1 FROM public.institutions WHERE id=NEW.tenant_id FOR UPDATE;
            SELECT * INTO registration FROM public.sitting_registrations
                WHERE tenant_id=NEW.tenant_id AND id=NEW.registration_id;
            SELECT * INTO sitting FROM public.exam_sittings
                WHERE tenant_id=NEW.tenant_id AND id=registration.sitting_id;
            SELECT revision,action INTO latest_revision,latest_action FROM public.registration_changes
                WHERE tenant_id=NEW.tenant_id AND registration_id=NEW.registration_id ORDER BY revision DESC LIMIT 1;
            SELECT EXISTS (SELECT 1 FROM public.memberships m JOIN public.users u ON u.id=m.user_id
                JOIN public.institutions i ON i.id=m.tenant_id WHERE m.tenant_id=NEW.tenant_id
                AND m.user_id=NEW.candidate_user_id AND m.role='candidate' AND m.status='active'
                AND u.is_active AND i.status='active') INTO eligible;
            ack_time := clock_timestamp();
            IF registration.id IS NULL OR sitting.id IS NULL OR NOT eligible
                OR NEW.sitting_id IS DISTINCT FROM registration.sitting_id
                OR NEW.candidate_user_id IS DISTINCT FROM registration.candidate_user_id
                OR NEW.registration_revision IS DISTINCT FROM COALESCE(latest_revision,1)
                OR latest_action='withdraw' OR sitting.closes_at<=ack_time
                OR EXISTS (SELECT 1 FROM public.sitting_cancellations WHERE tenant_id=NEW.tenant_id AND sitting_id=registration.sitting_id) THEN
                RAISE EXCEPTION 'Invitation acknowledgement is unavailable or mismatched' USING ERRCODE='23514';
            END IF;
            NEW.accepted_at := ack_time;
            RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER registration_acceptance_guard BEFORE INSERT OR UPDATE OR DELETE ON registration_acceptances FOR EACH ROW EXECUTE FUNCTION registration_acceptance_guard()"
    )


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM registration_acceptances) THEN
                RAISE EXCEPTION 'Cannot discard invitation acceptance history';
            END IF;
        END $$
    """)
    op.execute("DROP TRIGGER registration_acceptance_guard ON registration_acceptances")
    op.execute("DROP FUNCTION registration_acceptance_guard()")
    op.drop_table("registration_acceptances")
