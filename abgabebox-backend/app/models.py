"""Core-Tabellendefinitionen fuer den restricted DB-Zugriff dieses Service.

Bewusst NICHT als ORM-Klassen (kein Base/Mapped) und NICHT per Reflection geladen,
sondern als schlanke sa.Table()-Objekte mit genau den Spalten, die die restricted
Postgres-Rolle 'hocx_abgabebox' lesen/schreiben darf (siehe
backend/alembic/versions/0020_abgabebox.py fuer die GRANT-Statements). Kein ORM-Mapping,
weil db.refresh()/db.get() intern ein SELECT auf die volle Zeile braucht, das ueber die
gezielten Spalten-Grants dieser Rolle hinausgehen wuerde - siehe app/repository.py.

Hinweis stored_file/submission_upload_file: urspruenglich (Migration 0020) nur mit
INSERT-Grant gedacht, seit Migration 0023_abgabebox_select_grants aber tabellenweit
per SELECT lesbar - die Spaltenlisten hier bilden also nicht mehr die tatsaechlichen
DB-Grants ab, sondern nur die Spalten, die dieser Service kennt/braucht.
"""

from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, Float, Integer, MetaData, SmallInteger, Table, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

# submission_link/submission_assignment_link: der Zugang zur Abgabebox. Das Token in der URL ist
# die Authentifizierung - darueber wird Mandant und die freigegebene Abgabenmenge bestimmt. Die
# restricted Rolle darf nur (id, tenant_id, token) bzw. (assignment_id, link_id) lesen, nie
# name/is_default/Zeitstempel, und nichts schreiben (siehe Migration 0075_submission_link).
# Der Mandant selbst (tenant-Tabelle, public_slug) wird hier bewusst NICHT mehr gelesen - der
# Mandanten-Slug ist keine Zugangsberechtigung mehr.
submission_link_table = Table(
    "submission_link",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("tenant_id", BigInteger),
    Column("token", Text),
)

submission_assignment_link_table = Table(
    "submission_assignment_link",
    metadata,
    Column("assignment_id", BigInteger, primary_key=True),
    Column("link_id", BigInteger, primary_key=True),
)

# Feature-Gating (0085_plan_pricing): die restricted Rolle darf nur pruefen, ob ein
# Mandant 'abgabebox' gebucht hat - column-level SELECT auf (tenant_id, feature_code), nie
# id/enabled_at/enabled_by_admin_id. Die echte Tabelle hat eine eigene id-Spalte als PK
# (siehe Migration 0084) - hier absichtlich nicht abgebildet, diese Spalten-Teilmenge wird nie
# per db.get()/db.refresh() angesprochen (siehe Modul-Docstring oben).
tenant_feature_table = Table(
    "tenant_feature",
    metadata,
    Column("tenant_id", BigInteger),
    Column("feature_code", Text),
    # 'full' oder 'read_only' (0158_feature_entitlements): nur volle Buchung nimmt Uploads an
    Column("access", Text),
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
    Column("cycle_config_id", BigInteger),
    Column("cycle_offsets", JSONB),
    Column("list_definition_id", BigInteger),
    Column("deadline", Date),
    Column("allowed_file_types", JSONB),
    Column("max_files_per_element", Integer),
    Column("max_file_size_mb", Integer),
    Column("is_active", Boolean),
    Column("sort_order", Text),
    Column("auto_close", Text),
    Column("keep_open_after_end", Boolean),
    # Migration 0182: nach dem Zurückziehen nur noch über den persönlichen Link (Haupt-Backend)
    Column("owner_resubmit_only_personal", Boolean),
)

# cycle_config/event_cycle: nur fuer den Zyklus-Filter der Termin-Abgaben. Spalten-SELECT
# (id, reset_month, reset_day) bzw. (event_id, cycle_config_id, cycle_year), siehe Migration
# 0079_submission_cycle_filter - nie name/name_pattern.
cycle_config_table = Table(
    "cycle_config",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("reset_month", Integer),
    Column("reset_day", Integer),
)

event_cycle_table = Table(
    "event_cycle",
    metadata,
    Column("event_id", BigInteger, primary_key=True),
    Column("cycle_config_id", BigInteger, primary_key=True),
    Column("cycle_year", Integer, primary_key=True),
)

event_table = Table(
    "event",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("public_id", UUID(as_uuid=True)),
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
    # Spalten liegen seit 0186 in list_column; label_column_id ist die Rolle «Bezeichnung»
    Column("label_column_id", BigInteger),
    Column("is_active", Boolean),
)

list_column_table = Table(
    "list_column",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("list_definition_id", BigInteger),
    Column("key", Text),
    Column("value_type", Text),
    Column("sort_index", Integer),
)

