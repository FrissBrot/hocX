# Testbook: Backup und Restore (BorgBackup)

Dieses Testbook prüft das Offsite-Backup (backup-worker, Borg 1.4, Hetzner Storage Box):
Konsistenz zwischen Datenbank und Objektspeicher, inkrementelle Sicherung ohne lokalen Spiegel,
Retention, Verifikation, Voll-Restore, Recovery-CLI und Mandanten-Restore als Kopie.
Architektur und Betrieb: [Backup (BorgBackup)](backup/index.md).

## Vorbereitung und Ausführung

Die Testdatenbank muss bis einschliesslich `0115_backup_system` migriert sein (im Release 1.2.0:
`alembic upgrade head`, Stand `0125_release_merge_imgmeta`). Das
Backend-Testimage enthält borg 1.4, den PostgreSQL-16-Client und `sshd`; die Tests laufen gegen
das isolierte Test-S3 (Garage) und ein lokales Borg-Repository, die SSH-Fälle gegen einen
`sshd` im Testcontainer mit `borg serve --append-only` als Ersatz für die Storage Box.

```bash
./scripts/test.sh backend      # enthält alle Backup-Tests
./scripts/test.sh frontend     # Admin-Seite /admin/backups
./scripts/test.sh scripts      # Ablösung der alten Backup-Skripte, Release-Konfiguration
```

Gezielt (Testcontainer, wie in `scripts/test.sh`):

```bash
python -m pytest tests/test_backup_core.py tests/test_backup_borg.py tests/test_backup_hold.py \
  tests/test_backup_worker_e2e.py tests/test_backup_restore_e2e.py tests/test_backup_resilience.py \
  tests/test_admin_backups.py tests/test_zz_backup_full_restore.py
```

Ohne borg 1.4 (`requires_borg`), ohne Test-S3 (`requires_s3`) bzw. ohne Root und `sshd`
(`requires_sshd`) werden die betroffenen Tests übersprungen statt fehlzuschlagen – ein
CI-Lauf ohne diese Werkzeuge ist darum kein Nachweis. `test_zz_backup_full_restore.py` läuft
bewusst zuletzt: der Voll-Restore tauscht die Test-Datenbank aus.

Bei manuellen Prüfungen Ergebnis, Datum, Version und verwendete Storage Box festhalten. Die
manuellen Fälle sind Prüfanweisungen, keine bereits ausgeführten Testnachweise.

## Automatisierte Prüfungen

Dateien relativ zu `backend/tests/` bzw. `frontend/components/admin/`.

### Kernbibliothek und Borg

