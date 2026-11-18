"""Fingerabdrücke der Seitentexte eines PDFs für die Prüfseite (Migration 0185).

Ist eine Datei nicht mehr byte-genau das Original (z. B. auf dem Handy neu gespeichert), ordnet die
Prüfseite sie über die Dokument-ID zu und vergleicht Seite für Seite. Dafür speichert das Register
je Seite einen Fingerabdruck - nicht den Text und nicht das PDF.

Gleiche Regel wie im Browser (abgabebox-frontend/lib/pdf-fingerprints.ts), sonst stimmt nichts:
Text der Seite → Unicode-NFKC → Kleinbuchstaben → nur Buchstaben und Ziffern (Reihenfolge bleibt,
Leerzeichen, Zeilenumbrüche und Satzzeichen fallen weg, weil Extraktoren sie verschieden setzen) →
SHA-256 über ``hocx-page-v1:<dokument-id>:<text>`` → die ersten 16 Hex-Zeichen. Das Salz mit der
Dokument-ID verhindert, dass gleiche Seiten verschiedener Dokumente gleich aussehen.

Gleicher Text heisst nicht «Original»: das bleibt dem exakten Hash vorbehalten. Der Seitenvergleich
ist ein Hinweis, was sich geändert hat.
"""
from __future__ import annotations

import hashlib
import logging
import unicodedata

logger = logging.getLogger(__name__)

VERSION = "hocx-page-v1"
# Grenze der Prüfanfrage (Body-Limit der Prüfseite): mehr Seiten werden nicht verglichen
MAX_PAGES = 150
LENGTH = 16


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).lower()
    return "".join(char for char in folded if unicodedata.category(char)[0] in "LN")


def fingerprint(document_id: str, text: str) -> str:
    return hashlib.sha256(f"{VERSION}:{document_id.lower()}:{normalize(text)}".encode()).hexdigest()[:LENGTH]


def page_texts(pdf: bytes) -> list[str]:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf)
    try:
        texts: list[str] = []
        for index in range(min(len(document), MAX_PAGES)):
            page = document[index]
            textpage = page.get_textpage()
            try:
                texts.append(textpage.get_text_range())
            finally:
                textpage.close()
                page.close()
        return texts
    finally:
        document.close()


def compute(document_id: str, pdf: bytes) -> list[str] | None:
    """Fingerabdrücke aller Seiten (höchstens MAX_PAGES); None, wenn das PDF nicht lesbar ist -
    dann gibt es für dieses Dokument nur die Zuordnung über die ID, kein Export scheitert daran."""
    try:
        return [fingerprint(document_id, text) for text in page_texts(pdf)]
    except Exception:  # noqa: BLE001 - nur ein Zusatz der Prüfseite, nie ein Exportfehler
        logger.warning("Seiten-Fingerabdrücke nicht berechnet", exc_info=True)
        return None
