"""Migrationen des Layoutformats (TemplateContent.schema_version).

Gespeicherte Revisionen bleiben unverändert in der Datenbank (veröffentlichte Revisionen sind
unveränderlich). Beim Laden hebt ``migrate_content`` ältere Formate schrittweise auf die
aktuelle Version an; der Designer speichert beim nächsten Entwurf automatisch im neuen Format.

Neue Schemaversion: ``LAYOUT_SCHEMA_VERSION`` in layout.py erhöhen, ``Literal`` von
``TemplateContent.schema_version`` erweitern und hier eine Funktion ``_v<n>_to_v<n+1>`` in
``MIGRATIONS`` eintragen. Jede Migration ist rein (dict → dict) und getestet
(tests/documents/test_layout_migrations.py).
"""
from __future__ import annotations

import copy
from typing import Any, Callable

from app.documents.layout import LAYOUT_SCHEMA_VERSION

# Version n → Funktion, die ein Dokument der Version n in Version n+1 überführt.
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


class LayoutMigrationError(ValueError):
    pass


def migrate_content(raw: dict[str, Any]) -> dict[str, Any]:
    data = copy.deepcopy(raw)
    version = int(data.get("schema_version") or LAYOUT_SCHEMA_VERSION)
    if version > LAYOUT_SCHEMA_VERSION:
        raise LayoutMigrationError(f"Layoutversion {version} ist neuer als diese hocX-Version ({LAYOUT_SCHEMA_VERSION})")
    while version < LAYOUT_SCHEMA_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise LayoutMigrationError(f"keine Migration für Layoutversion {version}")
        data = step(data)
        version += 1
        data["schema_version"] = version
    data["schema_version"] = LAYOUT_SCHEMA_VERSION
    return data
