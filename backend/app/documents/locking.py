"""Zeilensperren für die optimistische Sperre (``lock_version``) des Document Studio.

Die Prüfung ``expected_lock_version == lock_version`` ist nur dann wirksam, wenn zwischen
Lesen und Schreiben keine zweite Transaktion denselben Stand lesen kann. Deshalb sperren die
Schreibpfade die übergeordnete Zeile (Vorlage, Brand-Profil, Komponente) mit
``SELECT … FOR UPDATE`` und laden sie dabei neu (``populate_existing``): Parallele Anfragen
laufen nacheinander, die zweite sieht die erhöhte Version und erhält HTTP 409 statt die erste
still zu überschreiben. Die Vorlagensperre serialisiert zugleich das Anlegen des Entwurfs und
die Vergabe der Revisionsnummern (sonst ``IntegrityError`` -> HTTP 500).
"""
from __future__ import annotations

from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

T = TypeVar("T")


def lock_row(db: Session, obj: T) -> T:
    """Zeile von ``obj`` bis zum Ende der Transaktion sperren und mit dem aktuellen DB-Stand
    neu laden. Vor jeder Änderung an ``obj`` aufrufen (ungespeicherte Änderungen gingen sonst
    beim Neuladen verloren)."""
    model = type(obj)
    # Ergebnis abrufen: populate_existing wirkt erst beim Laden der Zeile
    return db.execute(select(model).where(model.id == obj.id).with_for_update().execution_options(populate_existing=True)).scalar_one()  # type: ignore[attr-defined]