list_entry_table = Table(
    "list_entry",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("public_id", UUID(as_uuid=True)),
    Column("list_definition_id", BigInteger),
    Column("sort_index", Integer),
    # Werte je Spalten-Key (list_column.key), Migration 0186
    Column("values_json", JSONB),
)

# Seit 0108 sind Teilnehmer Zeilen in app_user; hocx_abgabebox darf dort nur diese Spalten
# lesen (Grant in 0109_abgabebox_participant_grant.py), keine Login-/Kontodaten.
participant_table = Table(
    "app_user",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("public_id", UUID(as_uuid=True)),
    Column("first_name", Text),
    Column("last_name", Text),
    Column("display_name", Text),
)

# Von Hand angelegte Elemente einer Einzelabgabe (Migration 0198). Nur lesend und nur diese
# Spalten (Spalten-Grant), keine Verantwortlichen; RLS: nur der Mandant des gesetzten Links.
submission_manual_element_table = Table(
    "submission_manual_element",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("public_id", UUID(as_uuid=True)),
    Column("tenant_id", BigInteger),
    Column("assignment_id", BigInteger),
    Column("is_default", Boolean),
    Column("name", Text),
    Column("window_start", Date),
    Column("window_end", Date),
    Column("sort_index", Integer),
)

# submission_upload: die restricted Rolle darf NUR (id, assignment_id, event_id,
# list_entry_id, manual_element_id, status) lesen - bewusst kein submitted_at im SELECT-Grant.
# Fuer INSERT ist die gesamte Tabelle freigegeben (separate Privilegien in Postgres), submitted_at
# wird also beim Insert mitgeschrieben, aber nie zurückgelesen.
submission_upload_table = Table(
    "submission_upload",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("assignment_id", BigInteger),
    Column("event_id", BigInteger),
    Column("list_entry_id", BigInteger),
    # Element einer Einzelabgabe (0198); NULL beim Standard-Element «manual»
    Column("manual_element_id", BigInteger),
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
    # Über den persönlichen Link zurückgezogen (Migration 0181): zählt nicht mehr
    Column("withdrawn_at", DateTime(timezone=True)),
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
    # Upload-Verlauf (Backend-Migration 0254): je abgelehnter oder doppelter Datei eine Zeile mit
    # Grund; ein DB-Trigger macht daraus eine Zeile im Vorgang. Nur INSERT, kein neues Recht.
    Column("request_ref", UUID(as_uuid=True)),
    Column("upload_id", BigInteger),
    Column("reason_code", Text),
    Column("file_name", Text),
    Column("file_size", BigInteger),
)

# stored_file: INSERT tabellenweit (Migration 0020), SELECT tabellenweit seit Migration
# 0023_abgabebox_select_grants - siehe Hinweis im Modul-Docstring oben.
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
    # Ursprünglicher Hash, wenn hocX die Datei später umgeschrieben hat (korrigiertes
    # Aufnahmedatum, Backend-Migration 0203) - nur gelesen (Duplikatprüfung).
    Column("source_checksum_sha256", Text),
    Column("perceptual_hash", Text),
    Column("scan_status", Text),
    # Bild-Metadaten (Migration 0113, siehe app/image_metadata.py) - nur beim INSERT gesetzt.
    Column("exif_taken_at", DateTime(timezone=True)),
    Column("exif_taken_offset", Text),
    Column("exif_taken_source", Text),
    Column("gps_latitude", Float),
    Column("gps_longitude", Float),
    Column("gps_altitude_m", Float),
    Column("gps_direction_deg", Float),
    Column("gps_source", Text),
    Column("camera_make", Text),
    Column("camera_model", Text),
    Column("orientation", SmallInteger),
    Column("metadata_scanned_at", DateTime(timezone=True)),
    Column("metadata_scan_status", Text),
)

# system_error_log: nur INSERT-Grant, absichtlich KEIN SELECT - siehe Migration 0039.
# Fehler dieses Service landen hier nur zur Sichtung im Platform-Admin-Panel, dieser
# restricted Service kann/darf sie nie selbst wieder auslesen. Deshalb hier ohne Primärschlüssel
# und ohne RETURNING: sonst holt SQLAlchemy die neue id per «RETURNING id» (braucht SELECT) bzw.
# «nextval(...)» (braucht USAGE auf die Sequenz), und jeder Eintrag scheiterte still mit
# «permission denied» (_record_error verschluckt das). Die id vergibt die Identity-Spalte selbst.
system_error_log_table = Table(
    "system_error_log",
    metadata,
    Column("id", BigInteger),  # bewusst ohne primary_key, siehe oben
    Column("source", Text),
    Column("tenant_id", BigInteger),
    Column("actor_email", Text),
    Column("request_method", Text),
    Column("request_path", Text),
    Column("status_code", Integer),
    Column("error_type", Text),
    Column("error_message", Text),
    Column("traceback", Text),
    implicit_returning=False,
)