| ID | Prüfung | Erwartung | Testdatei / Test |
|---|---|---|---|
| BAK-01 | Manifest schreiben und lesen | Einträge, Kopf und SHA-256 der Datei stimmen | `test_backup_core.py::test_manifest_roundtrip_and_hash` |
| BAK-02 | Manifest mit Traversal-Key, fremdem Namespace, negativer Grösse, kaputtem Hash oder Pool-Namen | `ManifestError`, nichts wird verwendet | `test_backup_core.py::test_manifest_rejects_untrusted_entries` |
| BAK-03 | Doppelter Key im Manifest | wird abgelehnt | `test_backup_core.py::test_manifest_rejects_duplicate_keys` |
| BAK-04 | Archivnamen, Pool-Pfade, Metadaten | Namen eindeutig parsebar, ungültige Pfade/Metadaten abgelehnt | `test_backup_core.py::test_archive_names_and_pool_paths`, `::test_metadata_validation` |
| BAK-05 | Tar-Stream mit falscher Grösse oder falschem SHA-256 | `ContentMismatch` | `test_backup_core.py::test_tar_stream_*` |
| BAK-06 | Retention über 500 Tage mit 6-stündlichen Punkten | alle Punkte der letzten 14 Tage, 14/8/12 täglich/wöchentlich/monatlich; Regeln vereinigt; geschützte und jüngster Punkt bleiben; `partial` zählt nicht für Perioden | `test_backup_core.py::test_retention_*` |
| BAK-07 | Konfiguration mit ungültigem Host, Kompression, fehlendem Schlüssel | `BackupConfigError`; Zusammenfassung enthält keine Secrets | `test_backup_core.py::test_config_validation` |
| BAK-08 | `import-tar`, Inhalte listen, einzeln und gesammelt lesen | Inhalte und Grössen stimmen | `test_backup_borg.py::test_import_list_extract_and_export` |
| BAK-09 | Upload mit falschem Hash abbrechen, Upload mitten im Inhalt beenden | **kein** Archiv im Repository | `test_backup_borg.py::test_aborted_or_inconsistent_import_creates_no_archive` |
| BAK-10 | Pool verkleinern (`recreate`), mehrere Archive löschen | neue Archiv-ID, nur verbleibende Inhalte, Löschung vollständig | `test_backup_borg.py::test_recreate_exclude_changes_archive_id_and_delete_many` |
| BAK-11 | Falsche Passphrase, fehlendes Repository, ungültiger Archivname | Codes `passphrase_wrong`, `repository_missing`, `invalid_argument` | `test_backup_borg.py::test_error_classification` |
| BAK-12 | SSH mit append-only-Schlüssel: löschen + `compact` | Archiv logisch weg, Daten bleiben im Repository | `test_backup_borg.py::test_ssh_append_only_and_host_key_pinning` |
| BAK-13 | Host-Key über known_hosts und über Fingerprint; falscher Key, falscher Fingerprint | richtige Keys verbinden, falsche ergeben `host_key_mismatch` (nie automatisch akzeptiert) | `test_backup_borg.py::test_ssh_append_only_and_host_key_pinning` |
| BAK-14 | Storage Box nicht erreichbar | vorübergehender Fehler (`repository_unreachable`/`connection_lost`) | `test_backup_borg.py::test_unreachable_storage_box_is_transient` |
| BAK-15 | Unbekannter SSH-Schlüssel | `ssh_auth_failed`, kein Wiederholungsfall | `test_backup_resilience.py::test_unknown_ssh_key_is_rejected` |

### Konsistenz (Backup-Hold, Copy-on-Write)

| ID | Prüfung | Erwartung | Testdatei / Test |
|---|---|---|---|
| HOLD-01 | Registriertes Objekt unter aktivem Hold löschen, danach Purge-Job | `delete` legt nur einen Tombstone an, die Datei bleibt; erst `purge_deleted` sichert den bisherigen Inhalt nach `_hocx-backup-hold/<hold>/<sha256>` und löscht dann (Migration `0123_backup_hold_tombstones`: der Hold findet auch Tombstones) | `test_backup_hold.py::test_delete_under_hold_preserves_the_registered_content` |
| HOLD-02 | Objekt unter Hold zweimal überschreiben | jeder vorherige Stand nach Inhalt gesichert | `test_backup_hold.py::test_overwrite_under_hold_preserves_the_previous_version_once` |
| HOLD-03 | Ohne Hold bzw. Hold auf anderer Generation löschen | keine Kopie | `test_backup_hold.py::test_without_hold_nothing_is_copied`, `::test_hold_on_another_generation_does_not_copy` |
| HOLD-04 | Sicherungskopie schlägt beim Purge fehl | Purge-Job bricht mit `StorageUnavailable` ab, Objekt bleibt erhalten und wird im nächsten Lauf erneut versucht | `test_backup_hold.py::test_failed_preservation_aborts_the_destructive_write` |
| HOLD-05 | Löschen/Überschreiben/Neuanlage nach dem Snapshot, während der Übertragung | Sicherungspunkt enthält den Snapshot-Stand, neue Datei fehlt, Hold-Kopien danach entfernt | `test_backup_worker_e2e.py::test_changes_during_transfer_keep_the_snapshot_content` |
| HOLD-06 | Storage-Cutover während des Backups | Backup liest die eingefrorene alte Generation zu Ende | `test_backup_worker_e2e.py::test_cutover_during_backup_reads_the_frozen_generation` |

### Backup-Lauf, Wiederaufnahme, Fehler

