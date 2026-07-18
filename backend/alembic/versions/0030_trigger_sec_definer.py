"""add SECURITY DEFINER to submission todo sync trigger"""

revision = "0030_trigger_sec_definer"
down_revision = "0029_submission_todo_trigger"

from alembic import op


def upgrade():
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_todo_status_on_submission_upload()
        RETURNS TRIGGER AS $$
        DECLARE
            v_element_ref TEXT;
        BEGIN
            IF NEW.event_id IS NOT NULL THEN
                v_element_ref := 'event-' || NEW.event_id::TEXT;
            ELSIF NEW.list_entry_id IS NOT NULL THEN
                v_element_ref := 'entry-' || NEW.list_entry_id::TEXT;
            ELSE
                RETURN NEW;
            END IF;

            IF NEW.status = 'submitted' THEN
                UPDATE protocol_todo
                SET todo_status_id = 3,
                    completed_at = NOW()
                WHERE submission_assignment_id = NEW.assignment_id
                  AND element_ref = v_element_ref
                  AND todo_status_id <> 3;
            ELSIF NEW.status = 'reopened' THEN
                UPDATE protocol_todo
                SET todo_status_id = 1,
                    completed_at = NULL
                WHERE submission_assignment_id = NEW.assignment_id
                  AND element_ref = v_element_ref
                  AND todo_status_id <> 1;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER;
    """)


def downgrade():
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_todo_status_on_submission_upload()
        RETURNS TRIGGER AS $$
        DECLARE
            v_element_ref TEXT;
        BEGIN
            IF NEW.event_id IS NOT NULL THEN
                v_element_ref := 'event-' || NEW.event_id::TEXT;
            ELSIF NEW.list_entry_id IS NOT NULL THEN
                v_element_ref := 'entry-' || NEW.list_entry_id::TEXT;
            ELSE
                RETURN NEW;
            END IF;

            IF NEW.status = 'submitted' THEN
                UPDATE protocol_todo
                SET todo_status_id = 3,
                    completed_at = NOW()
                WHERE submission_assignment_id = NEW.assignment_id
                  AND element_ref = v_element_ref
                  AND todo_status_id <> 3;
            ELSIF NEW.status = 'reopened' THEN
                UPDATE protocol_todo
                SET todo_status_id = 1,
                    completed_at = NULL
                WHERE submission_assignment_id = NEW.assignment_id
                  AND element_ref = v_element_ref
                  AND todo_status_id <> 1;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
