"""Gezielter Metadaten-Backfill für vorhandene Bilder (siehe app/services/image_metadata_backfill.py).

Aufruf im Backend-Container:

    docker compose exec backend python -m scripts.backfill_image_metadata --dry-run
    docker compose exec backend python -m scripts.backfill_image_metadata
    docker compose exec backend python -m scripts.backfill_image_metadata --tenant-id 3 --limit 500

Sicher wiederholbar und fortsetzbar: bereits analysierte Bilder werden übersprungen (ausser mit
--rescan), jede Charge wird einzeln committet. Gibt am Ende eine JSON-Auswertung aus.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fehlende Bildmetadaten (Aufnahmedatum, GPS, Kamera) aus vorhandenen Originalen ergänzen")
    parser.add_argument("--tenant-id", type=int, default=None, help="nur diesen Mandanten (interne id)")
    parser.add_argument("--limit", type=int, default=None, help="höchstens so viele Bilder prüfen")
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--rescan", action="store_true", help="auch bereits analysierte Bilder erneut prüfen (nur ergänzend)")
    parser.add_argument("--dry-run", action="store_true", help="analysieren, aber nichts speichern")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from app.core.db import SessionLocal
    from app.services.image_metadata_backfill import run_backfill

    db = SessionLocal()
    try:
        report = run_backfill(
            db,
            tenant_id=args.tenant_id,
            limit=args.limit,
            batch_size=max(1, args.batch_size),
            rescan=args.rescan,
            dry_run=args.dry_run,
        )
    finally:
        db.close()
    print(json.dumps({"dry_run": args.dry_run, **report.as_dict()}, indent=2))
    for error in report.errors[:50]:
        print(f"Fehler: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
