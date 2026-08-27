"""public_id: grants the restricted abgabebox-backend role (hocx_abgabebox) SELECT on the
new public_id column for tables whose grant is column-restricted rather than table-wide.

Cross-checked against every table hocx_abgabebox can read (0020_abgabebox.py,
0023_abgabebox_select_grants.py):

- event, list_definition, list_entry: table-wide SELECT since 0020 - public_id is already
  covered, no grant needed here.
- tenant, submission_assignment, submission_upload, submission_upload_file, stored_file:
  table-wide SELECT since 0023 (superseding 0020's narrower column lists for these five) -
  also already covered.
- participant: still column-restricted to (id, first_name, last_name, display_name) from
  0020, never widened - the only one that actually needs a new GRANT for public_id, needed
  so abgabebox-backend's element_resolver.py can build participant-independent labels
  without leaking the sequential internal id (see element_resolver.py's element_ref switch
  to public_id in the same change that added this migration).

Revision ID: 0069_abgabebox_public_id_grant
Revises: 0068_public_id_constraints
Create Date: 2026-08-26
"""

from alembic import op

revision = "0069_abgabebox_public_id_grant"
down_revision = "0068_public_id_constraints"
branch_labels = None
depends_on = None

ROLE_NAME = "hocx_abgabebox"


def upgrade() -> None:
    op.execute(f"GRANT SELECT (public_id) ON participant TO {ROLE_NAME}")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT (public_id) ON participant FROM {ROLE_NAME}")