| ID | Prüfung | Erwartung | Testdatei / Test |
|---|---|---|---|
| RUN-01 | Erstes Backup mit Objekten in beiden Namespaces und Datenbankverweis | `completed`, alle Objekte im Punkt, Mandantenübersicht, Hold gelöst, Staging leer | `test_backup_worker_e2e.py::test_first_and_incremental_backup` |
| RUN-02 | Folgebackup mit einer neuen Datei | nur diese Datei wird aus S3 gelesen und übertragen | `test_backup_worker_e2e.py::test_first_and_incremental_backup` |
| RUN-03 | Registriertes Objekt fehlt physisch | `partial` mit Liste der fehlenden Datei, nie `completed` | `test_backup_worker_e2e.py::test_missing_object_makes_the_backup_partial` |
| RUN-04 | Worker-Absturz mitten in der Übertragung, zweiter Worker übernimmt | Auftrag wird fortgesetzt, bereits übertragene Inhalte nicht erneut, Punkt vollständig | `test_backup_worker_e2e.py::test_interrupted_backup_resumes_without_reuploading` |
| RUN-05 | Storage Box fällt nach dem ersten Pool aus und kommt zurück | Auftrag mit Backoff erneut eingeplant, Hold bleibt, danach vollständig ohne Neuübertragung | `test_backup_resilience.py::test_connection_loss_mid_backup_is_retried_and_resumes` |
| RUN-06 | Falsche Passphrase | `failed` (`borg_passphrase_wrong`), Hold gelöst | `test_backup_worker_e2e.py::test_wrong_passphrase_fails_permanently_and_releases_hold` |
| RUN-07 | Zu wenig lokaler Platz für den Dump | `failed` (`staging_insufficient`), kein Hold übrig | `test_backup_resilience.py::test_insufficient_local_space_fails_cleanly` |
| RUN-08 | Zeitplan mehrfach im selben Zeitfenster auswerten | genau ein Auftrag pro Fenster | `test_backup_worker_e2e.py::test_scheduler_enqueues_once_per_slot` |
| RUN-09 | Last: 2000 Objekte (~123 MiB), einzelne grösser als ein Batch | lokale Staging-Spitze ≈ Dump + Manifest, kein Objektspiegel; Folgesicherung überträgt nichts | `test_backup_resilience.py::test_large_object_set_needs_no_local_mirror` |

### Prüfung, Retention, Restore-Test

| ID | Prüfung | Erwartung | Testdatei / Test |
|---|---|---|---|
| VER-01 | Integritätsprüfung nach zwei Backups | `borg check`, Dump-Hash und Stichprobe ok, Punkt «geprüft» | `test_backup_worker_e2e.py::test_restore_test_verify_and_retention_with_gc` |
| VER-02 | Restore-Test (alle Objekte) | isolierte DB, Anwendungstest, jedes registrierte Objekt wiederhergestellt, Punkt «Restore getestet» | `test_backup_worker_e2e.py::test_restore_test_verify_and_retention_with_gc` |
| VER-03 | Retention mit Garbage Collection | abgelaufener Punkt entfernt, unreferenzierter Inhalt aus Pool und Index entfernt, behaltener Punkt vollständig lesbar | `test_backup_worker_e2e.py::test_restore_test_verify_and_retention_with_gc` |
| VER-04 | Manipuliertes Repository-Segment | Integritätsprüfung `failed` | `test_backup_resilience.py::test_corrupted_repository_fails_verification` |

### Restore

