# Testbook: Release 1.2.0 (Zusammenspiel der Features und Update von 1.1.13)

Release 1.2.0 führt fünf Entwicklungszweige zusammen. Die Fachtestbooks prüfen jedes Feature
für sich ([Dokument-Engine](dokument-engine-testbook.md), [Objektspeicher](storage-testbook.md),
[Backup](backup-testbook.md), [Dokumentverwaltung](dokumentverwaltung-testbook.md),
[Upload und Bild-Metadaten](upload-testbook.md)). Dieses Testbook deckt ab, was erst durch die
Kombination entsteht, und die Abnahme des Updates. Update-Schritte: `CHANGELOG.md`, Abschnitt
1.2.0.

## Ausführung

Alle Suiten (entspricht der CI):

```bash
./scripts/test.sh backend
./scripts/test.sh abgabebox-backend
./scripts/test.sh photo-analysis-worker
./scripts/test.sh frontend
./scripts/test.sh abgabebox-frontend
./scripts/test.sh scripts
python3 scripts/check-design-rules.py && python3 scripts/check-i18n-completeness.py \
  && python3 scripts/check-i18n-hardcoded-text.py && python3 scripts/check-i18n-key-resolution.py
scripts/sync-objstore-client.sh --check
shellcheck $(git ls-files '*.sh') .githooks/pre-commit
```

Nachweis Stand Release-Branch (2026-10-16): Backend 2229 ✓, Abgabebox-Backend 96 ✓,
Foto-Worker 26 ✓, Frontend 560 ✓ + `tsc` ✓, Abgabebox-Frontend 49 ✓ + `tsc` ✓, Skript-Tests ✓,
shellcheck ✓, Design/i18n/Katalog ✓. E2E-Suiten nicht ausgeführt.

## Automatisierte Integrationsfälle

| ID | Zusammenspiel | Erwartung | Testdatei / Test |
|---|---|---|---|
| INT-01 | Document Studio × Objektspeicher | Assets, erzeugte PDFs und Protokollbilder im PDF über den Objektspeicher; Löschen als Tombstone | `backend/tests/documents/test_document_studio_api.py::test_asset_upload_validation_and_usage`, `documents/test_registry.py`, `documents/test_providers.py::test_unscanned_images_are_not_embedded`, `test_export_retention.py` |
| INT-02 | Dokument-Engine × Dokumentverwaltung | Protokoll-PDFs werden Dokumentversionen; Aufbewahrung schont sie | `backend/tests/documents/test_protocol_export_documents.py` |
| INT-03 | Dokument-Engine × Dokumentverwaltung (API) | gemeinsamer Präfix `/api/documents/`, Engine-Routen haben Vorrang | `backend/tests/test_document_api.py::test_engine_routes_take_precedence_over_document_ids` |
| INT-04 | Backup × Löschen nach dem Commit | Purge sichert Tombstones in den Hold (Migration `0123`) | `backend/tests/test_backup_hold.py::test_delete_under_hold_preserves_the_registered_content`, `::test_failed_preservation_aborts_the_destructive_write` |
| INT-05 | Bild-Metadaten × Objektspeicher | Standortschutz, Exportfassung und Live-Photo-Clip aus dem Objektspeicher | `backend/tests/test_album_share_location.py`, `test_image_export.py` |
| INT-06 | Bild-Metadaten × Dokumentverwaltung | Dateien-Tab-UNION mit `date_source` auch für Protokollexporte | `backend/tests/test_document_api.py::test_files_tab_shows_current_protocol_export_once` |
| INT-07 | Mandanten-Import (ZIP und Borg-Restore) × Dokumentenregister | Register ohne belegende PDF «importiert, nicht verifiziert» | `backend/tests/test_tenant_export_import.py::test_import_marks_registry_entries_without_matching_pdf_as_unverified` |
| INT-08 | Dokumentverwaltung × Bestand | XLSX-Extraktion mit openpyxl (Abhängigkeit der Engine) | `backend/tests/test_document_extraction.py::test_xlsx_*`, `test_document_processing.py::test_xlsx_gets_pdf_and_extraction_jobs` |
| INT-09 | Monitoring | Check `document_queue`; Checks und Alarmtexte aller Zweige vorhanden | `backend/tests/test_system_health_document_queue.py`, `test_storage_health.py`, `test_admin_backups.py::test_health_checks_include_backup` |
| INT-10 | Hintergrund-Loops | alle 16 Loops starten mit dem echten Lifespan; Lock-IDs eindeutig | `backend/tests/test_app_lifespan_smoke.py` |
| INT-11 | Alembic | eine Head-Revision `0126_verify_domain`; Revisions-IDs ≤ 32 Zeichen | Test-Stack `test-migrations` (`alembic upgrade head`) |
| INT-12 | Release-Konfiguration | 12 gehärtete Dienste, document-worker ohne Anmelde-Secrets, Worker mit Backend-Image im Rollback-Manifest | `scripts/tests/test_release_config.sh` |

