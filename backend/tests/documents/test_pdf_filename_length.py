"""Langer Protokolltitel (Nachtlauf 2026-11-25, Verdacht 3): der Titel geht gekürzt in den
Dateinamen und damit in den Objekt-Key ein, die PDF-Ablage gelingt trotzdem."""
from __future__ import annotations

from app.core.storage import MAIN, get_object_store
from app.documents import service
from tests.factories import make_tenant


def test_filename_base_is_capped():
    name = service._filename("Traktanden " * 200, "v1.0")
    assert name.endswith("-v1.0.pdf")
    assert len(name) <= service._FILENAME_BASE_MAX + len("-v1.0.pdf")
    assert service._filename("  ", None) == "dokument.pdf"


def test_pdf_with_very_long_title_can_be_stored(db):
    tenant = make_tenant(db)
    stored = service._store_pdf(db, tenant.id, b"%PDF-1.4\n%%EOF\n", service._filename("T" * 1100, "v1.0"), None)
    try:
        assert len(stored.storage_path) < 1024
        assert get_object_store().exists(MAIN, stored.storage_path)
    finally:
        service._discard_pdf(stored.storage_path)
