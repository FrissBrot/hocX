# Testbook: Objektspeicher (S3), Storage-Migration und Wartung

Dieses Testbook prüft die Objektspeicher-Abstraktion (Dateisystem und S3), Speicherprofile,
Erst- und Live-Migrationen mit Cutover, das Löschen nach dem Commit (Tombstones), den
Wartungsmodus und das Monitoring. Architektur und Betrieb: [Dateispeicher](storage/index.md),
RUNBOOK Abschnitt 14.

## Vorbereitung und Ausführung

Testdatenbank auf `alembic upgrade head`. Der Test-Stack startet ein isoliertes Garage-S3
(`test-s3`, Initialisierung `test-s3-init`); Tests mit `requires_s3` werden ohne es
übersprungen, nicht als Fehler gemeldet.

```bash
./scripts/test.sh backend             # Objektspeicher, Migration, Wartung, Purge
./scripts/test.sh abgabebox-backend   # Rollenbindung, Quarantäne, Upload-I/O
./scripts/test.sh photo-analysis-worker
./scripts/test.sh frontend            # /admin/storage, Wartungshinweis
./scripts/test.sh scripts             # Env-Migration, Release-Konfiguration
scripts/sync-objstore-client.sh --check   # Kopien des Clients synchron
```

## Automatisierte Prüfungen

Testdateien unter `backend/tests/`, sofern nicht anders angegeben.

### Abstraktion und Backends

| ID | Prüfung | Erwartung | Testdatei / Test |
|---|---|---|---|
| OBJ-01 | Keys | Traversal, Steuerzeichen, Client-Endungen abgelehnt (Python und SQL) | `test_object_storage.py::test_validate_key_*`, `::test_safe_suffix_never_takes_unsafe_client_input`, `::test_register_write_rejects_invalid_keys_in_the_database_as_well` |
| OBJ-02 | Dateisystem-Backend | atomar geschrieben, Integrität geprüft, Range/Liste, kein Ausbruch | `test_object_storage.py::test_filesystem_backend_*`, `::test_object_response_uses_file_response_for_the_filesystem` |
| OBJ-03 | S3-Backend | Roundtrip, Range, Copy, Multipart grosser Dateien, Hash-Prüfung, Abbruch alter Multiparts | `test_object_storage.py::test_s3_backend_*` (`requires_s3`) |
| OBJ-04 | Schreibprotokoll | Journal mit steigenden Versionen; Fence blockiert, Cutover wartet auf offene Schreiber; veraltete Generation verweigert | `test_object_storage.py::test_put_and_delete_are_journaled_with_increasing_versions`, `::test_write_is_rejected_while_storage_is_fenced`, `::test_fence_waits_for_open_write_transactions`, `::test_register_write_rejects_a_stale_generation` |
| OBJ-05 | Fehlerklassen und Erreichbarkeit | anbieterunabhängige Fehler; nicht erreichbar ≠ fehlt; 503 statt 500 | `test_object_storage.py::test_client_errors_map_to_provider_independent_classes`, `::test_unreachable_endpoint_is_reported_as_unavailable_not_as_missing`, `test_storage_migration_faults.py::test_unreachable_storage_yields_503_not_500` |
| OBJ-06 | Endpoint-Pinning (S3-009) | Auflösung bei jeder Verbindung geprüft, Loopback/Rebinding abgelehnt | `test_storage_endpoint_pinning.py` |
| OBJ-07 | Rollenbindung | Abgabebox schreibt nur in ihren Namespace, eingeschränkte Zugangsdaten erreichen den Haupt-Bucket nicht | `abgabebox-backend/tests/test_storage_role_scoping.py`, `test_object_storage.py::test_restricted_abgabebox_credentials_cannot_reach_the_main_bucket` |

### Löschen nach dem Commit (S3-008)

| ID | Prüfung | Erwartung | Testdatei / Test |
|---|---|---|---|
| PUR-01 | Rollback eines Löschens | Objekt und Registereintrag bleiben | `test_storage_purge.py::test_rollback_of_a_delete_keeps_the_object_and_its_registration` |
| PUR-02 | Purge-Job | löscht committete Tombstones, nie neu geschriebenen Inhalt, überspringt gehaltene Keys, endet still bei Fence | `test_storage_purge.py` |
| PUR-03 | Dokumentversionen und Exporte | Dateien verschwinden erst nach dem Purge | `test_storage_purge.py::test_deleting_a_document_version_keeps_its_files_until_the_purge`, `tests/test_export_retention.py` |
| PUR-04 | Laufendes Backup | Purge sichert in den Backup-Hold | [Backup-Testbook](backup-testbook.md) HOLD-01, HOLD-04 |

### Profile, Migration, Verifikation

