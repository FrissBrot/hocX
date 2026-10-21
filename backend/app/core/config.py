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
        "DATABASE_URL", "APP_DATABASE_URL", "AUTH_SECRET", "ADMIN_AUTH_SECRET", "INITIAL_ADMIN_PASSWORD",
        "STORAGE_CREDENTIALS_KEY", "LOCAL_S3_SECRET_KEY", "LOCAL_S3_ABGABEBOX_SECRET_KEY", "REDIS_PASSWORD",
        "EXPORT_ENCRYPTION_KEY",
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
    security_alert_admin_logins: bool = False
    # How often the cycle-snapshot loop checks whether any CycleConfig's reset boundary
    # was crossed since the last snapshot (see main.py's cycle_snapshot_loop and
    # table_snapshot_service.run_due_cycle_snapshots). Daily is enough - a cycle boundary
    # is crossed at most once a year per config, and the loop self-heals a missed day.
    cycle_snapshot_check_interval_minutes: int = 1440
    # Aufgabenpakete: Aufgaben des laufenden Zyklus anlegen/nachführen (siehe main.py's
    # task_package_rollover_loop). Täglich reicht - beim Zuweisen, bei Paket-, Listen- und
    # Terminänderungen wird zusätzlich sofort nachgeführt.
    task_package_rollover_interval_minutes: int = 1440
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
    # Auto-album sync (main.py's photo_album_sync_loop): folds newly-submitted (and newly
    # removed) abgabebox submission files into their Zyklus/Abgabe/Abgabe-Element albums -
    # same reason as the backfill above, this can't happen inline in the restricted
    # abgabebox-backend request path.
    photo_album_sync_interval_minutes: int = 15
    # Mirrors the abgabebox subapp's ABGABEBOX_TENANT_STORAGE_QUOTA_MB - protocol-image
    # uploads had only a per-file limit (MAX_UPLOAD_BYTES), no per-tenant total at all
    # (audit finding, 2026-08-25), a real risk given this app's two prior disk-full
    # outages. Same 2 GB default.
    protocol_image_storage_quota_mb: int = 2048
    auth_secret: str = "hocx-local-dev-secret"
    auth_session_cookie: str = "hocx_session"
    auth_session_ttl_hours: int = 72
    auth_secure_cookies: bool = True
    admin_auth_secret: str = "hocx-local-dev-admin-secret"
    admin_session_cookie: str = "hocx_admin_session"
    admin_session_ttl_hours: int = 12
    initial_admin_email: str | None = None
    initial_admin_password: str | None = None
    clamav_host: str = "clamav"
    clamav_port: int = 3310
    redis_url: str = "redis://redis:6379/0"
    # Dokument-Engine (app/documents): Grenzen für den Typst-Prozess-Pool. Der Timeout gilt
    # pro Compile (Wall-Clock); bei Überschreitung wird der Pool beendet und neu gestartet.
    # Pro Uvicorn-Worker (Dockerfile: 2) ein eigener Pool: 2 × 2 Compiles gleichzeitig.
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

    def apply_process_kind(self) -> None:
        if self.is_secretless_process:
            self.auth_secret = secrets.token_hex(32)
            self.admin_auth_secret = secrets.token_hex(32)

    def validate_for_production(self) -> None:
        # Prozesse ohne Sitzungen bekommen ihre Werte aus apply_process_kind, nicht aus der Konfiguration.
        if not self.is_secretless_process and (self.auth_secret in _INSECURE_DEFAULTS or len(self.auth_secret) < 32):
            print(
                "FATAL: AUTH_SECRET is insecure or not set. "
                "Set a random value of at least 32 characters in .env.",
                file=sys.stderr,
            )
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
        if self.is_production:
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
    def storage_filesystem_roots(self) -> dict[str, Path]:
        return {"main": Path(self.storage_root), "abgabebox": Path(self.abgabebox_storage_root)}

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
