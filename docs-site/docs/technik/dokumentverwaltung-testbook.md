# Testbook: Dokumentverwaltung (logische Dokumente, PDF-Ansicht, Textextraktion)

Dieses Testbook prüft die logische Dokumentebene im Dateien-Tab: Anlage aus allen Uploadwegen,
PDF-Konvertierung und Textextraktion im `document-worker`, Versionen von Protokollexporten der
Dokument-Engine, Aufbewahrung, Rechte und Monitoring. Architektur: [Dokumentverwaltung](dokumente.md),
Betrieb: RUNBOOK Abschnitt 16.

## Vorbereitung und Ausführung

Testdatenbank auf `alembic upgrade head`. Das Backend-Testimage enthält LibreOffice, Tesseract
und Poppler; Testdateien liegen unter `backend/tests/fixtures/documents/` (erzeugt mit
`generate.py`).

```bash
./scripts/test.sh backend    # alle Dokument-Tests
./scripts/test.sh frontend   # Dateien-Tab, Dokumentdetails
```

Gezielt:

```bash
python -m pytest tests/test_document_api.py tests/test_document_processing.py \
  tests/test_document_extraction.py tests/test_document_conversion.py tests/test_document_backfill.py \
  tests/test_document_upload_paths.py tests/test_document_uploads.py \
  tests/documents/test_protocol_export_documents.py tests/test_system_health_document_queue.py
```

## Automatisierte Prüfungen

Testdateien unter `backend/tests/`, sofern nicht anders angegeben.

### Anlage und Verarbeitung

| ID | Prüfung | Erwartung | Testdatei / Test |
|---|---|---|---|
| DOC-01 | Uploadwege (Dateien-Tab, Word-Import, Abgabebox) | je ein Dokument mit Version, Original und Aufträgen; Abgabebox einmal und aus dem eigenen Namespace | `test_document_upload_paths.py`, `test_document_processing.py::test_sync_registers_abgabebox_documents_once_and_skips_non_documents`, `::test_abgabebox_original_is_read_from_its_own_namespace` |
| DOC-02 | Formate | DOCX zwei Aufträge, PDF ohne Konvertierung, XLSX PDF + Extraktion, ODS nur PDF, Bilder/ZIP nie | `test_document_processing.py::test_docx_upload_*`, `::test_pdf_upload_*`, `::test_xlsx_gets_pdf_and_extraction_jobs`, `::test_spreadsheet_gets_pdf_job_but_extraction_is_unsupported`, `::test_images_and_archives_never_become_documents` |
| DOC-03 | Konvertierung (LibreOffice) und Sandbox | Office/Text/CSV → PDF, DOC → DOCX, defekte Dateien sauber abgelehnt; Kindprozess mit Zeit-, Speicher-, Dateigrenze, ohne Secrets | `test_document_conversion.py` |
| DOC-04 | Extraktion | Struktur und Reihenfolge je Format, Seitenzahlen, Markdown, CSV- und XLSX-Tabellen, Kodierung, Normalisierung, keine externen Entities | `test_document_extraction.py` |
| DOC-05 | OCR | gescanntes PDF erkannt bzw. `ocr_required` ohne erfundenen Text | `test_document_conversion.py::test_ocr_recognizes_scanned_pdf`, `test_document_processing.py::test_scanned_pdf_*` |
| DOC-06 | Aufträge | Virenscan ausstehend verschiebt ohne Versuch, infiziert blockiert, Backoff und Aufgeben, Leases, Mandanten-Abgleich, Requeue nur gescheiterter | `test_document_processing.py` |
| DOC-07 | Löschen und Aufräumen | Original weg → Dokument und erzeugte Dateien weg; verwaiste Dateien entfernt; Tombstones bis zum Purge | `test_document_processing.py::test_releasing_the_original_*`, `::test_deleting_the_original_directly_*`, `::test_orphaned_generated_files_are_removed`, `test_storage_purge.py::test_deleting_a_document_version_keeps_its_files_until_the_purge` |
| DOC-08 | Backfill | alle Herkunftstabellen, wiederholbar; Admin-Werkzeug `backfill`/`requeue` | `test_document_backfill.py` |

### Protokollexporte der Dokument-Engine (Release 1.2.0)

