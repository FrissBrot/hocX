"""Core-Tabellendefinitionen fuer den restricted DB-Zugriff dieses Service.

Bewusst NICHT als ORM-Klassen (kein Base/Mapped) und NICHT per Reflection geladen,
sondern als schlanke sa.Table()-Objekte mit genau den Spalten, die die restricted
Postgres-Rolle 'hocx_abgabebox' lesen/schreiben darf (siehe
backend/alembic/versions/0020_abgabebox.py fuer die GRANT-Statements). Kein ORM-Mapping,
weil db.refresh()/db.get() intern SELECT braucht, das diese Rolle auf einigen Tabellen
(stored_file, submission_upload_file) nicht hat - siehe app/repository.py.
"""

from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, Integer, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

tenant_table = Table(
    "tenant",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("name", Text),
    Column("public_slug", Text),
)

submission_assignment_table = Table(
    "submission_assignment",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("tenant_id", BigInteger),
    Column("title", Text),
    Column("description", Text),
    Column("public_slug", Text),
    Column("source_type", Text),
    Column("tag_filter", Text),
    Column("offset_days_before", Integer),
    Column("offset_days_after", Integer),
    Column("list_definition_id", BigInteger),
    Column("deadline", Date),
    Column("allowed_file_types", JSONB),
    Column("max_files_per_element", Integer),
    Column("max_file_size_mb", Integer),
    Column("is_active", Boolean),
)

event_table = Table(
    "event",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("tenant_id", BigInteger),
    Column("event_date", Date),
    Column("event_end_date", Date),
    Column("tag", Text),
    Column("title", Text),
)

list_definition_table = Table(
    "list_definition",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("tenant_id", BigInteger),
    Column("name", Text),
    Column("column_one_title", Text),
    Column("column_one_value_type", Text),
    Column("column_two_title", Text),
    Column("column_two_value_type", Text),
    Column("is_active", Boolean),
)

list_entry_table = Table(
    "list_entry",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("list_definition_id", BigInteger),
    Column("sort_index", Integer),
    Column("column_one_value_json", JSONB),
    Column("column_two_value_json", JSONB),
)

participant_table = Table(
    "participant",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("first_name", Text),
    Column("last_name", Text),
    Column("display_name", Text),
)

# submission_upload: die restricted Rolle darf NUR (id, assignment_id, event_id,
# list_entry_id, status) lesen - bewusst kein submitted_at im SELECT-Grant. Fuer INSERT
# ist die gesamte Tabelle freigegeben (separate Privilegien in Postgres), submitted_at
# wird also beim Insert mitgeschrieben, aber nie zurückgelesen.
submission_upload_table = Table(
    "submission_upload",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("assignment_id", BigInteger),
    Column("event_id", BigInteger),
    Column("list_entry_id", BigInteger),
    Column("status", Text),
    Column("submitted_at", DateTime(timezone=True)),
)

submission_upload_file_table = Table(
    "submission_upload_file",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("upload_id", BigInteger),
    Column("stored_file_id", BigInteger),
    Column("sort_index", Integer),
)

submission_upload_log_table = Table(
    "submission_upload_log",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("assignment_id", BigInteger),
    Column("element_ref", Text),
    Column("status", Text),
    Column("error_message", Text),
    Column("created_at", DateTime(timezone=True)),
)

# stored_file: nur INSERT-Grant, absichtlich KEIN SELECT - siehe Migration 0020.
stored_file_table = Table(
    "stored_file",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("tenant_id", BigInteger),
    Column("original_name", Text),
    Column("mime_type", Text),
    Column("storage_path", Text),
    Column("file_size_bytes", BigInteger),
    Column("checksum_sha256", Text),
    Column("scan_status", Text),
)