| ID | Prüfung | Erwartung | Testdatei |
|---|---|---|---|
| PRO-01 | Speicherprofile | gefährliche Werte und interne Endpunkte abgelehnt, Zugangsdaten verschlüsselt und nie ausgegeben, aktive/eingebaute Profile geschützt, Verbindungstest isoliert | `test_storage_profiles.py` |
| MIG-01 | Zustandsmaschine | vollständige, sichere Übergänge; Erstmigration nimmt nur Caches/Temporäres aus | `test_storage_state_machine.py` |
| MIG-02 | Ende-zu-Ende-Kette Dateisystem → lokales S3 → externes S3 → … | jede bestätigte Datei kommt an | `test_storage_migration_e2e.py` (`requires_s3`) |
| MIG-03 | Fehlerfälle | Wiederholungen, Leases, Absturz/Fortsetzung, gescheiterter Cutover, Journal-Lücken, gleichzeitige Starts, Abbruch/Pause, fehlende Quellobjekte, Aufräumen alter Generationen | `test_storage_migration_faults.py` |
| MIG-04 | Referenzprüfung | Registereinträge ohne Datei werden gemeldet; abgelaufene Exporte zählen nicht als fehlend; Document-Studio-Assets sind Referenzen | `test_storage_migration_faults.py::test_initial_migration_surfaces_registered_files_missing_on_disk`, `::test_expired_exports_are_not_counted_as_missing_references`, `::test_storage_verify_detects_objects_missing_after_an_inconsistent_restore` |
| MIG-05 | Worker-Konfiguration | spoolt auf Platte (nicht tmpfs), ungültige Optionen 409 | `test_storage_worker_config.py` |
| MIG-06 | Objekt-Backup (Altweg `backup_storage`) | Änderungen während des Laufs übernommen, echte Abweichungen gemeldet | `test_storage_backup.py` |

### Wartung, Monitoring, Kontingent, Oberfläche

| ID | Prüfung | Erwartung | Testdatei |
|---|---|---|---|
| MNT-01 | Wartungszustände und Freigabe | ungültige Übergänge abgelehnt, Freigabe nur bei allen Bedingungen, Supervisor gibt nie selbst frei | `test_maintenance.py` |
| MNT-02 | Serverseitige Sperre | volle Wartung sperrt API ausser Ausnahmen und schliesst WebSockets; Schreib-Fence sperrt nur Schreibzugriffe | `test_maintenance.py::test_full_maintenance_*`, `::test_partial_write_fence_blocks_only_writes` |
| MNT-03 | Öffentlicher Status und Schätzung | ohne interne Details, konservativ | `test_maintenance.py::test_public_status_*`, `::test_estimator_*` |
| MON-01 | Checks `object_storage`, `storage_migration` | aktive Generation, Eskalation bei Rollback/stehendem Worker, deutsche ntfy-Titel | `test_storage_health.py` |
| KON-01 | Kontingent und Belegung | Kategorien je Herkunft inkl. erzeugter Dokument-PDFs, Mandantentrennung, Admin-Routen | `test_storage_usage.py`, `test_storage_packages.py`, `test_document_backfill.py::test_generated_pdfs_count_as_files_in_storage_usage` |
| ABX-01 | Abgabebox | Quarantäne wie im Backend, Objektspeicher-I/O nicht in der Event-Loop | `abgabebox-backend/tests/test_storage_quarantine_parity.py`, `abgabebox-backend/tests/test_upload_storage_io_off_event_loop.py` |
| FE-01 | Adminportal Storage, Wartungshinweis, Speicheransicht | Profile/Migrationen bedienbar, Hinweis bei Wartung, Belegung je Kategorie | `frontend/components/admin/admin-storage.test.tsx`, `frontend/components/maintenance/maintenance-notice.test.tsx`, `frontend/components/storage/storage-usage-view.test.tsx` |
| OPS-01 | Env-Migration und Release-Konfiguration | neue Secrets ergänzt, Dienste gehärtet | `scripts/tests/test_env_migrate.sh`, `scripts/tests/test_release_config.sh` |

## Manuelle Prüfungen

| ID | Durchführung | Erwartung |
|---|---|---|
| STO-M1 | Erstmigration Dateisystem → lokales S3 auf der Testumgebung (Wartung, Prüfbericht, Cutover) | Prüfbericht ohne fehlende Referenzen; App danach voll nutzbar; Altdateien als «unreferenziert» nur, wenn `cleanup-legacy-document-templates.sh` vorher nicht lief |
| STO-M2 | Live-Migration lokales S3 → externes S3 bei laufender Nutzung (Uploads, Exporte) | kein Datenverlust, Cutover kurz, Fortschritt/Restzeit plausibel |
| STO-M3 | Externes S3 kurz sperren | Check «Dateispeicher» kritisch mit ntfy, Uploads 503 mit Hinweis, nach Freigabe «behoben» |
| STO-M4 | Wartungsfenster planen, starten, beenden | Anmeldeseite und Abgabebox zeigen den Hinweis, Freigabe erst bei erfüllten Bedingungen |
| STO-M5 | Videos und grosse Dateien nach der Migration | Range-Requests (Safari), Downloads ohne Speicherspitze im Backend |
| STO-M6 | `python -m app.workers.storage_verify --full` nach der Migration | Exit 0 |

## Grenzen

- Ohne laufendes Test-S3 sind die S3-Fälle nur übersprungen, nicht bestanden.
- Anbieterspezifisches Verhalten (AWS, Hetzner) ist nur manuell prüfbar (STO-M2, STO-M3).
