"""Inkrementelles Backup der aktiven Speichergeneration in ein lokales Verzeichnis (bzw. einen
gemounteten Backup-Datenträger) - Gegenstück zu scripts/backup_db.sh für die Dateien.

    python -m app.workers.storage_backup --target /backups/storage           # sichern
    python -m app.workers.storage_backup --target /backups/storage --verify  # Backup prüfen

Konsistenz mit dem Datenbank-Backup (docs-site/docs/technik/storage/backup.md):
- Das Objekt-Backup läuft **nach** pg_dump. Objekt-Keys sind einmalig
  vergeben; was der Dump referenziert, existiert darum beim anschliessenden
  Objekt-Backup noch - es sei denn, es wurde dazwischen gelöscht. Solche Fälle meldet die
  Integritätsprüfung nach einem Restore (app.workers.storage_verify).
- Das Backup ist inkrementell (Grösse + SHA-256 aus dem Register entscheiden) und schreibt jede
  Datei atomar. Es gibt genau einen Stand (ein manifest.json): ein Key, dessen Inhalt sich
  geändert hat, wird überschrieben, gelöschte Objekte bleiben liegen. Ältere Stände (passend zu
  älteren DB-Dumps) sichert nur ein Snapshot des Zielverzeichnisses durch das Host-Backup.
- Ändert sich ein Objekt während des Laufs, gilt der neue Registerstand; nur eine echte
  Abweichung zwischen Register und Speicher wird als "mismatched" gemeldet (Exit-Code 2).
- manifest.json hält Generation, Journal-Position, Zeitpunkt und SHA-256 je Objekt. --verify liest
  jede Datei neu und vergleicht - ein Backup gilt erst nach erfolgreichem Restore-Test als
  verifiziert (Restore-Probe: siehe Doku).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

from app.core.db import SessionLocal
from app.core.objstore_client import CHUNK_BYTES, ObjectNotFound, validate_key
from app.core.storage import get_object_store
from app.models import StorageObject

MANIFEST = "manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup(target: Path) -> dict[str, Any]:
    store = get_object_store()
    state = store.active_state(force=True)
    target.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        journal_seq = int(db.scalar(text("SELECT COALESCE(MAX(seq), 0) FROM storage_change_outbox")) or 0)
        rows = db.execute(select(StorageObject.namespace, StorageObject.key, StorageObject.size_bytes, StorageObject.sha256)
                          .where(StorageObject.status == "active")).all()
    objects: dict[str, dict[str, Any]] = {}
    copied = skipped = missing = changed = 0
    mismatched: list[str] = []
    for namespace, key, size, sha in rows:
        validate_key(key)
        path = target / "objects" / namespace / key
        if path.is_file() and size is not None and path.stat().st_size == size and sha and _sha256(path) == sha:
            skipped += 1
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".part-", dir=str(path.parent))
            os.close(fd)
            try:
                info = store.download_to(namespace, key, Path(tmp))
            except ObjectNotFound:
                Path(tmp).unlink(missing_ok=True)
                missing += 1
                continue
            if sha and info.sha256 != sha:
                # Während des Backups geändert (z. B. Vorlagen-Bauteil gleicher Version neu
                # hochgeladen) oder gelöscht: gegen den aktuellen Registerstand prüfen statt das
                # ganze Backup abzubrechen (S3-014).
                current = _registry_row(namespace, key)
                if current is None or current.status != "active":
                    Path(tmp).unlink(missing_ok=True)
                    changed += 1
                    continue
                if current.sha256 != info.sha256:
                    # Echte Abweichung zwischen Register und Speicher: nicht übernehmen, melden.
                    Path(tmp).unlink(missing_ok=True)
                    mismatched.append(f"{namespace}/{key}")
                    continue
                size = current.size_bytes
                changed += 1
            os.replace(tmp, path)
            sha = info.sha256
            copied += 1
        objects[f"{namespace}/{key}"] = {"size": size, "sha256": sha}
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "profile_id": state.config.profile_id,
        "generation": state.config.generation,
        "journal_seq": journal_seq,
        "objects": objects,
        "changed_during_backup": changed,
        "mismatched": mismatched[:1000],
    }
    tmp_manifest = target / f".{MANIFEST}.part"
    tmp_manifest.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_manifest, target / MANIFEST)
    return {"copied": copied, "skipped": skipped, "missing": missing, "changed": changed, "mismatched": len(mismatched),
            "objects": len(objects), "generation": state.config.generation}


def _registry_row(namespace: str, key: str):
    with SessionLocal() as db:
        return db.execute(select(StorageObject.status, StorageObject.sha256, StorageObject.size_bytes)
                          .where(StorageObject.namespace == namespace, StorageObject.key == key)).first()


def verify_backup(target: Path) -> dict[str, Any]:
    manifest = json.loads((target / MANIFEST).read_text(encoding="utf-8"))
    problems: list[str] = []
    for name, meta in manifest["objects"].items():
        path = target / "objects" / name
        if not path.is_file():
            problems.append(f"fehlt: {name}")
        elif meta.get("sha256") and _sha256(path) != meta["sha256"]:
            problems.append(f"SHA-256 abweichend: {name}")
    return {"objects": len(manifest["objects"]), "problems": problems[:1000], "problem_count": len(problems), "ok": not problems,
            "generation": manifest["generation"], "created_at": manifest["created_at"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Objekt-Backup der aktiven Speichergeneration")
    parser.add_argument("--target", required=True, help="Zielverzeichnis des Backups")
    parser.add_argument("--verify", action="store_true", help="vorhandenes Backup gegen sein Manifest prüfen")
    args = parser.parse_args()
    target = Path(args.target)
    result = verify_backup(target) if args.verify else backup(target)
    print(json.dumps(result, ensure_ascii=False))
    if args.verify:
        return 0 if result["ok"] else 2
    return 0 if result["missing"] == 0 and result["mismatched"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