Testdatei `backend/tests/documents/test_protocol_export_documents.py`.

| ID | Prüfung | Erwartung | Test |
|---|---|---|---|
| PEX-01 | Wiederholter Export | gleicher Inhalt ersetzt die Darstellung, neuer Inhalt neue Version (Label der Engine, z. B. `v0.1`); ein Dokument je Protokoll und Dokumenttyp | `test_repeated_exports_form_versions_of_one_document` |
| PEX-02 | Andere Sprache/Vorlage | keine neue Version | `test_design_change_does_not_create_a_version` |
| PEX-03 | Backfill bestehender Exporte | chronologisch, wiederholbar; erster neuer Export übernimmt erst die Historie | `test_backfill_maps_existing_exports_in_order_and_is_repeatable`, `test_first_new_export_backfills_history_before_appending` |
| PEX-04 | Datei schon freigegeben | übersprungen | `test_backfill_skips_exports_whose_file_is_gone` |
| PEX-05 | Aufbewahrung | Dateien von Dokumentversionen werden nie freigegeben | `test_export_retention_keeps_files_that_are_document_versions`, `tests/test_export_retention.py` |
| PEX-06 | Eine Version löschen | nur diese, aktuelle Version richtig gesetzt | `test_deleting_an_export_file_removes_only_that_version` |

### API, Rechte, Dateien-Tab, Monitoring

| ID | Prüfung | Erwartung | Testdatei / Test |
|---|---|---|---|
| API-01 | Details, Dateien je Rolle, Text in drei Formaten | PDF inline, Original als Download, Nicht-PDF nie inline | `test_document_api.py::test_detail_*`, `::test_file_endpoint_*`, `::test_non_pdf_original_is_never_served_inline`, `::test_text_endpoint_*` |
| API-02 | Rechte | Mandantentrennung, Leser nie mehr als am Original, Abgabebox-Feature, fremde Version unerreichbar, infiziert/ungeprüft gesperrt, Auth überall | `test_document_api.py` |
| API-03 | Routen neben der Dokument-Engine | `GET /api/documents/exports` landet bei der Engine, nie als `{document_id}` | `test_document_api.py::test_engine_routes_take_precedence_over_document_ids` |
| API-04 | Dateien-Tab | ein Eintrag je Dokument mit PDF-Vorschau, Protokollexport einmal (aktuelle Version) | `test_document_api.py::test_files_tab_*` |
| MON-01 | Check `document_queue` | gestaute fällige oder in 24 h endgültig gescheiterte Aufträge → Warnung mit ntfy-Text | `test_system_health_document_queue.py` |
| FE-01 | Dateien-Tab und Dokumentdetails | Status, PDF-Ansicht, Versionen, Upload mit Vorab-Abgleich | `frontend/components/files/files-view.test.tsx`, `document-panel.test.tsx`, `document-upload-modal.test.tsx` |

## Manuelle Prüfungen

| ID | Durchführung | Erwartung |
|---|---|---|
| DVW-M1 | DOCX, XLSX, ODT, gescanntes PDF hochladen | Status wechselt zu «bereit»; PDF-Ansicht und Text (XLSX je Blatt als Tabelle, Scan per OCR) |
| DVW-M2 | Protokoll exportieren, Inhalt ändern, erneut exportieren | Dateien-Tab zeigt ein Dokument «Protokoll» mit zwei Versionen; alte Version weiter abrufbar |
| DVW-M3 | `document-worker` stoppen, Dokument hochladen, 30 min warten | Check «Dokumentverarbeitung» Warnung, ntfy; nach Start abgearbeitet und «behoben» |
| DVW-M4 | Nach dem Update: `python -m app.workers.document_admin status` | Backfill läuft, Zähler sinken, keine Dauerfehler |
| DVW-M5 | Datei mit externen Verknüpfungen (z. B. DOCX mit verlinktem Bild auf externe URL) | Konvertierung ohne Netzwerkzugriff (Worker-Logs/Netzwerk) |

## Grenzen

- Die Qualität der OCR ist nur stichprobenartig (DOC-05, DVW-M1) belegt.
- Bestehende XLSX-Dokumente erhalten den Text erst über «Erneut verarbeiten».
