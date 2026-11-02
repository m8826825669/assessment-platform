"""Atomic draft import success receipts. QBK-01, QBK-02, TEN-01, GOV-01."""

from alembic import op

revision = "0008_question_imports"
down_revision = "0007_authoring_media"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE TABLE question_import_receipts (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tactor_user_id UUID NOT NULL, \n\tidempotency_key UUID NOT NULL, \n\tprofile VARCHAR(50) NOT NULL, \n\trequest_hash VARCHAR(64) NOT NULL, \n\titem_count INTEGER NOT NULL, \n\tresult JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_question_import_receipts PRIMARY KEY (id), \n\tCONSTRAINT uq_question_import_actor_key UNIQUE (tenant_id, actor_user_id, idempotency_key), \n\tCONSTRAINT ck_question_import_receipts_profile CHECK (profile = 'assessment-question-import.v1'), \n\tCONSTRAINT ck_question_import_receipts_request_hash CHECK (request_hash ~ '^[0-9a-f]{64}$'), \n\tCONSTRAINT ck_question_import_receipts_item_count CHECK (item_count BETWEEN 1 AND 50), \n\tCONSTRAINT ck_question_import_receipts_result_array CHECK (jsonb_typeof(result) = 'array' AND jsonb_array_length(result) = item_count), \n\tCONSTRAINT fk_question_import_receipts_tenant_id_institutions FOREIGN KEY(tenant_id) REFERENCES institutions (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_question_import_receipts_actor_user_id_users FOREIGN KEY(actor_user_id) REFERENCES users (id) ON DELETE RESTRICT\n)"
    )
    op.execute("ALTER TABLE question_import_receipts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE question_import_receipts FORCE ROW LEVEL SECURITY")
    scope = """tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid
        AND actor_user_id=NULLIF(current_setting('app.actor_user_id',true),'')::uuid
        AND EXISTS (SELECT 1 FROM public.memberships m JOIN public.users u ON u.id=m.user_id
            JOIN public.institutions i ON i.id=m.tenant_id WHERE m.tenant_id=question_import_receipts.tenant_id
            AND m.user_id=question_import_receipts.actor_user_id AND m.role IN ('admin','author')
            AND m.status='active' AND i.status='active' AND u.is_active)"""
    op.execute(f"CREATE POLICY import_receipt_read ON question_import_receipts FOR SELECT USING ({scope})")
    op.execute(
        f"CREATE POLICY import_receipt_create ON question_import_receipts FOR INSERT WITH CHECK ({scope})"
    )
    op.execute("""CREATE FUNCTION question_import_receipt_guard() RETURNS trigger LANGUAGE plpgsql
        SET search_path=pg_catalog,public AS $$
        DECLARE item jsonb; creation bigint;
        BEGIN
            IF TG_OP<>'INSERT' THEN
                RAISE EXCEPTION 'Import receipts are immutable' USING ERRCODE='42501'; END IF;
            IF jsonb_typeof(NEW.result)<>'array' OR jsonb_array_length(NEW.result)<>NEW.item_count THEN
                RAISE EXCEPTION 'Import result count mismatch' USING ERRCODE='23514'; END IF;
            IF (SELECT count(DISTINCT x->>'reference') FROM jsonb_array_elements(NEW.result) x)<>NEW.item_count OR
               (SELECT count(DISTINCT (x->>'question_id')::uuid) FROM jsonb_array_elements(NEW.result) x)<>NEW.item_count OR
               (SELECT count(DISTINCT (x->>'version_id')::uuid) FROM jsonb_array_elements(NEW.result) x)<>NEW.item_count THEN
                RAISE EXCEPTION 'Import references must be distinct' USING ERRCODE='23514'; END IF;
            FOR item IN SELECT value FROM jsonb_array_elements(NEW.result) LOOP
                IF jsonb_typeof(item)<>'object' OR NOT (item ?& ARRAY['reference','question_id','version_id']) OR
                   item-ARRAY['reference','question_id','version_id'] <> '{}'::jsonb OR
                   jsonb_typeof(item->'reference')<>'string' OR jsonb_typeof(item->'question_id')<>'string' OR
                   jsonb_typeof(item->'version_id')<>'string' OR item->>'reference' !~ '^[a-z][a-z0-9_-]{0,63}$' THEN
                    RAISE EXCEPTION 'Invalid import receipt mapping' USING ERRCODE='23514'; END IF;
                creation := NULL;
                SELECT v.created_txid INTO creation FROM public.question_versions v JOIN public.questions q
                    ON q.tenant_id=v.tenant_id AND q.id=v.question_id
                    WHERE v.tenant_id=NEW.tenant_id AND v.question_id=(item->>'question_id')::uuid AND v.id=(item->>'version_id')::uuid
                    AND v.version_number=1 AND q.revision=1 AND v.authored_by=NEW.actor_user_id AND q.created_by=NEW.actor_user_id
                    AND NOT EXISTS (SELECT 1 FROM public.question_review_events e WHERE e.tenant_id=v.tenant_id AND e.version_id=v.id);
                IF creation IS NULL OR creation<>txid_current() THEN
                    RAISE EXCEPTION 'Receipt must bind new owned drafts in the same transaction' USING ERRCODE='23514'; END IF;
            END LOOP;
            RETURN NEW;
        END $$""")
    op.execute(
        "CREATE TRIGGER question_import_receipt_guard BEFORE INSERT OR UPDATE OR DELETE ON question_import_receipts FOR EACH ROW EXECUTE FUNCTION question_import_receipt_guard()"
    )


def downgrade():
    op.drop_table("question_import_receipts")
    op.execute("DROP FUNCTION question_import_receipt_guard()")