## Manuelle Abnahme auf der Testumgebung

Vorher: Kopie eines Datenstands von 1.1.13 mit alten TeX-Vorlagen (Logo, eigene Schrift,
Slots), Protokollen mit Exporten, Galerie mit GPS-Fotos, Abgabebox-Uploads und
Office-Dokumenten. Ergebnis, Datum und Version je Fall festhalten.

| ID | Durchführung | Erwartung |
|---|---|---|
| REL-M1 | Update nach `CHANGELOG.md` (1.2.0) von 1.1.13: `update_deploy_code.sh`, `deploy.sh test` | Pre-Deploy-Dump angelegt, Secrets ergänzt, Migrationen bis `0151`, alle Dienste laufen, Smoke-Checks inkl. document-/storage-/job-worker grün |
| REL-M2 | `/admin/system` und `/admin/jobs` | Checks «Öffentliche Prüfseite», «Dateispeicher», «Storage-Migration», «Backup», «Dokumentverarbeitung» bewertet; keine nicht registrierten Jobs |
| REL-M3 | Fachtestbooks DOC-M1/M2, DVW-M1/M2, PRE-M1, DAT-M3 auf dem Dateisystem, dann Erstmigration auf lokales S3 (STO-M1) und dieselben Fälle erneut | identische Ergebnisse vor und nach der Migration; Studio-Logos und -Schriften in PDFs vorhanden |
| REL-M4 | `cleanup-legacy-document-templates.sh --dry-run`, dann ohne, **vor** REL-M3-Migration | nur TeX-Code entfernt, Logos/Schriften bleiben; Prüfbericht der Migration ohne Altlasten |
| REL-M5 | Rollback-Probe: auf einer Kopie bewusst ein Release mit fehlschlagendem Smoke-Check deployen (z. B. Frontend-Image ohne Start) | `deploy.sh` startet das vorherige Image-Set; storage-, backup-, document-worker gestoppt (vorheriges Release 1.1.13 ohne sie) bzw. mit altem Image neu gestartet |
| REL-M6 | Borg einrichten (RUNBOOK 15), Backup während Uploads/Löschungen und Protokoll-Exporten laufen lassen, danach Restore-Test | Backup «completed», Restore-Test grün, keine fehlenden Objekte |
| REL-M7 | Mandant als Kopie aus dem Backup wiederherstellen | Brand-Profile, Vorlagen, Dokumente mit Versionen, Fotos mit Metadaten und Standortschaltern vorhanden |
| REL-M8 | E2E-Suite `./scripts/e2e.sh up && ./scripts/e2e.sh test` inkl. `frontend/e2e/csp.spec.ts` | grün; Nonce-CSP ohne Verstösse auf angemeldeten Seiten |
| REL-M9 | Light/Dark, 1440/390 px: neue Seiten (Dokumente, Storage, Wartung, Backups, Verifizierungen, Dateien-Tab) | Design-Regeln eingehalten |
| REL-M10 | Prüf-Domain: Feature `verify_domain` einem Testmandanten zuordnen, `verify.<testdomain>` mit TXT und CNAME auf die Abgabebox-Domain einrichten, Name/Logo freigeben, Protokoll exportieren; QR-Code scannen; dieselbe Datei auf der zentralen Prüfseite prüfen; ein Dokument eines anderen Mandanten auf der Prüf-Domain prüfen; Feature entziehen | Zertifikat ausgestellt, `/` leitet auf `/verify`, Abgabe-Links 404; PDF-Fusszeile/QR zeigen die Prüf-Domain; zentrale Seite leitet nach 4 s weiter und prüft dort ohne erneute Dateiauswahl, Stufe «Prüf-Domain verifiziert»; fremdes Dokument wird als fremd markiert und weitergeleitet; nach Entzug kein Routing mehr, neue PDFs mit zentraler Prüfseite |

## Bekannte Lücken

- Die E2E-Suiten sind für 1.2.0 noch nicht gelaufen (REL-M8).
- Der Rollback von `deploy.sh` ist nur in der Konfiguration automatisiert geprüft (INT-12),
  der Ablauf nur manuell (REL-M5). Migrationen werden dabei nie zurückgerollt; `0115` ist nicht
  umkehrbar.
- `test_backup_resilience.py::test_unknown_ssh_key_is_rejected` war unter hoher Last einmal
  instabil (Fehlercode `connection_lost` statt `ssh_auth_failed`), isoliert stabil.
- Dependabot-Updates (Python 3.14, Node 25, Postgres 18, Redis 8, Traefik 3.7, Actions) sind
  nicht Teil von 1.2.0 und brauchen eigene Tests.
