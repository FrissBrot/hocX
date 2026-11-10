"""Nur noch S3: der Dateisystem-Speicher (Generation 0, bisheriger Bestand vor 1.2) entfällt.

Ab dieser Version liest und schreibt hocX Dateien ausschliesslich über einen S3-kompatiblen
Objektspeicher (lokales Garage oder externer Anbieter). Diese Revision ist das Upgrade-Tor:

1. Upgrade-Sperre - bricht mit einer Erklärung ab (die Datenbank bleibt unverändert), wenn
   - noch das Dateisystem aktiv ist, die Instanz aber schon Dateien hat (Erstmigration fehlt),
   - eine Storage-Migration noch offen ist,
   - eine Dateisystem-Generation noch nicht bereinigt ist (Rückfallfrist läuft bzw. Bereinigung
     angefordert/laufend). scripts/deploy.sh fragt vor dem Update, ob die Frist übersprungen
     werden soll, und lässt die Bereinigung vom bisherigen Release ausführen
     (scripts/lib/storage_gate.sh).
2. Neuinstallation (Dateisystem aktiv, aber noch keine einzige Datei): direkt auf das lokale S3
   umstellen - Profil «Lokales S3 (Garage)» aus LOCAL_S3_*, Generation 1 aktiv, Generation 0
   'abandoned'. Ohne LOCAL_S3_* bricht die Migration ab.
3. Das eingebaute Dateisystem-Profil bleibt als Historie (Generationen, Migrationsberichte)
   erhalten, wird aber deaktiviert.

Revision ID: 0168_s3_only
Revises: 0167_kreide_spacing
Create Date: 2026-11-10
"""

from alembic import op
from sqlalchemy import text

revision = "0168_s3_only"
down_revision = "0167_kreide_spacing"
branch_labels = None
depends_on = None

LOCAL_PROFILE_NAME = "Lokales S3 (Garage)"

HINT_SKIP = (
    "scripts/deploy.sh fragt vor dem Update, ob die Rückfallfrist übersprungen werden soll "
    "(nicht interaktiv: HOCX_SKIP_STORAGE_FALLBACK=1), und lässt die Bereinigung vom bisherigen "
    "Release ausführen. Alternativ im Adminportal (System → Storage) die Generation nach Ablauf "
    "der Frist bereinigen."
)


class S3OnlyUpgradeBlocked(RuntimeError):
    """Upgrade nicht möglich - die Meldung erklärt, was vorher zu tun ist."""


def _scalar(conn, sql: str, **params):
    return conn.execute(text(sql), params).scalar()


def _is_fresh(conn) -> bool:
    """Noch keine einzige Datei: weder registrierte Objekte noch Datei-Verweise in der Datenbank
    (Demo-Daten legen Mandanten, aber keine Dateien an)."""
    return not any(
        _scalar(conn, sql)
        for sql in (
            "SELECT EXISTS (SELECT 1 FROM storage_object)",
            "SELECT EXISTS (SELECT 1 FROM stored_file)",
            "SELECT EXISTS (SELECT 1 FROM document_asset)",
            "SELECT EXISTS (SELECT 1 FROM tenant WHERE profile_image_path IS NOT NULL)",
        )
    )