| ID | Prüfung | Erwartung | Testdatei / Test |
|---|---|---|---|
| RES-01 | Mandant als Kopie aus historischem Punkt, Original danach verändert | neuer Mandant mit dem **alten** Stand und allen Dateien unter `tenant_imports/tenant-<neu>/`; Original unverändert; vorhandene E-Mail nicht übernommen; Temp-DB und Restore-Bereich gelöscht | `test_backup_restore_e2e.py::test_tenant_restore_as_copy_from_historical_backup` |
| RES-02 | Mandant, der im Punkt nicht existiert | `tenant_not_in_backup`, kein Mandant angelegt | `test_backup_restore_e2e.py::test_tenant_restore_of_unknown_tenant_fails_cleanly` |
| RES-03 | Recovery-CLI: Restore in neue DB und anderes S3-Ziel (Anbieterwechsel) | Profil/Generation neu gesetzt, Wartung aktiv, Datei im neuen Ziel lesbar; zweiter Restore in dieselbe DB verweigert | `test_backup_restore_e2e.py::test_cli_full_restore_into_new_database_and_new_provider` |
| RES-04 | CLI mit Traversal-Archivname bzw. SQL im DB-Namen | Exit-Code 1, nichts ausgeführt | `test_backup_restore_e2e.py::test_cli_rejects_untrusted_archive_names` |
| RES-05 | `swap-database` | Datenbanken getauscht, alte bleibt (gesperrt) erhalten | `test_backup_restore_e2e.py::test_cli_swap_database_keeps_the_previous_database` |
| RES-06 | Absturz zwischen den beiden Umbenennungen | Worker-Start benennt die bisherige Live-DB zurück, Journal entfernt | `test_backup_restore_e2e.py::test_interrupted_database_swap_is_recovered_on_worker_start` |
| RES-07 | Voll-Restore über den Worker | Rettungspunkt (geschützt), neue DB und Generation, Tausch, Backup-Historie übernommen, Stand des Punkts aktiv, Wartung freigegeben, alte DB erhalten | `test_zz_backup_full_restore.py::test_full_restore_swaps_database_and_storage_generation` |
| RES-08 | Smoke-Test nach dem Tausch scheitert | automatischer Rücktausch (`rolled_back`), Live-Daten unverändert, kein Fence, keine Wartung | `test_zz_backup_full_restore.py::test_full_restore_with_rollback_when_smoke_test_fails` |

### Admin-API, Monitoring, Oberfläche

| ID | Prüfung | Erwartung | Testdatei / Test |
|---|---|---|---|
| ADM-01 | Status und Einstellungen lesen | keine Schlüssel, Passphrasen oder Zugangsdaten in Antworten | `test_admin_backups.py::test_status_and_settings_never_expose_secrets` |
| ADM-02 | Support-Rolle startet Backup, ändert Einstellungen, ruft Restore-Vorschau | jeweils 403, Lesen erlaubt | `test_admin_backups.py::test_support_role_can_read_but_not_start_backups` |
| ADM-03 | Doppelklick / gleicher Idempotenzschlüssel / zweiter Auftrag | derselbe Auftrag, sofortige Rückkehr mit 202 | `test_admin_backups.py::test_manual_backup_is_idempotent_and_returns_immediately` |
| ADM-04 | Backup ohne Einrichtung | 409 | `test_admin_backups.py::test_backup_rejected_when_not_configured` |
| ADM-05 | Ungültige Einstellungen und Filter | 422 | `test_admin_backups.py::test_settings_validation`, `::test_history_filters_are_validated` |
| ADM-06 | Restore-Vorschau voll und Mandant | Risiken, Bestätigungsphrase, Mandantendaten; unbekannter Mandant 409 | `test_admin_backups.py::test_restore_preview_lists_risks_and_requires_tenant_in_backup` |
| ADM-07 | Restore mit falschem TOTP, falscher Phrase, ohne TOTP-Faktor | 401 / 422 / 403; erst mit frischem Code und richtiger Phrase 202, TOTP nicht im Auftrag gespeichert | `test_admin_backups.py::test_restore_requires_fresh_totp_and_confirmation`, `::test_restore_without_totp_factor_is_forbidden` |
| ADM-08 | Bewertung: überfällig, Speicher fast voll, Prüfung fehlgeschlagen, Zeitplan aus | Probleme mit richtigem Schweregrad; drei Checks im Systemmonitoring | `test_admin_backups.py::test_evaluate_reports_overdue_and_failed_states`, `::test_disabled_schedule_is_a_warning`, `::test_health_checks_include_backup` |
| UI-01 | Übersicht | getrennte Nachweise erstellt/geprüft/Restore getestet, übersetzte Probleme, Aktionen nur für Owner | `admin-backups.test.tsx` |
| UI-02 | Manuelles Backup und laufender Auftrag | POST an `/api/admin/backups`, Fortschritt und Schritt sichtbar | `admin-backups.test.tsx` |
| UI-03 | Einstellungen | nur «vorhanden/fehlt», nie Secrets | `admin-backups.test.tsx` |
| OPS-01 | `backup_storage.sh` bei aktivem Borg-Backup | läuft nicht (ohne Docker-Aufruf), nur mit `HOCX_LEGACY_BACKUP_FORCE=true` | `scripts/tests/test_legacy_backup_guard.sh` |
| OPS-02 | Release-Konfiguration | `backup-worker` gehärtet, Backend ohne Borg-Secrets, `deploy.sh` initialisiert nie ein Repository | `scripts/tests/test_release_config.sh` |
| OPS-03 | Rollback von `deploy.sh` auf ein Release ohne `backup-worker` (z. B. 1.1.x) | Worker wird gestoppt statt mit dem neuen Image weiterzulaufen; Release-Manifest führt `HOCX_BACKEND_WORKERS` | `scripts/tests/test_release_config.sh` (Konfiguration), Ablauf manuell: [Release 1.2.0](release-1.2.0-testbook.md) REL-M5 |

