"""Recovery-CLI für hocX-Backups - unabhängig vom laufenden Backend, von Redis und von einer
vorhandenen hocX-Datenbank. Alle Informationen kommen aus dem Borg-Repository.

    docker compose exec backup-worker python -m app.backup.cli <befehl> [optionen]
    # ohne laufendes Backend (neuer Server, Datenbank weg):
    docker compose run --rm --no-deps --entrypoint python backup-worker -m app.backup.cli <befehl>

Befehle (Details: --help je Befehl, Ablauf: docs-site/docs/technik/backup/restore.md):
  info              Repository erreichbar? Identität, Verschlüsselung, Grösse
  list              Wiederherstellungspunkte (aus dem Repository rekonstruiert)
  show              Metadaten eines Punkts (Version, Schema, Mandanten, Prüfsummen)
  verify            Dump und Objektinhalte eines Punkts gegen ihre SHA-256 prüfen
  restore-full      Punkt in eine NEUE Datenbank und einen gewählten Objektspeicher wiederherstellen
  swap-database     wiederhergestellte Datenbank an die Stelle der Live-Datenbank setzen
  init              neues Repository anlegen (nur bei der Ersteinrichtung)
  export-key        Repository-Schlüssel sichern (Papier/Datei)
  compact           Speicher freigeben (nur mit Wartungsschlüssel, nie im Normalbetrieb)
  break-lock        verwaisten Repository-Lock entfernen
  enqueue-backup    Backup-Auftrag anlegen und optional auf das Ende warten (braucht die hocX-DB)

Exit-Codes: 0 ok, 1 Fehler, 2 Prüfung mit Befund.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.backup.borg import Borg, BorgError
from app.backup.config import BackupConfig, BackupConfigError, load_config
from app.backup.pgtools import PgTarget, PgToolError, PgTools, validate_db_name
from app.backup.repository import RepositoryView
from app.backup.restore_core import (
    RestoreError,
    configure_restored_database,
    ensure_app_roles,
    ensure_empty_generation,
    load_restore_point,
    reference_report,
    restore_database,
    restore_objects,
    restored_keys_from_manifest,
    run_alembic_upgrade,
    schema_compatibility,
    verify_stream,
)
from app.core.objstore_client import FilesystemBackend, ProfileConfig, S3Backend, encrypt_credential


def _print(data: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    elif isinstance(data, dict):
        for key, value in data.items():
            print(f"{key}: {value}")
    else:
        print(data)


def _secret(value: str | None, file_value: str | None, name: str) -> str | None:
    if file_value:
        return Path(file_value).read_text(encoding="utf-8").strip()
    if value:
        return value
    env_file = os.environ.get(f"{name}_FILE")
    if env_file:
        return Path(env_file).read_text(encoding="utf-8").strip()
    return os.environ.get(name)


def _database_url(args: argparse.Namespace) -> str:
    if getattr(args, "database_url", None) and getattr(args, "database_url_file", None):
        raise SystemExit("Nur eine von --database-url und --database-url-file angeben")
    if args.database_url:
        from sqlalchemy.engine import make_url

        try:
            has_password = bool(make_url(args.database_url).password)
        except Exception:  # noqa: BLE001 - ungültige URL meldet PgTarget mit klarer Meldung
            has_password = False
        if has_password:
            print("WARNUNG: --database-url enthält ein Passwort - es steht in der Prozessliste und der Shell-History. "
                  "Besser --database-url-file oder DATABASE_URL_FILE verwenden.", file=sys.stderr)
    url = args.database_url or _secret(None, getattr(args, "database_url_file", None), "DATABASE_URL")
    if not url:
        raise SystemExit("Datenbankserver unbekannt: --database-url oder DATABASE_URL(_FILE) setzen")
    return url


def _config(args: argparse.Namespace) -> BackupConfig:
    config = load_config()
    if getattr(args, "repository", None):
        config = replace(config, repository_url_override=args.repository)
    config.validate()
    return config


def _confirm(args: argparse.Namespace, question: str) -> None:
    if getattr(args, "yes", False):
        return
    answer = input(f"{question} [ja/NEIN] ").strip().lower()
    if answer not in ("ja", "yes"):
        raise SystemExit("Abgebrochen")


# --- Befehle ----------------------------------------------------------------------------------


def cmd_info(args: argparse.Namespace) -> int:
    config = _config(args)
    borg = Borg(config)
    try:
        info = borg.repo_info()
    finally:
        borg.close()
    repo = info.get("repository", {})
    data = {
        "repository": config.redacted_repository(), "repository_id": repo.get("id"),
        "repository_id_pinned_ok": None if not config.expected_repository_id else repo.get("id") == config.expected_repository_id,
        "encryption": (info.get("encryption") or {}).get("mode"), "stored_bytes": (info.get("cache") or {}).get("stats", {}).get("unique_csize"),
        "borg": borg.version(),
    }
    _print(data, args.json)
    return 0 if data["repository_id_pinned_ok"] is not False else 1


def cmd_list(args: argparse.Namespace) -> int:
    config = _config(args)
    borg = Borg(config)
    try:
        view = RepositoryView(borg)
        points = view.restore_points(include_invalid=args.all)
        rows = []
        for point in points:
            row: dict[str, Any] = {"archive": point.name, "snapshot_at": point.snapshot_at.isoformat(), "invalid": point.invalid}
            if args.details:
                try:
                    metadata = view.read_metadata(point.name)
                    row.update({"app_version": metadata.get("app_version"), "alembic_revision": metadata.get("alembic_revision"),
                                "objects": metadata.get("object_count"), "missing_objects": metadata.get("missing_objects"),
                                "trigger": metadata.get("trigger")})
                except Exception as exc:  # noqa: BLE001 - CLI zeigt jeden Befund an
                    row["error"] = str(exc)
            rows.append(row)
    finally:
        borg.close()
    if args.json:
        _print(rows, True)
    else:
        for row in rows:
            print("  ".join(f"{k}={v}" for k, v in row.items()))
        print(f"{len(rows)} Wiederherstellungspunkte")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    config = _config(args)
    borg = Borg(config)
    try:
        metadata = load_restore_point(RepositoryView(borg), args.archive)
    finally:
        borg.close()
    metadata["schema_compatibility"] = schema_compatibility(metadata.get("alembic_revision"))
    _print(metadata, True)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    config = _config(args)
    borg = Borg(config)
    work = config.staging_dir / f"cli-verify-{uuid.uuid4().hex}"
    try:
        view = RepositoryView(borg)
        metadata = load_restore_point(view, args.archive)
        work.mkdir(parents=True, exist_ok=True)
        dump = work / "dump.pgdump"
        view.download(args.archive, "db/hocx.pgdump", dump, expected_sha256=metadata["db_dump_sha256"], max_bytes=config.staging_max_bytes)
        dump.unlink()
        report = verify_stream(view, args.archive, metadata, work)
    finally:
        import shutil

        shutil.rmtree(work, ignore_errors=True)
        borg.close()
    _print({"dump_sha256_ok": True, **report}, args.json)
    return 0 if report["ok"] else 2


def _target_backend(args: argparse.Namespace, generation: int) -> tuple[Any, dict[str, Any]]:
    """Ziel-Objektspeicher aus den CLI-Angaben. Liefert Backend und die Profilwerte für die
    wiederhergestellte Datenbank (Zugangsdaten mit STORAGE_CREDENTIALS_KEY verschlüsselt)."""
    if args.storage == "filesystem":
        roots = {"main": Path(args.filesystem_root), "abgabebox": Path(args.filesystem_abgabebox_root or Path(args.filesystem_root) / "abgabebox-uploads")}
        config = ProfileConfig(profile_id=0, generation=generation, provider="filesystem")
        profile = {"public_id": uuid.uuid4(), "name": "Lokales Dateisystem (bisheriger Bestand)", "provider": "filesystem", "endpoint_url": None,
                   "region": None, "bucket": None, "abgabebox_bucket": None, "prefix": "", "addressing_style": "auto", "access_key_enc": None,
                   "secret_key_enc": None, "restricted_access_key_enc": None, "restricted_secret_key_enc": None, "tls_verify": True, "ca_bundle_pem": None}
        return FilesystemBackend(config, roots), profile
    credentials_key = _secret(None, None, "STORAGE_CREDENTIALS_KEY")
    if not credentials_key:
        raise SystemExit("STORAGE_CREDENTIALS_KEY(_FILE) fehlt - damit werden die S3-Zugangsdaten in der Datenbank verschlüsselt")
    access_key = _secret(None, args.s3_access_key_file, "RESTORE_S3_ACCESS_KEY")
    secret_key = _secret(None, args.s3_secret_key_file, "RESTORE_S3_SECRET_KEY")
    if not (args.s3_bucket and access_key and secret_key):
        raise SystemExit("--s3-bucket sowie Zugangsdaten (--s3-access-key-file/--s3-secret-key-file) sind nötig")
    config = ProfileConfig(
        profile_id=0, generation=generation, provider=args.s3_provider, endpoint_url=args.s3_endpoint or None, region=args.s3_region,
        bucket=args.s3_bucket, abgabebox_bucket=args.s3_abgabebox_bucket or None, prefix=args.s3_prefix or "",
        addressing_style=args.s3_addressing, access_key=access_key, secret_key=secret_key, tls_verify=not args.s3_insecure,
    )
    profile = {"public_id": uuid.uuid4(), "name": args.profile_name or f"Wiederherstellung {args.s3_bucket}", "provider": args.s3_provider,
               "endpoint_url": config.endpoint_url, "region": config.region, "bucket": config.bucket, "abgabebox_bucket": config.abgabebox_bucket,
               "prefix": config.prefix, "addressing_style": config.addressing_style,
               "access_key_enc": encrypt_credential(access_key, credentials_key), "secret_key_enc": encrypt_credential(secret_key, credentials_key),
               "restricted_access_key_enc": None, "restricted_secret_key_enc": None, "tls_verify": config.tls_verify, "ca_bundle_pem": None}
    return S3Backend(config), profile


def _insert_maintenance(database_url: str) -> None:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(database_url, poolclass=NullPool, hide_parameters=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO maintenance_window (kind, block_scope, state, reason_code, affected_features, source_job_type, started_at, internal_note)
                SELECT 'full', 'all', 'active', 'backup_restore', '["all"]'::jsonb, 'backup_restore_cli', NOW(),
                       'Wiederherstellung per Recovery-CLI - nach Prüfung im Admin-Portal (System -> Wartung) freigeben'
                WHERE NOT EXISTS (SELECT 1 FROM maintenance_window WHERE source_job_type = 'backup_restore_cli' AND state = 'active')
            """))  # Fortsetzung (--resume): keine zweite Wartung
    finally:
        engine.dispose()