def _bootstrap_local_s3(conn, filesystem_profile_id: int) -> None:
    from app.core.config import settings
    from app.core.objstore_client import encrypt_credential

    required = (settings.local_s3_endpoint, settings.local_s3_bucket, settings.local_s3_access_key, settings.local_s3_secret_key)
    if not all(required):
        raise S3OnlyUpgradeBlocked(
            "Neuinstallation: hocX speichert Dateien nur noch in S3, LOCAL_S3_ENDPOINT, LOCAL_S3_BUCKET, "
            "LOCAL_S3_ACCESS_KEY und LOCAL_S3_SECRET_KEY sind aber nicht vollständig gesetzt "
            "(scripts/lib/env_migrate.sh erzeugt sie)."
        )
    key = settings.storage_credentials_key

    def enc(value: str) -> str | None:
        return encrypt_credential(value or None, key)

    profile_id = _scalar(conn, "SELECT id FROM storage_profile WHERE provider = 'garage_local' AND is_builtin")
    values = {
        "name": LOCAL_PROFILE_NAME,
        "endpoint_url": settings.local_s3_endpoint.rstrip("/"),
        "region": settings.local_s3_region or "garage",
        "bucket": settings.local_s3_bucket,
        "abgabebox_bucket": settings.local_s3_abgabebox_bucket or None,
        "access_key_enc": enc(settings.local_s3_access_key),
        "secret_key_enc": enc(settings.local_s3_secret_key),
        "restricted_access_key_enc": enc(settings.local_s3_abgabebox_access_key),
        "restricted_secret_key_enc": enc(settings.local_s3_abgabebox_secret_key),
        "data_location": settings.hocx_server_location or None,
    }
    if profile_id is not None:
        # Ein schon vorhandenes eingebautes Profil (noch nie aktiv, die Instanz hat keine Dateien)
        # wird auf die aktuellen LOCAL_S3_*-Werte gebracht statt ungeprüft übernommen.
        conn.execute(
            text(
                """
                UPDATE storage_profile SET endpoint_url = :endpoint_url, region = :region, bucket = :bucket,
                       abgabebox_bucket = :abgabebox_bucket, access_key_enc = :access_key_enc,
                       secret_key_enc = :secret_key_enc, restricted_access_key_enc = :restricted_access_key_enc,
                       restricted_secret_key_enc = :restricted_secret_key_enc, is_enabled = true,
                       config_version = config_version + 1, updated_at = NOW()
                WHERE id = :id
                """
            ),
            {**{key: value for key, value in values.items() if key not in ("name", "data_location")}, "id": profile_id},
        )
    else:
        profile_id = _scalar(
            conn,
            """
            INSERT INTO storage_profile (name, provider, endpoint_url, region, bucket, abgabebox_bucket, prefix,
                                         addressing_style, access_key_enc, secret_key_enc, restricted_access_key_enc,
                                         restricted_secret_key_enc, tls_verify, is_builtin, data_location)
            VALUES (:name, 'garage_local', :endpoint_url, :region, :bucket, :abgabebox_bucket, 'hocx', 'path',
                    :access_key_enc, :secret_key_enc, :restricted_access_key_enc, :restricted_secret_key_enc,
                    false, true, :data_location)
            RETURNING id
            """,
            **values,
        )
    # Zuerst die leere Dateisystem-Generation schliessen: es darf nur eine aktive geben
    # (uq_storage_generation_active).
    conn.execute(
        text(
            "UPDATE storage_generation SET status = 'abandoned', deactivated_at = NOW() "
            "WHERE profile_id = :fs AND status NOT IN ('purged', 'abandoned')"
        ),
        {"fs": filesystem_profile_id},
    )
    generation = _scalar(conn, "SELECT COALESCE(MAX(generation), 0) + 1 FROM storage_generation")
    conn.execute(
        text(
            "INSERT INTO storage_generation (profile_id, generation, status, activated_at, object_count, total_bytes) "
            "VALUES (:profile_id, :generation, 'active', NOW(), 0, 0)"
        ),
        {"profile_id": profile_id, "generation": generation},
    )
    conn.execute(
        text(
            "UPDATE storage_state SET active_profile_id = :profile_id, active_generation = :generation, "
            "write_fenced = false, fence_reason = NULL, fenced_at = NULL, updated_at = NOW() WHERE id = 1"
        ),
        {"profile_id": profile_id, "generation": generation},
    )


def upgrade() -> None:
    conn = op.get_bind()
    active = conn.execute(
        text(
            "SELECT p.id, p.provider FROM storage_state s JOIN storage_profile p ON p.id = s.active_profile_id WHERE s.id = 1"
        )
    ).first()
    open_migration = _scalar(
        conn,
        "SELECT kind || ' (' || state || ')' FROM storage_migration "
        "WHERE state NOT IN ('completed', 'failed', 'cancelled') LIMIT 1",
    )
    if open_migration:
        raise S3OnlyUpgradeBlocked(
            f"Upgrade gesperrt: Storage-Migration {open_migration} ist noch offen. Erst abschliessen oder abbrechen "
            "(Adminportal → System → Storage), dann erneut deployen."
        )

    if active is not None and active.provider == "filesystem":
        if not _is_fresh(conn):
            raise S3OnlyUpgradeBlocked(
                "Upgrade gesperrt: hocX speichert ab dieser Version nur noch in S3, die Dateien liegen aber noch im "
                "Dateisystem. Zuerst mit dem bisherigen Release (1.2.x) die Erstmigration ausführen "
                "(Adminportal → System → Storage → Migration vorbereiten, Ziel «Lokales S3»), dann erneut deployen."
            )
        _bootstrap_local_s3(conn, active.id)

    pending = conn.execute(
        text(
            "SELECT g.generation, g.status, g.retain_until FROM storage_generation g "
            "JOIN storage_profile p ON p.id = g.profile_id "
            "WHERE p.provider = 'filesystem' AND g.status NOT IN ('purged', 'abandoned') ORDER BY g.generation"
        )
    ).all()
    if pending:
        details = ", ".join(
            f"g{row.generation} {row.status}"
            + (f" bis {row.retain_until:%d.%m.%Y %H:%M} UTC" if row.retain_until is not None else "")
            for row in pending
        )
        raise S3OnlyUpgradeBlocked(
            f"Upgrade gesperrt: der bisherige Dateisystem-Bestand ist noch nicht bereinigt ({details}). " + HINT_SKIP
        )

    conn.execute(text("UPDATE storage_profile SET is_enabled = false, updated_at = NOW() WHERE provider = 'filesystem'"))


def downgrade() -> None:
    # Bewusst ohne Rückweg zum Dateisystem: die Dateien liegen nur noch in S3. Das Profil wird
    # wieder aktiviert, damit ältere Releases ihre Historie anzeigen können.
    op.execute("UPDATE storage_profile SET is_enabled = true WHERE provider = 'filesystem'")
