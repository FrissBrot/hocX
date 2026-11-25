import os
import secrets
import sys
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULTS = {
    "hocx-local-dev-secret",
    "hocx-local-dev-admin-secret",
    "change-me-to-a-random-32-plus-char-value",
    "change-me-to-a-different-random-32-plus-char-value",
    "changeme",
    "secret",
    "",
}


def _load_file_secrets() -> None:
    """Resolve Docker-style VAR_FILE inputs without exposing values in Config.Env."""
    for variable in (
        "DATABASE_URL", "APP_DATABASE_URL", "AUTH_SECRET", "AUTH_SECRET_PREVIOUS", "ADMIN_AUTH_SECRET", "INITIAL_ADMIN_PASSWORD",
        "STORAGE_CREDENTIALS_KEY", "LOCAL_S3_SECRET_KEY", "LOCAL_S3_ABGABEBOX_SECRET_KEY", "REDIS_PASSWORD",
        "EXPORT_ENCRYPTION_KEY", "ADMIN_GATE_SECRET", "GEO_DATABASE_URL",
        # Datei-Import aus der Cloud (services/cloud_import, Plan 2026-11-21 §12.1)
        "CLOUD_IMPORT_TOKEN_KEY", "CLOUD_IMPORT_TOKEN_KEY_PREVIOUS", "CLOUD_IMPORT_MS_CLIENT_SECRET",
        "CLOUD_IMPORT_GOOGLE_CLIENT_SECRET",
    ):
        file_variable = f"{variable}_FILE"
        if variable not in os.environ and (path := os.environ.get(file_variable)):
            os.environ[variable] = Path(path).read_text(encoding="utf-8").rstrip("\r\n")


_load_file_secrets()


# Werte von HOCX_ENVIRONMENT, die als Produktion gelten (kanonisch: 'production').
PRODUCTION_ENVIRONMENT_NAMES = frozenset({"production", "prod"})

# Prozessarten ohne Anmelde-/Admin-Sitzungen (HOCX_PROCESS_KIND). Sie bekommen AUTH_SECRET und
# ADMIN_AUTH_SECRET nicht (Least Privilege: der document-worker verarbeitet nicht
# vertrauenswürdige Dateien) und erhalten stattdessen zufällige Werte je Prozess - damit lässt
# sich nichts signieren, was das Backend anerkennt, und ein versehentliches Entschlüsseln mit
# secret_crypto schlägt sichtbar fehl.
SECRETLESS_PROCESS_KINDS = frozenset({"document-worker"})
# Prozesse ohne Anmeldesitzungen, die aber ADMIN_AUTH_SECRET für secret_crypto brauchen (z. B.
# Passwörter der Vereinsexporte): bekommen nur für AUTH_SECRET einen Zufallswert - damit lassen
# sich keine Session-Cookies signieren (job-worker verarbeitet nicht vertrauenswürdige Uploads).
SESSIONLESS_PROCESS_KINDS = frozenset({"job-worker"})