_DB_COMPLETE_MARKER = "hocx-restore-database-complete"


def _database_comment(pg: PgTools, name: str) -> str:
    return pg.psql(f"SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = '{validate_db_name(name)}';", database="postgres")


def cmd_restore_full(args: argparse.Namespace) -> int:
    config = _config(args)
    target = PgTarget.from_url(_database_url(args))
    db_name = validate_db_name(args.target_db)
    borg = Borg(config)
    work = config.staging_dir / f"cli-restore-{uuid.uuid4().hex}"
    report: dict[str, Any] = {"archive": args.archive, "target_db": db_name}
    try:
        view = RepositoryView(borg)
        metadata = load_restore_point(view, args.archive)
        compat = schema_compatibility(metadata.get("alembic_revision"))
        report["schema"] = compat
        if compat["state"] in ("newer", "unknown"):
            print(f"FEHLER: Backup-Schema {compat['revision']} ist dieser hocX-Version unbekannt - passendes Image verwenden.", file=sys.stderr)
            return 1
        if compat["state"] == "upgrade" and not args.allow_schema_upgrade:
            print(f"FEHLER: Backup hat Schema {compat['revision']}, Code erwartet {compat['head']}. Mit --allow-schema-upgrade wird nach dem "
                  "Restore kontrolliert migriert; sonst die zum Backup passende hocX-Version verwenden.", file=sys.stderr)
            return 1
        generation = args.generation or int((metadata.get("storage") or {}).get("generation") or 0) + 1
        backend, profile = _target_backend(args, generation)
        # Fortsetzung (--resume): eine vorhandene Zieldatenbank wird nur übernommen, wenn sie als
        # vollständig wiederhergestellt aus GENAU diesem Punkt markiert ist - sonst nichts anfassen.
        marker = f"{_DB_COMPLETE_MARKER}:{args.archive}"
        with PgTools(target) as pg:
            resume_db = bool(args.resume and pg.database_exists(db_name))
            if resume_db and _database_comment(pg, db_name) != marker:
                print(f"FEHLER: Zieldatenbank {db_name} existiert, ist aber nicht als vollständig aus {args.archive} wiederhergestellt "
                      "markiert (z. B. Abbruch während pg_restore). Nichts verändert - Datenbank prüfen und ggf. löschen, dann neu starten.",
                      file=sys.stderr)
                return 1
        if not resume_db:
            ensure_empty_generation(backend)
        print(f"Wiederherstellungspunkt {args.archive} (hocX {metadata.get('app_version')}, {metadata.get('object_count')} Objekte)")
        print(f"Ziel: Datenbank {db_name} auf {target.host}, Objekte nach {args.storage} (Generation {generation})"
              + (" - Fortsetzung: Datenbank bereits wiederhergestellt" if resume_db else ""))
        _confirm(args, "Fortfahren?")
        if resume_db:
            report["database"] = {"resumed": True}
        else:
            with PgTools(target) as pg:
                if not args.no_owner:
                    report["roles"] = ensure_app_roles(pg)
                report["database"] = restore_database(view, args.archive, metadata, pg, db_name, work, max_bytes=config.staging_max_bytes,
                                                      jobs=config.pg_restore_jobs, no_owner=args.no_owner)
                pg.psql(f"COMMENT ON DATABASE \"{db_name}\" IS '{marker}';", database="postgres")
        print("Datenbank wiederhergestellt, Objekte werden übertragen ...")
        objects = restore_objects(view, args.archive, metadata, backend, work, skip_existing=args.resume,
                                  progress=lambda v: print(f"  {v['contents_restored']} Inhalte, {v['bytes_restored'] // 1024 ** 2} MiB", flush=True))
        report["objects"] = objects
        restored_url = target.with_database(db_name).sqlalchemy_url()
        if compat["state"] == "upgrade":
            run_alembic_upgrade(restored_url)
            report["alembic_upgraded"] = True
        report["configured"] = configure_restored_database(restored_url, profile=profile, generation=generation, note="CLI-Restore")
        if not args.no_maintenance:
            _insert_maintenance(restored_url)
            report["maintenance"] = "aktiv - nach Prüfung im Admin-Portal freigeben"
        report["references"] = reference_report(restored_url, restored_keys_from_manifest(view, args.archive, metadata, work,
                                                                                          set(objects.get("corrupt") or [])))
    except (RestoreError, BorgError, PgToolError, BackupConfigError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        _print(report, True)
        return 1
    finally:
        import shutil

        shutil.rmtree(work, ignore_errors=True)
        borg.close()
    _print(report, True)
    ok = objects["ok"] and report["references"]["registry_without_object_count"] == int(metadata.get("missing_objects") or 0)
    print("\nNächste Schritte: Anwendung stoppen, 'swap-database' ausführen (oder POSTGRES_DB auf die neue Datenbank setzen), "
          "Anwendung starten, im Admin-Portal prüfen und die Wartung freigeben.")
    return 0 if ok else 2


def cmd_swap_database(args: argparse.Namespace) -> int:
    target = PgTarget.from_url(_database_url(args))
    live, restored = validate_db_name(args.live), validate_db_name(args.restored)
    pre = validate_db_name(args.keep_as or f"hocx_pre_restore_{time.strftime('%Y%m%d%H%M%S')}")
    with PgTools(target) as pg:
        if not pg.database_exists(restored):
            print(f"FEHLER: {restored} existiert nicht", file=sys.stderr)
            return 1
        _confirm(args, f"{live} wird zu {pre} umbenannt und {restored} wird zu {live}. Alle Verbindungen werden beendet. Fortfahren?")
        exists = pg.database_exists(live)
        for name in ([live] if exists else []) + [restored]:
            pg.psql(f'ALTER DATABASE "{name}" WITH ALLOW_CONNECTIONS false;', database="postgres")
        pg.psql(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('{live}', '{restored}') AND pid <> pg_backend_pid();",
                database="postgres")
        if exists:
            pg.psql(f'ALTER DATABASE "{live}" RENAME TO "{pre}";', database="postgres")
        pg.psql(f'ALTER DATABASE "{restored}" RENAME TO "{live}";', database="postgres")
        pg.psql(f'ALTER DATABASE "{live}" WITH ALLOW_CONNECTIONS true;', database="postgres")
        pg.psql(f'GRANT CONNECT ON DATABASE "{live}" TO hocx_app, hocx_abgabebox, hocx_photo_worker;', database="postgres")
    print(f"Fertig. Bisherige Datenbank: {pre if exists else '(keine)'}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    config = _config(args)
    if not args.i_understand_this_creates_a_new_repository:
        print("Sicherheitsabfrage: --i-understand-this-creates-a-new-repository fehlt. Ein bestehendes Repository wird nie überschrieben.",
              file=sys.stderr)
        return 1
    borg = Borg(config)
    try:
        borg.init()
        info = borg.repo_info()
    except BorgError as exc:
        print(f"FEHLER: {exc} ({exc.code})", file=sys.stderr)
        return 1
    finally:
        borg.close()
    repo_id = info["repository"]["id"]
    print(f"Repository angelegt: {config.redacted_repository()}\nRepository-ID: {repo_id}\n"
          f"-> In .env als BACKUP_REPOSITORY_ID={repo_id} eintragen (Pinning) und sofort den Schlüssel sichern: export-key --paper")
    return 0


def cmd_export_key(args: argparse.Namespace) -> int:
    config = _config(args)
    borg = Borg(config)
    try:
        if args.paper:
            out = config.work_dir / f"borg-key-paper-{uuid.uuid4().hex}.txt"
            borg.key_export(out, paper=True)
            print(out.read_text())
            out.unlink()
        else:
            borg.key_export(Path(args.file))
            os.chmod(args.file, 0o600)
            print(f"Schlüssel exportiert nach {args.file} - offline aufbewahren, zusammen mit der Passphrase getrennt lagern.")
    finally:
        borg.close()
    return 0


def cmd_compact(args: argparse.Namespace) -> int:
    config = _config(args)
    key = Path(args.maintenance_key or (config.maintenance_ssh_key_file or ""))
    if not key.is_file():
        print("FEHLER: Wartungsschlüssel fehlt (--maintenance-key). Mit dem append-only-Backupschlüssel gibt compact nichts frei.", file=sys.stderr)
        return 1
    borg = Borg(config, ssh_key_file=key)
    try:
        archives = borg.list_archives()
        print(f"{len(archives)} Archive im Repository. Vor dem Kompaktieren prüfen, dass keine unerwarteten Löschungen erfolgt sind "
              "(Vergleich mit dem Admin-Portal / 'list').")
        _confirm(args, "Gelöschte Daten endgültig freigeben?")
        borg.compact()
    finally:
        borg.close()
    print("Kompaktierung abgeschlossen")
    return 0


def cmd_break_lock(args: argparse.Namespace) -> int:
    config = _config(args)
    _confirm(args, "Nur ausführen, wenn sicher kein Backup-Prozess mehr läuft. Lock entfernen?")
    borg = Borg(config)
    try:
        borg.break_lock()
    finally:
        borg.close()
    return 0


def _print_partial_details(backup_set) -> None:
    for warning in (backup_set.warnings or []) if backup_set else []:
        if warning.get("code") != "missing_objects":
            continue
        print(f"WARNUNG: {warning.get('count', 0)} Objekte fehlen im Wiederherstellungspunkt (Datenbank-Dump vollständig):", file=sys.stderr)
        for item in (warning.get("items") or [])[:20]:
            print(f"  {item.get('namespace', 'main')}/{item.get('key')}", file=sys.stderr)


def cmd_enqueue_backup(args: argparse.Namespace) -> int:
    """Für deploy.sh: Backup vor riskanten Migrationen. Braucht die hocX-Datenbank.

    Läuft gerade ein anderes Backup (ein offener Auftrag je Art), wird mit --wait auf dessen Ende
    gewartet und danach der eigene (geschützte) Auftrag angelegt - kein Abbruch mit Traceback."""
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    from app.backup.jobs import OPEN_JOB_STATES
    from app.core.db import SessionLocal
    from app.models import BackupJob, BackupSet

    key = f"{args.trigger}:{args.key or uuid.uuid4().hex}"
    deadline = time.monotonic() + args.timeout
    job_id = None
    announced = None
    while job_id is None:
        with SessionLocal() as db:
            job = db.scalars(select(BackupJob).where(BackupJob.idempotency_key == key)).first()
            if job is None:
                job = BackupJob(kind="backup", trigger=args.trigger, idempotency_key=key,
                                options={"protected": args.protect, "protected_reason": args.reason} if args.protect else {})
                db.add(job)
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    job = None
            if job is not None:
                job_id = job.id
                break
            blocking = db.scalars(select(BackupJob).where(BackupJob.kind == "backup", BackupJob.state.in_(OPEN_JOB_STATES))).first()
        if blocking is not None and blocking.id != announced:
            announced = blocking.id
            print(f"Es läuft bereits ein Backup ({blocking.id}, {blocking.state}) - warte auf dessen Ende", file=sys.stderr)
        if not args.wait:
            print("Kein neuer Auftrag angelegt: ein Backup ist bereits offen (mit --wait wird gewartet)", file=sys.stderr)
            return 1
        if time.monotonic() >= deadline:
            print("Zeitlimit erreicht - das laufende Backup ist noch nicht fertig, kein eigener Auftrag angelegt", file=sys.stderr)
            return 1
        time.sleep(args.poll_seconds)
    print(f"Backup-Auftrag {job_id}")
    if not args.wait:
        return 0
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            job = db.get(BackupJob, job_id)
            if job.state in ("completed", "partial", "failed", "cancelled", "interrupted"):
                backup_set = db.get(BackupSet, job.backup_set_id) if job.backup_set_id else None
                print(f"Ergebnis: {job.state} {backup_set.archive_name if backup_set else ''} {job.error_message or ''}".strip())
                if job.state == "partial":
                    _print_partial_details(backup_set)
                    if args.accept_partial:
                        print("Teilweise erfolgreiches Backup wird akzeptiert (--accept-partial)", file=sys.stderr)
                        return 0
                return 0 if job.state == "completed" else 1
        time.sleep(args.poll_seconds)
    print("Zeitlimit erreicht - Backup läuft weiter, Ergebnis im Admin-Portal", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.backup.cli", description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repository", help="Repository-URL statt der Storage-Box-Konfiguration (z. B. für eine Kopie)")
    parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info").set_defaults(func=cmd_info)
    p = sub.add_parser("list")
    p.add_argument("--all", action="store_true", help="auch als ungültig markierte Punkte")
    p.add_argument("--details", action="store_true", help="Metadaten je Punkt lesen (langsamer)")
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("show")
    p.add_argument("archive")
    p.set_defaults(func=cmd_show)
    p = sub.add_parser("verify")
    p.add_argument("archive")
    p.set_defaults(func=cmd_verify)
    p = sub.add_parser("restore-full")
    p.add_argument("--archive", required=True)
    p.add_argument("--target-db", required=True, help="Name der NEUEN Datenbank (darf nicht existieren)")
    p.add_argument("--database-url", help="Server/Zugang (Superuser), Default DATABASE_URL - mit Passwort besser --database-url-file")
    p.add_argument("--database-url-file", help="Datei mit der Datenbank-URL (Passwort nicht in der Prozessliste)")
    p.add_argument("--storage", choices=("s3", "filesystem"), required=True)
    p.add_argument("--generation", type=int, help="Ziel-Generation (Default: Generation des Backups + 1)")
    p.add_argument("--filesystem-root")
    p.add_argument("--filesystem-abgabebox-root")
    p.add_argument("--s3-provider", default="s3_compatible", choices=("garage_local", "aws_s3", "hetzner", "s3_compatible"))
    p.add_argument("--s3-endpoint")
    p.add_argument("--s3-region", default="us-east-1")
    p.add_argument("--s3-bucket")
    p.add_argument("--s3-abgabebox-bucket")
    p.add_argument("--s3-prefix", default="")
    p.add_argument("--s3-addressing", default="auto", choices=("auto", "path", "virtual"))
    p.add_argument("--s3-access-key-file")
    p.add_argument("--s3-secret-key-file")
    p.add_argument("--s3-insecure", action="store_true", help="TLS-Prüfung aus (nur lokales Test-S3)")
    p.add_argument("--profile-name")
    p.add_argument("--allow-schema-upgrade", action="store_true")
    p.add_argument("--no-owner", action="store_true", help="Besitzer/Rechte des Dumps nicht übernehmen (fremder Server ohne hocX-Rollen)")
    p.add_argument("--no-maintenance", action="store_true", help="keine Wartung in der wiederhergestellten DB aktivieren")
    p.add_argument("--resume", action="store_true", help="bereits vorhandene, passende Objekte überspringen")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_restore_full)
    p = sub.add_parser("swap-database")
    p.add_argument("--live", required=True)
    p.add_argument("--restored", required=True)
    p.add_argument("--keep-as")
    p.add_argument("--database-url", help="mit Passwort besser --database-url-file")
    p.add_argument("--database-url-file", help="Datei mit der Datenbank-URL (Passwort nicht in der Prozessliste)")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_swap_database)
    p = sub.add_parser("init")
    p.add_argument("--i-understand-this-creates-a-new-repository", action="store_true")
    p.set_defaults(func=cmd_init)
    p = sub.add_parser("export-key")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--paper", action="store_true")
    group.add_argument("--file")
    p.set_defaults(func=cmd_export_key)
    p = sub.add_parser("compact")
    p.add_argument("--maintenance-key")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_compact)
    p = sub.add_parser("break-lock")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_break_lock)
    p = sub.add_parser("enqueue-backup")
    p.add_argument("--trigger", default="cli", choices=("cli", "pre_deploy", "manual"))
    p.add_argument("--key", help="Idempotenzschlüssel (z. B. Zielversion)")
    p.add_argument("--protect", action="store_true", help="Punkt nie durch die Retention entfernen")
    p.add_argument("--reason")
    p.add_argument("--wait", action="store_true")
    p.add_argument("--timeout", type=int, default=6 * 3600, help="Sekunden insgesamt (Warten auf ein laufendes Backup eingeschlossen)")
    p.add_argument("--accept-partial", action="store_true",
                   help="Teilweise erfolgreiches Backup (Datenbank vollständig, einzelne Objekte fehlen) als Erfolg werten; "
                        "die fehlenden Objekte werden ausgegeben")
    p.add_argument("--poll-seconds", type=float, default=10, help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_enqueue_backup)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except BackupConfigError as exc:
        print(f"Konfigurationsfehler: {exc}", file=sys.stderr)
        return 1
    except BorgError as exc:
        print(f"Borg-Fehler ({exc.code}): {exc}", file=sys.stderr)
        return 1
    except (RestoreError, PgToolError) as exc:
        print(f"Fehler ({exc.code}): {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
