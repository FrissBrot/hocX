"""Ortsdaten für Foto-Standorte aus lokalen Dateien importieren (app/services/geo_places.py).

Für Installationen ohne Netz zu den Quellen (GEO_PLACES_AUTO_UPDATE=false), für den E2E-Stack
(kleiner Testdatensatz unter tests/fixtures/geo_places) und zum manuellen Nachladen:

    docker compose exec backend python -m scripts.import_geo_places \\
        --geonames-cities cities500.zip --geonames-admin1 admin1CodesASCII.txt \\
        --geonames-country CH=CH.zip --geonames-country DE=DE.zip \\
        --swissnames swissnames3d_2026_2056.csv.zip
    docker compose exec backend python -m scripts.import_geo_places --fixture   # Testdatensatz
    docker compose exec backend python -m scripts.import_geo_places --resolve   # Fotos nachtragen

Die Daten selbst liegen nie im Repo (Lizenz/Grösse), ausser dem winzigen Testdatensatz.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "geo_places"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ortsdaten (GeoNames, swissNAMES3D) aus lokalen Dateien laden")
    parser.add_argument("--geonames-cities", type=Path)
    parser.add_argument("--geonames-admin1", type=Path)
    parser.add_argument("--geonames-country", action="append", default=[], help="CODE=Datei, mehrfach")
    parser.add_argument("--swissnames", type=Path, help="CSV-ZIP oder Ordner mit *_PKT.csv/*_PLY.csv")
    parser.add_argument("--version", default="lokal")
    parser.add_argument("--fixture", action="store_true", help="kleinen Testdatensatz laden (Tests, E2E)")
    parser.add_argument("--resolve", action="store_true", help="danach Ortsnamen aller Fotos nachtragen")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from app.core.db import SessionLocal
    from app.services import geo_places, photo_places

    report: dict = {}
    # Import mit der Rolle hocx_geo (GEO_DATABASE_URL), sonst der Owner-Zugang dieses Containers;
    # die App-Rolle hocx_app darf die Zwischenablage nicht beschreiben (Migration 0260).
    db = geo_places.geo_session(allow_owner=True)
    try:
        min_rows = 1 if args.fixture else None
        cities = FIXTURE / "cities.txt" if args.fixture else args.geonames_cities
        admin1 = FIXTURE / "admin1.txt" if args.fixture else args.geonames_admin1
        countries = {"CH": FIXTURE / "CH.txt"} if args.fixture else {}
        for entry in args.geonames_country:
            code, _, path = entry.partition("=")
            countries[code.strip().upper()] = Path(path)
        if cities and admin1:
            report["geonames"] = geo_places.import_geonames_files(
                db, cities=cities, admin1=admin1, countries=countries, version=args.version, min_rows=min_rows
            )
        swiss = FIXTURE if args.fixture else args.swissnames
        if swiss:
            report["swissnames3d"] = geo_places.import_swissnames_file(db, swiss, version=args.version, min_rows=min_rows)
        if args.resolve:
            db.close()
            db = SessionLocal()
            while True:
                result = photo_places.resolve_backlog(db)
                report.setdefault("resolve", []).append(result)
                if not result.get("resolved"):
                    break
    finally:
        db.close()
    json.dump(report, sys.stdout, ensure_ascii=False, default=str, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