## Manuelle Prüfungen und Abnahme

| ID | Durchführung | Erwartung |
|---|---|---|
| BAK-M1 | Storage Box: Backup-Schlüssel per `ssh -p 23` verwenden | Verbindung endet mit Borg-Meldung, keine Shell (append-only-Einschränkung greift) |
| BAK-M2 | `cli info` auf der Storage Box | `repokey-blake2`, gepinnte ID, borg 1.4.x (`BACKUP_REMOTE_PATH` passt) |
| BAK-M3 | Testarchiv mit Backup-Schlüssel löschen und `compact` ausführen | Belegung der Box in der Hetzner-Konsole unverändert; erst `compact` mit Wartungsschlüssel gibt frei |
| BAK-M4 | Falschen Fingerprint in `BACKUP_SSH_HOST_FINGERPRINT` eintragen, Worker neu starten | Repository-Status «nicht erreichbar» (`host_key_mismatch`), ntfy-Meldung, keine Verbindung |
| BAK-M5 | Erstes produktives Backup | `/admin/backups`: erfolgreich, Dauer, Datenmengen, nächster Termin plausibel |
| BAK-M6 | «Restore-Test starten» und Integritätsprüfung im Admin-Portal | «Restore getestet» bzw. «Geprüft» am Punkt |
| BAK-M7 | Browser-Reload und Tab-Wechsel während eines laufenden Backups | Fortschritt bleibt sichtbar, Auftrag läuft weiter |
| BAK-M8 | Mandant als Kopie über den Assistenten (Testumgebung) | neuer Mandant mit altem Stand, Hinweise sichtbar, Original unverändert |
| BAK-M9 | Voll-Restore auf der Testumgebung | Wartungsseite während des Tauschs, danach Stand des Punkts, Anmeldung möglich, `hocx_pre_restore_*` vorhanden |
| BAK-M10 | Recovery-CLI auf einem frischen Testserver nach `restore.md` | Anwendung startet mit wiederhergestellten Daten; Dateien aus dem Backup im neuen Ziel |
| BAK-M11 | `deploy.sh` bei gestopptem `backup-worker` und `BACKUP_ENABLED=true` | Update bricht vor den Migrationen ab; mit `HOCX_PRE_DEPLOY_BACKUP=skip` läuft es mit Warnung |
| BAK-M12 | ntfy: Storage Box für > 30 min sperren (z. B. Firewall) | Problem «Backup-Repository gestört» kommt einmal, nach Freigabe «behoben» |

## Bekannte Lücken

- Ein Ausfall der PostgreSQL-Datenbank mitten im Backup ist nicht automatisiert getestet.
- Das Zusammenspiel von laufendem Backup und Purge-Job ist nur auf Ebene `purge_deleted`
  (HOLD-01/-04) geprüft, nicht mit gleichzeitig laufendem `backup-worker`; manuell BAK-M7 mit
  parallelem Löschen von Dateien ergänzen.
- Hetzner-spezifisches Verhalten (BAK-M1 bis BAK-M4) ist nur manuell prüfbar.
- Der Restore-Test im Betrieb prüft Dateiinhalte standardmässig stichprobenartig; vollständig
  über «alle Objekte» (`objects=all`).
