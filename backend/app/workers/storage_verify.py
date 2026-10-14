"""Integritätsprüfung des aktiven Speichers gegen die Datenbank - nach einem Restore, nach einem
Cutover oder regelmässig (docs-site/docs/technik/storage/backup.md).

    python -m app.workers.storage_verify [--full] [--json bericht.json]

Prüft für die aktive Generation:
- jede Dateireferenz der Datenbank (stored_file, Mandantenlogos, Vorlagen-Bauteile, Snapshots)
  zeigt auf ein vorhandenes Objekt,
- jedes aktive Objekt im Register existiert mit der registrierten Grösse (und mit --full auch
  mit dem registrierten SHA-256),
- Objekte im Speicher ohne Registereintrag (z. B. nach einem älteren Datenbank-Restore).

Ändert nichts. Exit-Code 0 = konsistent, 2 = Abweichungen gefunden, 1 = Prüfung nicht möglich.
Damit fallen zeitlich inkonsistente Backups von Datenbank und Objektspeicher (Szenario: DB älter
oder neuer als der Objektstand) auf, bevor die Anwendung wieder freigegeben wird.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.objstore_client import StorageError
from app.core.storage import get_object_store
from app.models import StorageObject
from app.services.storage_migration_service import database_references

LIMIT = 1000


def verify(*, full: bool = False) -> dict[str, Any]:
    store = get_object_store()
    store.invalidate()
    state = store.active_state(force=True)
    backend = store.backend_for(state.config)
    report: dict[str, Any] = {
        "checked_at": datetime.now(UTC).isoformat(),
        "profile_id": state.config.profile_id,
        "generation": state.config.generation,
        "full": full,
        "missing_references": [],
        "registry_missing": [],
        "registry_mismatch": [],
        "unregistered_objects": [],
    }
    with SessionLocal() as db:
        refs = database_references(db)
        registry = {(row.namespace, row.key): row for row in db.execute(
            select(StorageObject.namespace, StorageObject.key, StorageObject.size_bytes, StorageObject.sha256)
            .where(StorageObject.status == "active")).all()}
    present: dict[tuple[str, str], int] = {}
    for namespace in ("main", "abgabebox"):
        for info in backend.list(namespace, ""):
            present[(namespace, info.key)] = info.size
    present_dirs = {(ns, "/".join(key.split("/")[:i]) + "/") for ns, key in present for i in range(1, len(key.split("/")))}
    for (namespace, key), kind in refs.items():
        found = (namespace, key) in present_dirs if kind.startswith("prefix:") else (namespace, key) in present
        if not found:
            report["missing_references"].append({"namespace": namespace, "key": key, "kind": kind})
    for (namespace, key), row in registry.items():
        size = present.get((namespace, key))
        if size is None:
            report["registry_missing"].append({"namespace": namespace, "key": key})
            continue
        if row.size_bytes is not None and size != row.size_bytes:
            report["registry_mismatch"].append({"namespace": namespace, "key": key, "reason": "size"})
            continue
        if full and row.sha256:
            try:
                ok = store.verify(namespace, key, sha256=row.sha256, size=row.size_bytes, full=True)
            except StorageError:
                ok = False
            if not ok:
                report["registry_mismatch"].append({"namespace": namespace, "key": key, "reason": "sha256"})
    if registry:
        # Nur sinnvoll, wenn das Register befüllt ist (nach der Erstmigration).
        report["unregistered_objects"] = [
            {"namespace": ns, "key": key} for ns, key in sorted(present) if (ns, key) not in registry and not key.startswith("_hocx-connection-test/")
        ]
    counts = {name: len(report[name]) for name in ("missing_references", "registry_missing", "registry_mismatch", "unregistered_objects")}
    for name in counts:
        report[name] = report[name][:LIMIT]
    report["counts"] = counts
    report["consistent"] = counts["missing_references"] == 0 and counts["registry_missing"] == 0 and counts["registry_mismatch"] == 0
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--full", action="store_true", help="Inhalte vollständig lesen und SHA-256 prüfen")
    parser.add_argument("--json", help="Bericht zusätzlich als JSON-Datei schreiben")
    args = parser.parse_args()
    try:
        report = verify(full=args.full)
    except Exception as exc:  # noqa: BLE001 - CLI meldet jeden Fehler mit Exit-Code 1
        print(f"Prüfung nicht möglich: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"consistent": report["consistent"], "generation": report["generation"], "counts": report["counts"]}, ensure_ascii=False))
    return 0 if report["consistent"] else 2


if __name__ == "__main__":
    sys.exit(main())