class Settings(BaseSettings):
    app_name: str = "hocX API"
    # docker-compose.yml/docker-compose.release.yml set HOCX_ENVIRONMENT (matching the
    # HOCX_* naming every other operator-facing variable uses, see scripts/lib/env.sh's
    # allowlist) - without this alias pydantic-settings looks for a bare ENVIRONMENT, which
    # nothing ever sets, so this silently stayed on the "production" default in every
    # environment including local dev. Harmless before the demo-data production guard below
    # existed; now it makes that guard fire in dev too, since INITIAL_ADMIN_EMAIL there is
    # an @hocx.local address. Mirrors abgabebox-backend/app/config.py's Settings.environment.
    environment: str = Field(default="production", validation_alias="HOCX_ENVIRONMENT")
    # Art des Prozesses (backend, document-worker, ...), siehe SECRETLESS_PROCESS_KINDS.
    process_kind: str = Field(default="backend", validation_alias="HOCX_PROCESS_KIND")
    # Admin/migration connection (superuser role) - used by alembic (see alembic/env.py).
    database_url: str = "postgresql+psycopg://hocx:hocx@db:5432/hocx"
    # Runtime connection for the FastAPI app itself, using the least-privilege
    # 'hocx_app' role (see alembic/versions/0070_restrict_app_db_role.py) instead of the
    # superuser role above - audit finding, 2026-08-26: previously the app served every
    # request as Postgres superuser, so a SQL-injection bug or a compromised backend
    # process would have had full control over the whole Postgres server (all databases,
    # CREATE ROLE, RLS bypass, ...), not just this app's tables. Falls back to
    # database_url when unset so existing local/CI setups that only define DATABASE_URL
    # keep working unchanged.
    app_database_url: str = ""
    storage_root: str = "/app/storage"
    export_root: str = "/app/storage/exports"
    upload_root: str = "/app/storage/uploads"
    thumbnail_root: str = "/app/storage-local/thumbnails"
    abgabebox_storage_root: str = "/app/abgabebox-storage"
    abgabebox_base_url: str = "https://upload.example.com"
    traefik_domain: str | None = None
    traefik_abgabebox_domain: str | None = None
    # Domain des Plattform-Admin-Panels: erwarteter WebAuthn-Origin der Admin-Passkeys (SEC-021).
    traefik_admin_domain: str | None = None
    # Docs- und Website-Domain: nur, damit sie nie als Mandanten-Domain eingetragen werden können.
    traefik_docs_domain: str | None = None
    traefik_website_domain: str | None = None
    # Extra Origins for CORS (main.py) and the protocol-collaboration WebSocket
    # (collaboration_ws.py's _static_allowed_origins) beyond localhost/127.0.0.1:3000 and
    # traefik_domain - needed whenever a deployment's published port differs from the
    # container-internal port 3000 (e.g. docker-compose.e2e.yml maps the frontend to host
    # port 13000, so the browser's Origin header is "http://127.0.0.1:13000", which the
    # static 3000-only list never matched - this silently 403'd every WS handshake).
    # Comma-separated, e.g. "http://127.0.0.1:13000,https://staging.example.com".
    extra_cors_origins: str = ""
    router_prefix: str = "hocx"
    traefik_middleware_prefix: str = ""
    traefik_dynamic_config_dir: str = "/app/traefik_dynamic"
    domain_health_check_interval_minutes: int = 30
    abgabebox_rescan_interval_minutes: int = 15
    # Shared by the three internal upload paths (protocol image, gallery upload, word
    # import) - one consolidated rescan loop instead of the three that previously existed
    # separately (word_import_rescan_interval_minutes/gallery_upload_rescan_interval_minutes,
    # with protocol images reusing the word-import setting for lack of their own). See
    # FileService.rescan_pending_internal_files / app.core.background_loops.
    upload_pipeline_rescan_interval_minutes: int = 15
    export_cleanup_interval_minutes: int = 1440
    export_retention_days: int = 30
    # Retention sweep for audit_log/system_error_log (audit finding, 2026-08-26: neither
    # table had any cleanup, both grow unbounded forever). audit_log default is
    # deliberately long (~2 years) since it's the compliance/security trail - review
    # against your own legal retention duty before relying on this default.
    log_cleanup_interval_minutes: int = 1440
    audit_log_retention_days: int = 730
    error_log_retention_days: int = 90
    # Verlauf der Job-Läufe für /admin/jobs (system_job_run, siehe job_registry.py) - der aktuelle
    # Stand pro Job in system_job_status bleibt unabhängig davon erhalten.
    job_run_retention_days: int = 30
    # Systemmonitoring (/admin/system, ntfy-Alarme). docker_api_url zeigt auf den
    # docker-socket-proxy (nur Container-Lesezugriff, eigenes internes Netz - siehe Compose);
    # leer = keine Container-Übersicht, die übrigen Prüfungen laufen trotzdem.
    docker_api_url: str | None = None
    system_monitor_interval_seconds: int = 30
    health_event_retention_days: int = 90
    # Fristen für Job-/Ereignistabellen (app/services/retention_service.py, Datenschutz-Audit
    # PRIV-011). 0 schaltet eine Regel ab.
    upload_job_retention_days: int = 30
    submission_upload_log_retention_days: int = 90
    operations_event_retention_days: int = 730
    identity_request_retention_days: int = 365
    word_import_outcome_retention_days: int = 365
    inactive_share_link_retention_days: int = 90
    # Löschjournal: länger als jede Backup-Aufbewahrung (Migration 0144 erzwingt >= 400)
    erasure_journal_retention_days: int = 400
    # Offboarding (Datenschutz-Audit G): Tage nach Vertragsende, bis /admin/system die Löschung des
    # Mandanten anmahnt (Exportfenster für den Verein)
    tenant_offboarding_grace_days: int = 90
    # Datenstandort der Speicherprofile (Datenschutz-Audit E3): Standort dieses Servers für das
    # lokale Profil, und optional erlaubte Standorte (z. B. "ch,eu_eea"; leer = alle)
    hocx_server_location: str = "ch"
    # Gleicher Wert wie in der Abgabebox (dort wird geprüft); hier nur für den Hinweis in
    # /admin/system, ob der EU-Endpunkt von Friendly Captcha aktiv ist (Datenschutz-Audit E2)
    friendly_captcha_verify_url: str = "https://api.friendlycaptcha.com/api/v1/siteverify"
    storage_allowed_locations: str = ""
    # Sicherheitsalarme aus dem Audit-Log (system_health_service._check_security, PRIV-022)
    security_failed_logins_warning: int = 50
    security_failed_logins_critical: int = 200
    security_failed_logins_per_account: int = 20
    security_exports_per_hour: int = 3
    # Auth-Audit 2026-11-20 (Abschnitt 12): Plattform-Anmeldungen sind selten, jede wird gemeldet.
    security_alert_admin_logins: bool = True
    # How often the cycle-snapshot loop checks whether any CycleConfig's reset boundary
    # was crossed since the last snapshot (see main.py's cycle_snapshot_loop and
    # table_snapshot_service.run_due_cycle_snapshots). Daily is enough - a cycle boundary
    # is crossed at most once a year per config, and the loop self-heals a missed day.
    cycle_snapshot_check_interval_minutes: int = 1440
    # Aufgabenpakete: Aufgaben des laufenden Zyklus anlegen/nachführen (siehe main.py's
    # task_package_rollover_loop). Täglich reicht - beim Zuweisen, bei Paket-, Listen- und
    # Terminänderungen wird zusätzlich sofort nachgeführt.
    task_package_rollover_interval_minutes: int = 1440
    # Abgabe-Pendenzen periodisch abgleichen (submission_todo_sync_loop). Termin-, Listen- und
    # Abgabeänderungen gleichen sofort ab; der Job fängt Zykluswechsel und verknüpfte Dateien.
    submission_todo_sync_interval_minutes: int = 15
    # Photo-culling Phase 3 auto-queue (main.py's photo_analysis_auto_queue_loop): how
    # often to check for unanalyzed images, and the UTC hour window it's allowed to queue
    # them in. Default 0/24 = rund um die Uhr - die Analyse läuft automatisch, es gibt keinen
    # manuellen "Analyse starten"-Button mehr; der Last-Check unten bleibt die Bremse.
    # Ein engeres Fenster ist weiterhin möglich (start > end wraps past midnight, e.g.
    # 22/5 means 22:00-05:00 UTC).
    photo_analysis_auto_queue_interval_minutes: int = 5
    photo_analysis_auto_queue_start_hour: int = 0
    photo_analysis_auto_queue_end_hour: int = 24
    # Additional safety gate independent of the time window: skip this run if the host's
    # 1-minute load average is already above cpu_count * this factor. os.getloadavg()
    # reads /proc/loadavg, which reflects the whole Docker host, not just this container -
    # exactly the shared-host signal this needs, not a container-local one.
    photo_analysis_auto_queue_max_load_factor: float = 0.7
    # Photo-culling Phase 1 backfill (main.py's photo_quality_backfill_loop): sharpness/
    # exposure scores are computed inline for protocol-image/gallery uploads, but the
    # abgabebox-backend submission-upload path runs as a separate, minimally-privileged
    # process (see sql/baseline_schema.sql's hocx_abgabebox grants) that never computes
    # them - this loop fills them in afterwards from the trusted backend instead. Cheap
    # per-image (see photo_quality.py's module docstring), so unlike Phase 3 this doesn't
    # need an off-peak time window.
    photo_quality_backfill_interval_minutes: int = 15
    # Vorschaubilder für Abgabebox-Uploads nachziehen (job-worker, CONC-014)
    thumbnail_backfill_interval_minutes: int = 5
    # Kamera-Kürzel für Altfotos nachtragen (services/camera_serial_backfill.py, Migration 0253):
    # Takt und höchstens so viele Dateien je Tick (alle Mandanten zusammen, reihum).
    camera_serial_backfill_interval_minutes: int = 2
    camera_serial_backfill_files_per_tick: int = 200
    # Auto-album sync (main.py's photo_album_sync_loop): folds newly-submitted (and newly
    # removed) abgabebox submission files into their Zyklus/Abgabe/Abgabe-Element albums -
    # same reason as the backfill above, this can't happen inline in the restricted
    # abgabebox-backend request path.
    photo_album_sync_interval_minutes: int = 15
    # Duplikate/Ähnliche vorberechnen (job-worker, FileService.refresh_similarity_results) - neue
    # Fotos erscheinen in den Tabs spätestens nach diesem Takt.
    photo_similarity_refresh_interval_minutes: float = 2
    # Mirrors the abgabebox subapp's ABGABEBOX_TENANT_STORAGE_QUOTA_MB - protocol-image
    # uploads had only a per-file limit (MAX_UPLOAD_BYTES), no per-tenant total at all
    # (audit finding, 2026-08-25), a real risk given this app's two prior disk-full
    # outages. Same 2 GB default.
    protocol_image_storage_quota_mb: int = 2048
    auth_secret: str = "hocx-local-dev-secret"
    auth_session_cookie: str = "hocx_session"
    auth_session_ttl_hours: int = 72
    auth_secure_cookies: bool = True
    # Schlüsselrotation der Sessions (SEC-AUTH-011): der bisherige AUTH_SECRET. Tokens und
    # Geräte-Cookies, die damit signiert sind, gelten bis zu ihrem Ablauf weiter; neue werden nur
    # mit AUTH_SECRET signiert. Leer = keine Rotation im Gang.
    auth_secret_previous: str = ""
    # Übergang auf den Cookie-Namen mit __Host- (SEC-AUTH-018): bis wann der bisherige Name noch
    # gelesen wird (ISO-Datum). Leer = Prozessstart + auth_session_ttl_hours (≈ Deploy + 72 h).
    auth_legacy_cookie_until: str = ""

    # --- Login-Härtung (Auth-Audit 2026-11-20, docs: RUNBOOK «Anmeldeschutz») ----------------
    # Body-Limit für /api/auth/* und /api/admin/auth/* (SEC-AUTH-002); Rest: max_request_body_bytes.
    auth_max_request_body_bytes: int = 16 * 1024
    auth_passkey_max_request_body_bytes: int = 64 * 1024
    # Session-Register (SEC-AUTH-011): Inaktivität und absolute Lebensdauer einer Session;
    # last_seen_at wird höchstens alle auth_session_touch_seconds geschrieben.
    auth_session_idle_minutes: int = 8 * 60
    auth_session_absolute_hours: int = 14 * 24
    auth_session_touch_seconds: int = 300
    # Bekannte Geräte (SEC-AUTH-006): signiertes Cookie nach erfolgreicher Anmeldung.
    auth_device_cookie: str = "hocx_device"
    auth_device_ttl_days: int = 90
    # Schichten des Anmeldeschutzes (Audit Abschnitt 6.3). Fenster 15 min, sofern nicht anders genannt.
    auth_ip_failures_soft: int = 20          # L1 IP exakt: ab hier Prüfung für unbekannte Geräte
    auth_ip_failures_hard: int = 60          # L1: ab hier 429 für unbekannte Geräte dieser IP
    auth_net_failures_soft: int = 60         # L2 /24 bzw. /64 (15 min)
    auth_net_failures_hard_hour: int = 300   # L2 je Stunde: 429 für unbekannte Geräte
    auth_wide_failures_alert_hour: int = 1000  # L3 IPv6 /48 je Stunde: nur Alarm
    auth_account_ip_failures: int = 10       # L4 Konto + IP: 429 für diese Quelle
    auth_account_failures_challenge: int = 30   # L5 Konto: unbekannte Geräte zusätzlich prüfen
    auth_account_failures_known_only: int = 100  # L5 Konto: nur noch bekannte Geräte
    auth_totp_account_limit: int = 10        # L6 TOTP je Konto (atomar)
    auth_totp_drip_seconds: int = 60         # danach ein Versuch je Minute
    auth_passkey_account_limit: int = 30     # L6 Passkey je Konto
    auth_global_attack_min: int = 100        # L7 Angriffsmodus: mindestens so viele Fehlversuche
    auth_global_attack_factor: float = 5.0   # ... und so viel mal die gewohnte Rate
    auth_tenant_accounts_alert: int = 20     # L8 verschiedene Konten eines Mandanten mit Fehlversuchen
    # Versuche je Quelle (unabhängig vom Ergebnis), GCRA in der App - gilt auch auf Mandanten-Domains.
    auth_ip_attempts_per_minute: int = 30
    auth_ip_attempts_burst: int = 15
    auth_net_attempts_per_minute: int = 120
    auth_net_attempts_burst: int = 60
    # IPv6: L2 zählt je /48 (mit Faktor auf die Grenzen), Versuchsrate zusätzlich je /32
    auth_net6_factor: int = 4
    auth_wide_attempts_per_minute: int = 600
    auth_wide_attempts_burst: int = 300
    # Optional eigenes Redis nur für Zähler (z. B. mit maxmemory-policy volatile-lru): unter einem
    # Angriff werden dort Zähler verdrängt statt dass das Haupt-Redis (Tickets, noeviction) volläuft.
    # Leer = Haupt-Redis (REDIS_URL).
    ratelimit_redis_url: str = ""
    # Temporäre IP-Sperre (Stufe 4): nach so vielen Prüfstufen in 24 h, Dauer je Wiederholung.
    auth_block_strikes: int = 3
    auth_block_minutes: str = "60,360,1440"
    # Risk Engine (Abschnitt 7): "enforce" setzt Massnahmen durch, "monitor" protokolliert nur.
    auth_risk_mode: str = "enforce"
    auth_risk_moderate: int = 30
    auth_risk_high: int = 60
    auth_risk_critical: int = 80
    auth_critical_deny_minutes: int = 30
    # Bestätigungscode per E-Mail für Konten ohne zweiten Faktor (moderates/hohes Risiko)
    auth_email_code_ttl_minutes: int = 10
    # Notbetrieb ohne Redis (Abschnitt 11): lokale Grenze je Worker
    auth_emergency_ip_per_minute: int = 5
    auth_emergency_account_per_minute: int = 20
    # Step-up (SEC-AUTH-010): Höchstalter der letzten starken Anmeldung
    auth_step_up_mfa_minutes: int = 10
    auth_step_up_admin_minutes: int = 15
    # Sicherheitsereignisse (auth_event): Aufbewahrung
    auth_event_retention_days: int = 90
    # Alarmregeln (Abschnitt 10.3)
    auth_alert_stuffing_min: int = 100
    auth_alert_stuffing_networks: int = 20
    auth_alert_spraying_accounts: int = 10
    auth_alert_account_failures: int = 30
    auth_alert_account_networks: int = 3
    auth_alert_admin_mfa_failures: int = 3
    auth_alert_blocks_per_hour: int = 10
    auth_alert_cross_tenant: int = 3
    auth_alert_redis_memory_ratio: float = 0.7
    # Prüfung neuer Passwörter auf bekannte Leaks (SEC-AUTH-015, app/core/password_leak.py):
    # "on" = HIBP-Range-API (k-Anonymität, nur 5 Hex-Zeichen des SHA-1 gehen raus), Rückfall auf die
    # lokale Liste; "local-only" = nur die lokale Liste im Image; "off" = keine Leak-Prüfung.
    password_leak_check: str = "on"
    # Ab so vielen Vorkommen in HIBP gilt ein Passwort als geleakt (lokale Liste: immer Treffer).
    password_leak_min_count: int = 1
    password_leak_timeout_seconds: float = 2.0
    # Höchstens so viele Abfragen an HIBP je Minute (alle Prozesse); darüber lokale Liste.
    password_leak_fetch_per_minute: int = 600
    # Leak-Prüfung bestehender Passwörter beim Login (1.5.2, app/auth_security/breach.py): der
    # Nachtjob password_breach_recheck markiert Konten, deren letzte Prüfung älter ist, damit die
    # nächste Anmeldung ohne Präfix-Cache prüft.
    password_breach_recheck_days: int = 30
    # Länder-Geolocation als Risikosignal (app/core/geoip.py): DB-IP «IP to Country Lite» (CC BY 4.0),
    # lokal als MMDB, vom Job geoip_update (job-worker) monatlich geladen. Fehlt die Datei, entfällt
    # das Signal still. GEOIP_AUTO_UPDATE=false: kein Download (Datei bei Bedarf selbst ablegen).
    geoip_db_path: str = "/var/lib/hocx/geoip/dbip-country-lite.mmdb"
    geoip_auto_update: bool = True
    # Foto-Standorte (app/services/geo_places.py): Ortsdaten aus GeoNames (CC BY 4.0) und swisstopo
    # swissNAMES3D, vom Job geo_places_update (job-worker) monatlich in Postgres geladen. Nur dieser
    # Job lädt herunter, nie mit Koordinaten von Fotos. GEO_PLACES_AUTO_UPDATE=false: kein Download
    # (Import dann mit scripts/import_geo_places.py aus lokalen Dateien).
    geo_places_auto_update: bool = True
    # Länderdateien mit Gipfeln, Hütten, Seen und Weilern (Kürzel GeoNames); weltweit sonst cities500.
    geo_places_countries: str = "CH,LI,AT,DE,FR,IT"
    geo_places_max_age_days: int = 30
    # Eigene DB-Rolle hocx_geo nur für den Import (Migration 0260, GEO_DATABASE_URL[_FILE] im
    # job-worker). Leer: ausserhalb der Produktion die Owner-URL (DATABASE_URL), in der Produktion
    # bricht der job-worker ab, solange der automatische Import an ist.
    geo_database_url: str = ""

    admin_auth_secret: str = "hocx-local-dev-admin-secret"
    admin_session_cookie: str = "hocx_admin_session"
    admin_session_ttl_hours: int = 12
    # Nachweis «kam über den Admin-Entrypoint» (SEC-AUTH-001, app/core/admin_gate.py): Traefik setzt
    # diesen Wert an jedem Admin-Router als Header X-Hocx-Admin-Gate. Ohne Wert ist die Admin-API
    # ausserhalb der Entwicklung gesperrt (fail closed).
    admin_gate_secret: str | None = None
    initial_admin_email: str | None = None
    initial_admin_password: str | None = None
    clamav_host: str = "clamav"
    clamav_port: int = 3310
    redis_url: str = "redis://redis:6379/0"
    # Dokument-Engine (app/documents): Grenzen für den Typst-Worker-Pool. Der Timeout gilt
    # pro Compile (Wall-Clock); bei Überschreitung wird nur dieser Worker-Prozess beendet.
    # Pro Uvicorn-Worker (Dockerfile: 2) und im job-worker je ein eigener Pool.
    # Speicherlimit (RLIMIT_AS) je Typst-Prozess: eine Galerie mit 60 Fotos braucht gemessen
    # rund 1,7 GB RSS, kleiner geht nicht. Überbucht der Container trotzdem, beendet der
    # OOM-Killer nur den grössten Typst-Prozess; das trifft nur dessen Compile (CONC-004).
    document_render_concurrency: int = 2
    document_render_timeout_seconds: int = 60
    document_render_memory_limit_mb: int = 3072
    # Höchstens so lange auf einen freien Compile-Platz warten, sonst HTTP 503 (error.busy)
    document_render_queue_timeout_seconds: int = 20
    document_preview_max_pages: int = 4
    # Öffentliche Prüfseite (Abgabebox /verify), steht in jedem PDF (Fusszeile, QR-Code, XMP).
    # Bewusst die Plattform-Domain, nicht eine Mandanten-Domain: gedruckte Links bleiben stabil.
    # Leer = ABGABEBOX_BASE_URL + "/verify".
    document_verify_base_url: str | None = None
    # Interner Prüf-Endpoint der Abgabebox für den Systemcheck document_verification.
    abgabebox_internal_url: str = "http://abgabebox-backend:8000"
    # Obergrenze für Request-Bodies ausser Multipart (JSON etc.), MAIN-OPS-013.
    max_request_body_bytes: int = 10 * 1024 * 1024
    # Gleichzeitige Galerie-Uploads je uvicorn-Worker (CONC-007) und Wartezeit auf einen Platz.
    gallery_upload_concurrency: int = Field(default=2, ge=1, le=8, validation_alias="GALLERY_UPLOAD_CONCURRENCY")
    gallery_upload_slot_wait_seconds: float = Field(default=60.0, ge=0, le=600, validation_alias="GALLERY_UPLOAD_SLOT_WAIT_SECONDS")
    # Datei-Import (services/cloud_import, Plan 2026-11-21 E-5): Obergrenzen je Import-Auftrag.
    # Einzeldateien behalten die normalen Upload-Grenzen (20 MB Dokument, 100 MB Bild).
    cloud_import_max_job_files: int = Field(default=50_000, ge=1, le=50_000, validation_alias="CLOUD_IMPORT_MAX_JOB_FILES")
    cloud_import_max_job_bytes: int = Field(
        default=100 * 1024**3, ge=1024**2, le=100 * 1024**3, validation_alias="CLOUD_IMPORT_MAX_JOB_BYTES"
    )
    # Datei-Import aus Cloud-Diensten (services/cloud_import/providers, RUNBOOK «Cloud-Import
    # einrichten»). Globaler Schalter für alle API-Anbieter; ein Anbieter ohne Konfiguration wird
    # ohnehin nicht angeboten.
    cloud_import_enabled: bool = Field(default=True, validation_alias="CLOUD_IMPORT_ENABLED")
    # Schlüssel für die OAuth-Tokens in import_connection (MultiFernet, token_crypto.py). Nur backend
    # und job-worker. _PREVIOUS = bisheriger Schlüssel während einer Rotation (nur entschlüsseln).
    cloud_import_token_key: str = Field(default="", validation_alias="CLOUD_IMPORT_TOKEN_KEY")
    cloud_import_token_key_previous: str = Field(default="", validation_alias="CLOUD_IMPORT_TOKEN_KEY_PREVIOUS")
    # Basis der fest registrierten Redirect-URI (…/api/cloud-import/oauth/<anbieter>/callback).
    # Leer = https://TRAEFIK_DOMAIN (zentrale Domain; Rücksprung danach auf die Vereinsdomain).
    cloud_import_redirect_base_url: str = Field(default="", validation_alias="CLOUD_IMPORT_REDIRECT_BASE_URL")
    # Microsoft Entra App (OneDrive privat/Business, SharePoint). Ohne Client-ID/Secret: nicht angeboten.
    cloud_import_ms_client_id: str = Field(default="", validation_alias="CLOUD_IMPORT_MS_CLIENT_ID")
    cloud_import_ms_client_secret: str = Field(default="", validation_alias="CLOUD_IMPORT_MS_CLIENT_SECRET")
    # Ablaufdatum des Client-Secrets (JJJJ-MM-TT) für den Monitoring-Check «Cloud-Import».
    cloud_import_ms_client_secret_expires: str = Field(default="", validation_alias="CLOUD_IMPORT_MS_CLIENT_SECRET_EXPIRES")
    # Autorität: "common" (Arbeits-/Schulkonten und persönliche Konten), sonst Tenant-ID.
    cloud_import_ms_authority: str = Field(default="common", validation_alias="CLOUD_IMPORT_MS_AUTHORITY")
    # Download aus OneDrive for Business/SharePoint: "auto" (vorauthentifizierte URL, bei 401 bzw. ab
    # 1.4.2027 Bearer-Token), "tempauth" oder "bearer" (nur noch Bearer).
    cloud_import_ms_download_mode: str = Field(default="auto", pattern="^(auto|tempauth|bearer)$", validation_alias="CLOUD_IMPORT_MS_DOWNLOAD_MODE")
    # Google-Cloud-Projekt (Google Drive mit drive.file + Picker, Google Fotos über die Photos
    # Picker API; Plan §3, E-3 a). Ohne Client-ID/Secret werden beide nicht angeboten, Google Drive
    # zusätzlich nicht ohne API-Key und App-ID (der Picker braucht beides).
    cloud_import_google_client_id: str = Field(default="", validation_alias="CLOUD_IMPORT_GOOGLE_CLIENT_ID")
    cloud_import_google_client_secret: str = Field(default="", validation_alias="CLOUD_IMPORT_GOOGLE_CLIENT_SECRET")
    # Optional: Ablaufdatum (JJJJ-MM-TT), falls das Secret ablaufen soll (Google: unbegrenzt, sonst leer)
    cloud_import_google_client_secret_expires: str = Field(default="", validation_alias="CLOUD_IMPORT_GOOGLE_CLIENT_SECRET_EXPIRES")
    # Browser-Schlüssel für den Google Picker - öffentlich, in der Google-Cloud-Konsole auf die
    # HTTP-Referrer der hocX-Domains und die Picker API beschränken (kein Secret).
    cloud_import_google_api_key: str = Field(default="", max_length=200, pattern=r"^[A-Za-z0-9_-]*$", validation_alias="CLOUD_IMPORT_GOOGLE_API_KEY")
    # Projektnummer des Google-Cloud-Projekts (PickerBuilder.setAppId; ohne sie gibt drive.file keinen Zugriff)
    cloud_import_google_app_id: str = Field(default="", max_length=30, pattern=r"^[0-9]*$", validation_alias="CLOUD_IMPORT_GOOGLE_APP_ID")
    # Nachgebaute Anbieter für E2E/Tests (services/cloud_import/fake_*.py). Wirkt nur mit
    # HOCX_ENVIRONMENT=development; in jeder anderen Umgebung bricht der Start ab. Nie in .env*/deploy.
    cloud_import_fake_providers: bool = Field(default=False, validation_alias="CLOUD_IMPORT_FAKE_PROVIDERS")
    # Gleichzeitige Downloads je Import-Auftrag im job-worker (Plan §8.3). Konservativ: Anbieter
    # drosseln je App und Konto; mehr bringt selten mehr Durchsatz, aber schneller 429.
    cloud_import_max_parallel_downloads: int = Field(default=2, ge=1, le=8, validation_alias="CLOUD_IMPORT_MAX_PARALLEL_DOWNLOADS")
    # SQLAlchemy-Pool je Prozess (Concurrency-Audit CONC-010). pool_timeout kurz: bei erschöpftem
    # Pool lieber nach wenigen Sekunden 503 mit Retry-After (main.py) als 30 s Warten mit
    # gehaltenem Thread. Worker-Container setzen kleine Werte (docker-compose*.yml).
    db_pool_size: int = Field(default=12, ge=1, le=50, validation_alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=8, ge=0, le=50, validation_alias="DB_MAX_OVERFLOW")
    db_pool_timeout_seconds: float = Field(default=5.0, ge=0.5, le=60, validation_alias="DB_POOL_TIMEOUT_SECONDS")
    # Gleichzeitige HTTP-Requests je uvicorn-Worker (app/core/db_admission.py). Leer = Pool minus
    # DB_ADMISSION_RESERVE (WebSockets, Hintergrund-Loops, Fehlerprotokoll). Wer keinen Platz bekommt,
    # wartet ohne Thread und Verbindung bis DB_ADMISSION_WAIT_SECONDS, dann 503 db_busy.
    db_admission_limit: int | None = Field(default=None, ge=1, le=100, validation_alias="DB_ADMISSION_LIMIT")
    db_admission_reserve: int = Field(default=4, ge=0, le=50, validation_alias="DB_ADMISSION_RESERVE")
    db_admission_wait_seconds: float = Field(default=20.0, ge=0.5, le=120, validation_alias="DB_ADMISSION_WAIT_SECONDS")
    # Überlast-Schutz je Abo-Priorität (plan.load_priority, db_admission.py): Ab dieser Auslastung
    # (Requests in Arbeit + wartend je Platz, geglättet über ~10 s) sehen neue Nutzer von Mandanten
    # mit niedriger bzw. normaler Priorität die Überlast-Seite. Hohe Priorität wird nie vorab
    # abgewiesen. Wer in den letzten OVERLOAD_ACTIVE_MINUTES gearbeitet hat, bleibt drin.
    overload_threshold_low: float = Field(default=0.75, ge=0.1, le=10, validation_alias="OVERLOAD_THRESHOLD_LOW")
    overload_threshold_normal: float = Field(default=1.0, ge=0.1, le=10, validation_alias="OVERLOAD_THRESHOLD_NORMAL")
    overload_active_minutes: int = Field(default=15, ge=1, le=240, validation_alias="OVERLOAD_ACTIVE_MINUTES")
    # requirepass im Release-Stack (REDIS_PASSWORD_FILE, MAIN-OPS-005); leer = ohne Passwort.
    redis_password: str | None = None
    # Proxys, deren X-Forwarded-For ausgewertet wird (Traefik im Compose-Netz), siehe
    # app/core/client_ip.py.
    trusted_proxy_cidrs: str = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.0/8,::1/128,fc00::/7"

    # --- Objektspeicher (docs-site/docs/technik/storage/architektur.md) ---------------------------------------
    # Schlüssel für die Verschlüsselung der S3-Zugangsdaten in storage_profile. Gemeinsam mit
    # abgabebox-backend, photo-analysis-worker und storage-worker; nie im Frontend/Log.
    storage_credentials_key: str = ""
    # X25519-Schlüssel des Servers (64 Hex-Zeichen) für die Verschlüsselung der Mandanten-Exporte
    # (app/services/export_crypto.py). deploy.sh erzeugt ihn einmalig (scripts/lib/env_migrate.sh);
    # zusammen mit .env sichern, sonst sind ohne Passwort erstellte Exporte nicht mehr lesbar.
    # Ausserhalb der Produktion darf er fehlen (Ableitung aus AUTH_SECRET); in Produktion verweigert
    # export_crypto ohne ihn jeden Export/Import (deploy.sh prüft ihn vor dem Start).
    export_encryption_key: str = ""
    # Lokales Garage-S3 aus docker-compose (Profil "Lokales S3" wird beim Start angelegt bzw.
    # aktualisiert, solange die Variablen gesetzt sind). Leer = kein lokales S3 bereitgestellt.
    local_s3_endpoint: str = ""
    local_s3_region: str = "garage"
    local_s3_bucket: str = ""
    local_s3_abgabebox_bucket: str = ""
    local_s3_access_key: str = ""
    local_s3_secret_key: str = ""
    local_s3_abgabebox_access_key: str = ""
    local_s3_abgabebox_secret_key: str = ""
    # Wie lange eine abgelöste Speichergeneration nach einem Cutover garantiert erhalten bleibt.
    storage_fallback_days: int = 14
    # Lokaler Arbeitsbereich für materialisierte Vorlagen-Snapshots und temporäre Kopien.
    storage_work_root: str = "/app/storage-local/work"
    storage_journal_retention_days: int = 30

    # --- Dokumentverarbeitung (docs-site/docs/technik/dokumente.md) -------------------------
    # Grösste Originaldatei, die konvertiert/extrahiert wird; grössere bleiben nur als Original.
    document_max_input_mb: int = 50
    document_convert_timeout_seconds: int = 120
    document_extract_timeout_seconds: int = 90
    document_ocr_timeout_seconds: int = 300
    # Adressraum-Limits der Kindprozesse (LibreOffice reserviert viel virtuellen Speicher).
    document_convert_memory_mb: int = 3072
    document_extract_memory_mb: int = 1024
    document_ocr_max_pages: int = 50
    document_max_text_chars: int = 5_000_000
    document_job_max_attempts: int = 5
    document_job_lease_seconds: int = 600
    document_worker_poll_seconds: float = 5.0
    # Backend-Loop document_sync: Anlage für Abgabebox-Uploads und Bestand, Aufräumen.
    document_sync_interval_minutes: float = 2
    document_sync_batch_size: int = 200
    document_backfill_enabled: bool = True

    # --- Wartungsmodus -----------------------------------------------------------------------
    # Wie lange ein Prozess den Wartungszustand zwischenspeichert (Middleware). Kurz halten: der
    # Initial-Migrations-Worker wartet vor dem Fencen mindestens zweimal so lange.
    maintenance_cache_seconds: float = 2.0
    maintenance_supervisor_interval_seconds: int = 15
    # MaintenanceEstimator (app/services/maintenance_estimator.py): bewusst vorsichtige
    # Annahmen, solange keine Messwerte/Historie vorliegen. Raten in Bytes pro Sekunde.
    estimator_default_rate_local_bps: int = 25 * 1024 * 1024
    estimator_default_rate_external_bps: int = 6 * 1024 * 1024
    estimator_per_object_seconds_local: float = 0.03
    estimator_per_object_seconds_external: float = 0.15
    estimator_rate_derating: float = 0.75
    estimator_safety_factor: float = 0.5
    estimator_min_reserve_seconds: int = 300
    estimator_cutover_min_reserve_seconds: int = 60
    estimator_init_seconds: int = 60
    estimator_cutover_seconds: int = 60
    estimator_healthcheck_seconds: int = 60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def extra_cors_origin_set(self) -> set[str]:
        return {o.strip() for o in self.extra_cors_origins.split(",") if o.strip()}

    @property
    def is_secretless_process(self) -> bool:
        return self.process_kind.strip().lower() in SECRETLESS_PROCESS_KINDS

    @property
    def is_sessionless_process(self) -> bool:
        return self.is_secretless_process or self.process_kind.strip().lower() in SESSIONLESS_PROCESS_KINDS

    def apply_process_kind(self) -> None:
        if self.is_sessionless_process:
            self.auth_secret = secrets.token_hex(32)
            self.auth_secret_previous = ""
        if self.is_secretless_process:
            self.admin_auth_secret = secrets.token_hex(32)

    def validate_for_production(self) -> None:
        # Prozesse ohne Sitzungen bekommen ihre Werte aus apply_process_kind, nicht aus der Konfiguration.
        if not self.is_sessionless_process and (self.auth_secret in _INSECURE_DEFAULTS or len(self.auth_secret) < 32):
            print(
                "FATAL: AUTH_SECRET is insecure or not set. "
                "Set a random value of at least 32 characters in .env.",
                file=sys.stderr,
            )
            sys.exit(1)
        if self.auth_secret_previous and (self.auth_secret_previous in _INSECURE_DEFAULTS or len(self.auth_secret_previous) < 32):
            print("FATAL: AUTH_SECRET_PREVIOUS must be empty or a random value of at least 32 characters.", file=sys.stderr)
            sys.exit(1)
        if not self.is_secretless_process and (
            self.admin_auth_secret in _INSECURE_DEFAULTS or len(self.admin_auth_secret) < 32
        ):
            print(
                "FATAL: ADMIN_AUTH_SECRET is insecure or not set. "
                "Set a random value of at least 32 characters in .env.",
                file=sys.stderr,
            )
            sys.exit(1)
        if self.local_s3_access_key and (
            self.storage_credentials_key in _INSECURE_DEFAULTS or len(self.storage_credentials_key) < 32
        ):
            print(
                "FATAL: STORAGE_CREDENTIALS_KEY is insecure or not set although LOCAL_S3_* is configured. "
                "Set a random value of at least 32 characters in .env.",
                file=sys.stderr,
            )
            sys.exit(1)
        if self.cloud_import_fake_providers and self.environment.strip().lower() != "development":
            print("FATAL: CLOUD_IMPORT_FAKE_PROVIDERS is only allowed in test stacks (HOCX_ENVIRONMENT=development).", file=sys.stderr)
            sys.exit(1)
        for name, value in (("CLOUD_IMPORT_TOKEN_KEY", self.cloud_import_token_key), ("CLOUD_IMPORT_TOKEN_KEY_PREVIOUS", self.cloud_import_token_key_previous)):
            if value and (value in _INSECURE_DEFAULTS or len(value) < 32):
                print(f"FATAL: {name} must be empty or a random value of at least 32 characters.", file=sys.stderr)
                sys.exit(1)
        if self.is_production and self.cloud_import_redirect_base_url and not self.cloud_import_redirect_base_url.startswith("https://"):
            print("FATAL: CLOUD_IMPORT_REDIRECT_BASE_URL must use https:// in production.", file=sys.stderr)
            sys.exit(1)
        if self.is_production and (self.cloud_import_ms_client_id or self.cloud_import_google_client_id) and not self.cloud_import_token_key:
            print(
                "FATAL: CLOUD_IMPORT_TOKEN_KEY is not set although a cloud import provider is configured. "
                "Run scripts/deploy.sh (scripts/lib/env_migrate.sh creates it).",
                file=sys.stderr,
            )
            sys.exit(1)
        if self.is_production:
            if self.process_kind == "job-worker" and self.geo_places_auto_update and not self.geo_database_url:
                print(
                    "FATAL: GEO_DATABASE_URL is not set (DB role hocx_geo for the place data import, "
                    "Migration 0260). Run scripts/deploy.sh or set GEO_PLACES_AUTO_UPDATE=false.",
                    file=sys.stderr,
                )
                sys.exit(1)
            if not self.auth_secure_cookies:
                print("FATAL: AUTH_SECURE_COOKIES must be true in production.", file=sys.stderr)
                sys.exit(1)
            if self.initial_admin_email and self.initial_admin_email.lower().endswith("@hocx.local"):
                print("FATAL: A local development admin identity is forbidden in production.", file=sys.stderr)
                sys.exit(1)
            if self.initial_admin_password == "ChangeMe123!":
                print("FATAL: The known development admin password is forbidden in production.", file=sys.stderr)
                sys.exit(1)

    @property
    def verify_base_url(self) -> str:
        return (self.document_verify_base_url or f"{self.abgabebox_base_url.rstrip('/')}/verify").rstrip("/")

    @property
    def is_production(self) -> bool:
        # 'prod' ist ein Alias: scripts/deploy.sh schrieb bis zum Audit MAIN-OPS-001 den
        # Host-Namen 'prod' in die .env, solche Hosts muessen weiter als Produktion gelten.
        return self.environment.strip().lower() in PRODUCTION_ENVIRONMENT_NAMES

    @property
    def local_dev_origins(self) -> tuple[str, ...]:
        """Lokaler Next-Dev-Server als CORS-/WebSocket-Origin - nur ausserhalb der Produktion
        (Audit MAIN-SEC-009: sonst durfte jede lokal auf Port 3000 laufende Seite
        credentialed Requests an die Produktions-API stellen)."""
        if self.is_production:
            return ()
        return ("http://localhost:3000", "http://127.0.0.1:3000")


settings = Settings()
settings.apply_process_kind()
settings.validate_for_production()
