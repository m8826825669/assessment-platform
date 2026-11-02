"""Institution taxonomy and immutable version classification. QBK-01, TEN-01, GOV-01."""

import sqlalchemy as sa

from alembic import op

revision = "0006_question_taxonomy"
down_revision = "0005_question_review"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "question_versions", sa.Column("created_txid", sa.BigInteger(), nullable=False, server_default="0")
    )
    op.alter_column("question_versions", "created_txid", server_default=sa.text("txid_current()"))
    op.create_unique_constraint(
        "uq_question_versions_taxonomy_binding", "question_versions", ["tenant_id", "question_id", "id"]
    )
    op.execute(
        "CREATE TABLE taxonomy_terms (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tkind VARCHAR(20) NOT NULL, \n\tcode VARCHAR(64) NOT NULL, \n\tlabel VARCHAR(200) NOT NULL, \n\tparent_id UUID, \n\tstate VARCHAR(20) DEFAULT 'active' NOT NULL, \n\trevision INTEGER DEFAULT '1' NOT NULL, \n\tcreated_by UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_taxonomy_terms PRIMARY KEY (id), \n\tCONSTRAINT uq_taxonomy_terms_tenant_id UNIQUE (tenant_id, id), \n\tCONSTRAINT uq_taxonomy_kind_code UNIQUE (tenant_id, kind, code), \n\tCONSTRAINT fk_taxonomy_parent FOREIGN KEY(tenant_id, parent_id) REFERENCES taxonomy_terms (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_taxonomy_terms_kind_values CHECK (kind IN ('subject','topic','outcome','tag')), \n\tCONSTRAINT ck_taxonomy_terms_code_format CHECK (code ~ '^[a-z][a-z0-9_-]{0,63}$'), \n\tCONSTRAINT ck_taxonomy_terms_label_not_blank CHECK (length(trim(label)) BETWEEN 1 AND 200), \n\tCONSTRAINT ck_taxonomy_terms_state_revision CHECK (state IN ('active','retired') AND revision > 0), \n\tCONSTRAINT ck_taxonomy_terms_topic_parent CHECK ((kind='topic') = (parent_id IS NOT NULL)), \n\tCONSTRAINT fk_taxonomy_terms_tenant_id_institutions FOREIGN KEY(tenant_id) REFERENCES institutions (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_taxonomy_terms_created_by_users FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE RESTRICT\n)"
    )
    op.execute(
        "CREATE TABLE question_version_taxa (\n\ttenant_id UUID NOT NULL, \n\tversion_id UUID NOT NULL, \n\tterm_id UUID NOT NULL, \n\tquestion_id UUID NOT NULL, \n\tkind_snapshot VARCHAR(20) NOT NULL, \n\tcode_snapshot VARCHAR(64) NOT NULL, \n\tlabel_snapshot VARCHAR(200) NOT NULL, \n\tparent_id_snapshot UUID, \n\tterm_revision INTEGER NOT NULL, \n\tCONSTRAINT pk_question_version_taxa PRIMARY KEY (tenant_id, version_id, term_id), \n\tCONSTRAINT fk_version_taxon_version FOREIGN KEY(tenant_id, question_id, version_id) REFERENCES question_versions (tenant_id, question_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_version_taxon_term FOREIGN KEY(tenant_id, term_id) REFERENCES taxonomy_terms (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_question_version_taxa_positive_term_revision CHECK (term_revision > 0), \n\tCONSTRAINT ck_question_version_taxa_kind_values CHECK (kind_snapshot IN ('subject','topic','outcome','tag'))\n)"
    )
    op.execute(
        "CREATE INDEX ix_version_taxa_term_version ON question_version_taxa (tenant_id, term_id, version_id)"
    )
    op.execute(
        "CREATE OR REPLACE FUNCTION question_version_guard() RETURNS trigger LANGUAGE plpgsql\n        SET search_path = pg_catalog, public AS $$\n        DECLARE current_revision integer;\n        BEGIN\n            IF TG_OP <> 'INSERT' THEN\n                RAISE EXCEPTION 'Saved question versions are immutable' USING ERRCODE = '42501';\n            END IF;\n            NEW.created_txid := txid_current();\n            SELECT q.revision INTO current_revision FROM public.questions q\n                WHERE q.tenant_id = NEW.tenant_id AND q.id = NEW.question_id FOR UPDATE;\n            IF current_revision IS NULL OR current_revision <> NEW.version_number THEN\n                RAISE EXCEPTION 'Version must match the current revision' USING ERRCODE = '23514';\n            END IF;\n            RETURN NEW;\n        END $$"
    )
    for table in ["taxonomy_terms", "question_version_taxa"]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    actor = "NULLIF(current_setting('app.actor_user_id', true), '')::uuid"
    scope = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    staff = f"""EXISTS (SELECT 1 FROM public.memberships m JOIN public.institutions i ON i.id=m.tenant_id
        JOIN public.users u ON u.id=m.user_id WHERE m.tenant_id=taxonomy_terms.tenant_id AND m.user_id={actor}
        AND m.status='active' AND i.status='active' AND u.is_active AND m.role IN ('admin','author','reviewer','coordinator'))"""
    admin = staff.replace("m.role IN ('admin','author','reviewer','coordinator')", "m.role='admin'")
    op.execute(f"CREATE POLICY taxonomy_read ON taxonomy_terms FOR SELECT USING (({scope}) AND ({staff}))")
    op.execute(
        f"CREATE POLICY taxonomy_create ON taxonomy_terms FOR INSERT WITH CHECK (({scope}) AND ({admin}) AND created_by={actor})"
    )
    op.execute(
        f"CREATE POLICY taxonomy_change ON taxonomy_terms FOR UPDATE USING (({scope}) AND ({admin})) WITH CHECK (({scope}) AND ({admin}))"
    )
    private = "EXISTS (SELECT 1 FROM public.question_versions v WHERE v.tenant_id=question_version_taxa.tenant_id AND v.question_id=question_version_taxa.question_id AND v.id=question_version_taxa.version_id)"
    public = "EXISTS (SELECT 1 FROM public.question_selections s WHERE s.tenant_id=question_version_taxa.tenant_id AND s.version_id=question_version_taxa.version_id AND s.state='approved')"
    op.execute(
        f"CREATE POLICY version_taxon_read ON question_version_taxa FOR SELECT USING (({scope}) AND (({private}) OR ({public})))"
    )
    op.execute(
        f"CREATE POLICY version_taxon_append ON question_version_taxa FOR INSERT WITH CHECK (({scope}) AND ({private}))"
    )
    op.execute("""CREATE FUNCTION taxonomy_term_guard() RETURNS trigger LANGUAGE plpgsql
        SET search_path=pg_catalog, public AS $$
        DECLARE parent public.taxonomy_terms%ROWTYPE;
        BEGIN
            IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Taxonomy history is retained' USING ERRCODE='42501'; END IF;
            PERFORM id FROM public.institutions WHERE id=NEW.tenant_id FOR UPDATE;
            IF TG_OP='UPDATE' THEN
                IF OLD.state <> 'active' OR NEW.revision::bigint <> OLD.revision::bigint+1 OR
                   (to_jsonb(NEW)-'label'-'state'-'revision') IS DISTINCT FROM (to_jsonb(OLD)-'label'-'state'-'revision') THEN
                    RAISE EXCEPTION 'Invalid taxonomy revision' USING ERRCODE='23514'; END IF;
            ELSE
                IF NEW.state <> 'active' OR NEW.revision <> 1 THEN
                    RAISE EXCEPTION 'New terms start active at revision one' USING ERRCODE='23514'; END IF;
            END IF;
            IF NEW.kind='topic' THEN
                SELECT * INTO parent FROM public.taxonomy_terms WHERE tenant_id=NEW.tenant_id AND id=NEW.parent_id;
                IF parent.id IS NULL OR parent.kind <> 'subject' OR (NEW.state='active' AND parent.state <> 'active') THEN
                    RAISE EXCEPTION 'Active subject parent required' USING ERRCODE='23514'; END IF;
            END IF;
            IF NEW.state='retired' AND EXISTS (SELECT 1 FROM public.taxonomy_terms t WHERE t.tenant_id=NEW.tenant_id AND t.parent_id=NEW.id AND t.state='active') THEN
                RAISE EXCEPTION 'Retire active children first' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$""")
    op.execute(
        "CREATE TRIGGER taxonomy_term_guard BEFORE INSERT OR UPDATE OR DELETE ON taxonomy_terms FOR EACH ROW EXECUTE FUNCTION taxonomy_term_guard()"
    )
    op.execute("""CREATE FUNCTION version_taxon_guard() RETURNS trigger LANGUAGE plpgsql
        SET search_path=pg_catalog, public AS $$
        DECLARE term public.taxonomy_terms%ROWTYPE; creation bigint; number integer; revision integer;
        BEGIN
            IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Version classifications are immutable' USING ERRCODE='42501'; END IF;
            SELECT v.created_txid,v.version_number,q.revision INTO creation,number,revision FROM public.question_versions v
                JOIN public.questions q ON q.tenant_id=v.tenant_id AND q.id=v.question_id
                WHERE v.tenant_id=NEW.tenant_id AND v.question_id=NEW.question_id AND v.id=NEW.version_id;
            IF creation IS NULL OR creation <> txid_current() OR number <> revision OR EXISTS
                (SELECT 1 FROM public.question_review_events e WHERE e.tenant_id=NEW.tenant_id AND e.version_id=NEW.version_id) THEN
                RAISE EXCEPTION 'Classification belongs to version creation only' USING ERRCODE='23514'; END IF;
            SELECT * INTO term FROM public.taxonomy_terms WHERE tenant_id=NEW.tenant_id AND id=NEW.term_id AND state='active';
            IF term.id IS NULL THEN RAISE EXCEPTION 'Active local taxonomy required' USING ERRCODE='23514'; END IF;
            IF term.kind='topic' AND NOT EXISTS (SELECT 1 FROM public.question_version_taxa p
                WHERE p.tenant_id=NEW.tenant_id AND p.version_id=NEW.version_id AND p.term_id=term.parent_id AND p.kind_snapshot='subject') THEN
                RAISE EXCEPTION 'Subject snapshot must precede topic' USING ERRCODE='23514'; END IF;
            IF (SELECT count(*) FROM public.question_version_taxa p WHERE p.tenant_id=NEW.tenant_id AND p.version_id=NEW.version_id) >= 64 THEN
                RAISE EXCEPTION 'Too many classification references' USING ERRCODE='23514'; END IF;
            NEW.kind_snapshot:=term.kind; NEW.code_snapshot:=term.code; NEW.label_snapshot:=term.label;
            NEW.parent_id_snapshot:=term.parent_id; NEW.term_revision:=term.revision;
            RETURN NEW;
        END $$""")
    op.execute(
        "CREATE TRIGGER version_taxon_guard BEFORE INSERT OR UPDATE OR DELETE ON question_version_taxa FOR EACH ROW EXECUTE FUNCTION version_taxon_guard()"
    )


def downgrade():
    op.drop_table("question_version_taxa")
    op.drop_table("taxonomy_terms")
    op.execute("DROP FUNCTION version_taxon_guard()")
    op.execute("DROP FUNCTION taxonomy_term_guard()")
    op.drop_constraint("uq_question_versions_taxonomy_binding", "question_versions", type_="unique")
    op.execute(
        "CREATE OR REPLACE FUNCTION question_version_guard() RETURNS trigger LANGUAGE plpgsql\n        SET search_path = pg_catalog, public AS $$\n        DECLARE current_revision integer;\n        BEGIN\n            IF TG_OP <> 'INSERT' THEN\n                RAISE EXCEPTION 'Saved question versions are immutable' USING ERRCODE = '42501';\n            END IF;\n            SELECT q.revision INTO current_revision FROM public.questions q\n                WHERE q.tenant_id = NEW.tenant_id AND q.id = NEW.question_id FOR UPDATE;\n            IF current_revision IS NULL OR current_revision <> NEW.version_number THEN\n                RAISE EXCEPTION 'Version must match the current revision' USING ERRCODE = '23514';\n            END IF;\n            RETURN NEW;\n        END $$"
    )
    op.drop_column("question_versions", "created_txid")
