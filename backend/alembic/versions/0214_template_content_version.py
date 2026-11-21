"""Vorlagenversion zählt inhaltliche Änderungen (Hinweis «Vorlage wurde geändert»).

template.version stand bisher immer auf 1, die Pill «Vorlagenversion N» im Protokoll sagte also
nichts aus, und ein geplantes Protokoll merkte nicht, dass sich seine Vorlage geändert hatte.
Ab jetzt zählen Trigger die Version hoch, sobald sich der Inhalt der Vorlage ändert:

- template_element: Traktandum hinzugefügt, entfernt oder geändert (Baustein, Reihenfolge,
  Name, Sichtbarkeit, Konfiguration/Verhalten);
- element_definition: Titel, Beschreibung oder Blöcke eines verwendeten Bausteins geändert
  (zählt für jede Vorlage desselben Mandanten, die ihn verwendet).

Ein Trigger statt Anwendungscode, damit jeder Schreibpfad erfasst ist (wie 0149). Speichern
ohne Änderung zählt nicht (IS DISTINCT FROM). Höchstens eine Erhöhung je Vorlage und
Transaktion (Markierung über eine transaktionslokale Einstellung), damit z. B. Umsortieren
mehrerer Traktanden nur eine Version ergibt. Vorlagen ohne Protokolle zählen nicht: dort gibt
es nichts zu vergleichen, und Klon/Import (Vorlage samt Elementen neu angelegt) behalten die
übernommene Version.

protocol.template_version (Version beim Erstellen bzw. letzten Abgleich) gibt es schon; keine
neue Spalte, keine neue Tabelle (RLS unverändert).

Revision ID: 0214_template_content_version
Revises: 0212_maintenance_public_update
Create Date: 2026-11-21
"""

from alembic import op

revision = "0214_template_content_version"
down_revision = "0212_maintenance_public_update"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION public.template_bump_content_version(p_template_id bigint) RETURNS void
        LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
        DECLARE
          marker text := 'hocx.template_version_bumped_' || p_template_id;
        BEGIN
          IF p_template_id IS NULL OR current_setting(marker, true) = '1' THEN
            RETURN;
          END IF;
          UPDATE public.template t SET version = t.version + 1
           WHERE t.id = p_template_id
             AND EXISTS (SELECT 1 FROM public.protocol p WHERE p.template_id = t.id);
          IF FOUND THEN
            PERFORM set_config(marker, '1', true);
          END IF;
        END
        $$
    """)
    # Nur die App (und der Eigentümer) ruft die Hilfsfunktion auf, nicht Abgabebox/Foto-Worker
    op.execute("REVOKE ALL ON FUNCTION public.template_bump_content_version(bigint) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.template_bump_content_version(bigint) TO hocx_app")
    op.execute("""
        CREATE FUNCTION public.template_element_content_changed() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
        BEGIN
          IF TG_OP = 'UPDATE' AND NOT (
               NEW.template_id IS DISTINCT FROM OLD.template_id
            OR NEW.element_definition_id IS DISTINCT FROM OLD.element_definition_id
            OR NEW.sort_index IS DISTINCT FROM OLD.sort_index
            OR NEW.section_name IS DISTINCT FROM OLD.section_name
            OR NEW.section_order IS DISTINCT FROM OLD.section_order
            OR NEW.is_required IS DISTINCT FROM OLD.is_required
            OR NEW.is_visible IS DISTINCT FROM OLD.is_visible
            OR NEW.export_visible IS DISTINCT FROM OLD.export_visible
            OR NEW.configuration_json IS DISTINCT FROM OLD.configuration_json
          ) THEN
            RETURN NULL;
          END IF;
          IF TG_OP <> 'DELETE' THEN
            PERFORM public.template_bump_content_version(NEW.template_id);
          END IF;
          IF TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND NEW.template_id IS DISTINCT FROM OLD.template_id) THEN
            PERFORM public.template_bump_content_version(OLD.template_id);
          END IF;
          RETURN NULL;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_template_element_content_version
        AFTER INSERT OR UPDATE OR DELETE ON public.template_element
        FOR EACH ROW EXECUTE FUNCTION public.template_element_content_changed()
    """)
    op.execute("""
        CREATE FUNCTION public.element_definition_content_changed() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
        DECLARE
          tid bigint;
        BEGIN
          IF NOT (
               NEW.title IS DISTINCT FROM OLD.title
            OR NEW.display_title IS DISTINCT FROM OLD.display_title
            OR NEW.description IS DISTINCT FROM OLD.description
            OR NEW.element_type_id IS DISTINCT FROM OLD.element_type_id
            OR NEW.configuration_json IS DISTINCT FROM OLD.configuration_json
          ) THEN
            RETURN NULL;
          END IF;
          -- Nur Vorlagen desselben Mandanten (inkonsistenter Altbestand fremder Traktanden zählt nicht)
          FOR tid IN
            SELECT DISTINCT te.template_id
              FROM public.template_element te
              JOIN public.template t ON t.id = te.template_id
             WHERE te.element_definition_id = NEW.id AND t.tenant_id = NEW.tenant_id
          LOOP
            PERFORM public.template_bump_content_version(tid);
          END LOOP;
          RETURN NULL;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_element_definition_content_version
        AFTER UPDATE ON public.element_definition
        FOR EACH ROW EXECUTE FUNCTION public.element_definition_content_changed()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_element_definition_content_version ON public.element_definition")
    op.execute("DROP TRIGGER IF EXISTS trg_template_element_content_version ON public.template_element")
    op.execute("DROP FUNCTION IF EXISTS public.element_definition_content_changed()")
    op.execute("DROP FUNCTION IF EXISTS public.template_element_content_changed()")
    op.execute("DROP FUNCTION IF EXISTS public.template_bump_content_version(bigint)")
