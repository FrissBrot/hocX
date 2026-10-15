# Backup-Architektur (BorgBackup, Hetzner Storage Box)

Verschlüsseltes, inkrementelles Offsite-Backup von PostgreSQL **und** aktivem Objektspeicher
nach einer Hetzner Storage Box, mit BorgBackup 1.4 als Backup-Engine. Diese Seite beschreibt
das Zielbild und die Entscheidungen; Betrieb, Einrichtung und Restore stehen in
[Betrieb](betrieb.md), [Wiederherstellung](restore.md) und [Sicherheit](sicherheit.md).

## Ausgangslage (Analyse des Branches `feature/s3-storage-maintenance`)

| Komponente | Befund | Umgang |
|---|---|---|
| `scripts/backup_db.sh` | `pg_dump` (Plain-SQL, gzip) lokal nach `backups/`, Cron 03:15 | abgelöst; Skript verweigert den Lauf, sobald `HOCX_BACKUP_BORG_ENABLED=true` (Override nur explizit) |
| `scripts/backup_storage.sh` + `workers/storage_backup.py` | **vollständiger lokaler Spiegel** aller Objekte unter `backups/storage/objects/`, Konsistenz nur "praktisch immer" | abgelöst (Ziel: kein lokaler Spiegel); gleiche Sperre wie oben |
| `storage_object` / `storage_change_outbox` | Register mit Grösse, SHA-256, Version je `(namespace, key)`, in derselben Transaktion wie die fachliche Änderung | Grundlage des Objektinventars und der inkrementellen Erkennung |
| `storage_state` + `storage_begin_write()` (FOR SHARE) | jeder Schreiber hält einen Share-Lock auf die Zustandszeile bis Transaktionsende | wiederverwendet für den **Backup-Hold** (siehe Konsistenz) |
| `ObjectStore.delete()` | löscht **physisch vor** dem Commit der Transaktion | Grund, warum "erst Dump, dann Objekte kopieren" nicht konsistent ist → Copy-on-Write |
| Generationen (`g<n>/`) | Cutover schreibt in neue Generation, alte bleibt `retained` | eine abgelöste Generation ist eingefroren; das Backup kann sie zu Ende lesen |
| Garage (lokales S3) | keine Objektversionierung | Unveränderlichkeit über eigenen Copy-on-Write-Hold, unabhängig vom Anbieter |
| `storage_worker.py` | Lease + Fencing-Token, Heartbeat-Thread, Backoff | Muster für den Backup-Worker übernommen |
| `tenant_export_service` / `tenant_import_service` | Export als ZIP, Import aus ZIP (Grenze 2 GiB entpackt) | Export-Logik gegen eine **historische** Datenbank, Import über eine neue Dateiquelle ohne ZIP |
| `system_health_service` / `system_alert_service` | Checks → Probleme → entprellte ntfy-Meldungen | drei neue Checks `backup`, `backup_repository`, `backup_verification` |
| Plattform-Admin | `require_admin_write` (owner), Audit-Log, TOTP-Faktoren | Owner-only für Aktionen, frische TOTP-Bestätigung für Restores |

## Zielbild

```text
Admin-Portal (/admin/backups)
   │  JSON-API, Owner-Rechte, Audit, Idempotenz
   ▼
FastAPI  ── schreibt nur Aufträge/Einstellungen ──►  backup_job / backup_restore_job
                                                         │  Lease + Fencing + Heartbeat
                                                         ▼
                                              backup-worker (eigener Container)
                                   ┌─────────────┬───────┴────────┬──────────────┐
                                   ▼             ▼                ▼              ▼
                              pg_dump -Fc   ObjectStore      Manifest       borg (SSH)
                              (Snapshot)   (aktive Gen.)   (jsonl.gz)          │
                                                                               ▼
                                                              Hetzner Storage Box (Borg-Repo,
                                                              repokey-blake2, append-only)

Recovery-CLI (python -m app.backup.cli) ── braucht weder Backend, Redis noch hocX-DB
```

Das Backend bekommt weder Borg-Schlüssel noch SSH-Zugang, keinen Docker-Socket und startet keine
Prozesse. Nur der `backup-worker` hält die Borg-Secrets.

## Repository-Layout im Borg-Repository

Borg ist dateisystemorientiert und dedupliziert auf Chunk-Ebene – aber nur für Daten, die man
ihm erneut zeigt. Um unveränderte Objekte **nicht** erneut aus S3 laden zu müssen, ist das
Repository inhaltsadressiert organisiert:

| Archiv | Inhalt | entsteht |
|---|---|---|
| `hocx-pool-<backup-id>-<n>` | Objektinhalte, Pfad `pool/<sha[0:2]>/<sha256>` – jeder Inhalt genau einmal im Repository | pro Backup-Lauf nur für **neue** Inhalte, in Batches |
| `hocx-rp-<UTC-Zeit>-<backup-id>` | **Wiederherstellungspunkt**: `hocx-backup.json` (Metadaten), `manifest.jsonl.gz` (vollständige Objektliste), `db/hocx.pgdump` (Custom-Format), `db/globals.sql` (Rollen ohne Passwörter), `recovery/README.txt` | genau einmal pro erfolgreichem Lauf, **zuletzt** |

Ein Wiederherstellungspunkt ist vollständig, sobald sein `rp`-Archiv existiert: das Manifest
nennt für jedes Objekt `namespace`, `key`, Grösse, SHA-256, Registerversion und das
Pool-Archiv, in dem der Inhalt liegt. Weil die Pool-Archive nach Inhalt adressiert sind,
bleibt ein Wiederherstellungspunkt unabhängig vom S3-Anbieter, der Generation und dem
Objektpfad im Bucket.

Das `hocx-backup.json` jedes Punktes enthält Backup-ID, Zeitpunkt, hocX-Version,
Alembic-Revision, PostgreSQL-Version, Storage-Generation, Profil (nur Name/Anbieter, keine
Zugangsdaten), Journal-Position, Zähler, SHA-256 von Dump und Manifest und die Mandantenliste.
**Die Backup-Historie lässt sich vollständig aus dem Repository rekonstruieren**
(`borg list` + Metadaten); die Tabellen in der hocX-Datenbank sind nur ein Index.

## Inkrementelle Objektsicherung ohne lokalen Spiegel

1. Inventar des Sicherungspunkts (aus dem Snapshot, siehe unten): alle aktiven Objekte.
2. Abgleich mit dem Index `backup_content` (SHA-256 → Pool-Archiv). Bekannte Inhalte werden
   **nicht** geladen – nur im Manifest referenziert.
3. Neue Inhalte werden in Batches (Default 2 GiB / 5000 Objekte) direkt aus dem ObjectStore
   gelesen, beim Lesen gegen den Register-SHA-256 geprüft und als **Tar-Stream über eine Pipe**
   in `borg import-tar` geschrieben. Es entsteht keine lokale Kopie – auch nicht für Objekte, die
   grösser als das Staging-Budget sind. Lokal liegt nur der Pipe-Puffer.
4. Stimmt der SHA-256 eines Objekts nach dem Lesen nicht, wird `borg import-tar` per SIGTERM
   abgebrochen (Borg schreibt dann **kein** Archiv – experimentell verifiziert), der Inhalt aus
   dem Backup-Hold gesucht und der Batch ohne das defekte Objekt wiederholt.
5. Erst wenn alle Inhalte in Pool-Archiven liegen, werden die Pool-Archive gegen den Index
   geprüft (`borg list --json-lines`, Pfad + Grösse) und der Wiederherstellungspunkt geschrieben.

Lokaler Speicher wird nur für den PostgreSQL-Dump und das Manifest gebraucht (Staging-Budget
`BACKUP_STAGING_MAX_BYTES`, vorher geprüft) sowie für den Borg-Cache (wächst mit der Zahl der
Chunks, nicht mit der Datenmenge im Verhältnis 1:1; Richtwert < 1 % der Repository-Grösse).

## Konsistenz zwischen PostgreSQL und Objektspeicher

Problem: `ObjectStore.delete()` löscht physisch, bevor die Transaktion committet; Vorlagen-Bauteile
können denselben Key überschreiben. Ein Dump plus späteres Kopieren der aktuellen Objekte kann
daher Inhalte verlieren, auf die der Dump verweist.

Lösung **Backup-Hold mit Copy-on-Write** (anbieterunabhängig, braucht keine S3-Versionierung):

1. Der Worker setzt `storage_state.backup_hold_id/backup_hold_generation` per `UPDATE` (mit
   `lock_timeout`). Das `UPDATE` wartet – wie das Cutover-Fence – auf alle offenen
   Schreibtransaktionen (`storage_begin_write()` hält `FOR SHARE`); neue Schreiber sehen den
   Hold. Schreibzugriffe werden dabei höchstens für die Dauer des `lock_timeout` aufgehalten,
   **ohne** Wartungsmodus.
2. Ab jetzt sichert jeder Schreiber vor `delete`/Überschreiben eines im Register aktiven Objekts
   der gehaltenen Generation den bisherigen Inhalt per serverseitigem Copy nach
   `_hocx-backup-hold/<hold-id>/<sha256>` (SQL-Funktion `storage_backup_hold()`, Client
   `objstore_client.py`, gilt für Backend **und** Abgabebox).
3. In einer `REPEATABLE READ`-Transaktion exportiert der Worker einen Snapshot
   (`pg_export_snapshot()`), startet `pg_dump --snapshot=…` und liest im **selben** Snapshot
   das Objektinventar, die Journal-Position, die Mandantenliste und prüft, dass der Hold noch
   seiner ist und die Generation stimmt.
4. Die lange Übertragung läuft danach ohne jede Sperre. Ein Objekt aus dem Inventar ist entweder
   unverändert am Originalort oder sein Inhalt liegt (nach SHA-256 benannt) im Hold.
5. Nach dem Schreiben des Wiederherstellungspunkts wird der Hold gelöst und der Hold-Bereich
   gelöscht. Ein abgebrochener Lauf hinterlässt einen Hold; der nächste Lauf übernimmt bzw. räumt
   ihn kontrolliert ab (Lease abgelaufen → Hold freigeben → Bereich löschen).

**Storage-Cutover während eines Backups:** Ein Cutover wird während der kurzen Erfassungsphase
(Schritte 1–3) durch die Prüfung in Schritt 3 erkannt (Lauf beginnt neu). Danach darf er
stattfinden: die gehaltene Generation wird nach dem Cutover nicht mehr beschrieben (eingefroren),
der Worker liest sie zu Ende. Das Bereinigen einer Generation (`purge_generations`) überspringt
Generationen mit aktivem Hold. Folgebackups arbeiten automatisch mit der neuen Generation.

Die Erstmigration vom Dateisystem (Generation 0) füllt das Register erst vollständig. Solange
Generation 0 aktiv ist und keine abgeschlossene Erstmigration existiert, verweigert der Worker
das Backup (`storage_registry_incomplete`), ausser `BACKUP_TRUST_FILESYSTEM_REGISTRY=true` ist
gesetzt (Neuinstallation, bei der jede Datei über das Register geschrieben wurde).

## Retention und Garbage Collection

* Behalten: alle Punkte der letzten 14 Tage (6-stündlich), zusätzlich je Tag/Woche/Monat der
  jüngste Punkt für 14 Tage / 8 Wochen / 12 Monate (Borg-`prune`-Semantik: Perioden zählen nur,
  wenn sie einen Punkt enthalten). Regeln werden **vereinigt**: ein Punkt bleibt, sobald
  irgendeine Regel ihn hält. Geschützte Punkte (Rettungspunkt vor Restore, vor Deploy) und der
  jüngste erfolgreiche Punkt werden nie entfernt.
* Ablauf: (1) behaltene Punkte bestimmen, (2) deren Manifeste aus dem Repository lesen,
  (3) Menge aller referenzierten Inhalte bilden und gegen den Index prüfen, (4) erst dann nicht
  mehr behaltene `rp`-Archive löschen, (5) Pool-Archive ohne referenzierten Inhalt löschen,
  teilweise referenzierte Pool-Archive mit `borg recreate --exclude` verkleinern (nur
  Metadaten, keine Datenübertragung). Jeder Fehler bricht ab, bevor gelöscht wird.
* Index-Einträge werden vor dem Entfernen auf `gc_pending` gesetzt; ein abgebrochener Lauf
  wird beim nächsten Mal aus dem Repository-Zustand neu abgeglichen.
* Mit append-only-Zugang geben Löschungen keinen Platz frei (siehe [Sicherheit](sicherheit.md));
  `borg compact` läuft nur mit dem getrennten Wartungszugang.

## Restore-Wege

| Weg | Ziel | Kern |
|---|---|---|
| Voll-Restore (Admin) | aktuelle Installation | Rettungspunkt → neue DB `hocx_restore_<id>` → neue Storage-Generation im gewählten Profil → Referenzprüfung → Alembic falls nötig → kontrollierter Cutover (Wartung, DB-Rename) → Smoke-Test. Die alte DB bleibt als `hocx_pre_restore_<ts>`, die alte Generation unberührt (Rollback). |
| Recovery-CLI | neuer Server, keine hocX-DB | Archive direkt aus dem Repository, Dump in leere Ziel-DB, Objekte in ein per CLI angegebenes Profil (S3 oder Dateisystem), Register/Profil/Generation in der wiederhergestellten DB neu setzen, Referenzprüfung |
| Mandant als Kopie | aktuelle Installation, **neuer** Mandant | Dump in isolierte Temp-DB, Alembic auf aktuellen Stand, Export-Logik gegen diese DB, Objekte direkt aus Borg in den aktiven Speicher, Import über `RecoveryFileSource` (ohne ZIP-Grenze, aber mit eigener Mengen-/Pfadprüfung) |

Ein Restore aktiviert nie blind ein altes Storage-Profil: Objekte werden immer aus Borg in eine
**neue** Generation des gewählten Ziels geschrieben; der alte Anbieter muss nicht erreichbar sein.

## Risiken und offene Einschränkungen

* Restore-Tests und Integrationstests laufen gegen ein lokales Borg-Repository über SSH
  (`borg serve` in einem Testcontainer). Hetzner-spezifische Abnahmen (Borg-Version
  `borg-1.4` auf der Box, append-only per `authorized_keys`, Kapazitätsabfrage) sind in
  [Betrieb](betrieb.md#abnahme-auf-der-hetzner-storage-box) als manuelle Schritte aufgeführt.
* Ein kompromittierter Produktivserver mit dem append-only-Schlüssel kann keine Archive
  endgültig löschen, aber neue (falsche) Archive anlegen und das Repository mit Daten füllen.
  Endgültig gelöscht wird erst beim `compact` mit dem Wartungsschlüssel – der gehört nicht
  auf den Produktivserver.
* Ein Voll-Restore ersetzt die Datenbank per Umbenennen; alle Dienste verlieren dabei ihre
  DB-Verbindungen kurz (Wartungsfenster). Sitzungen in Redis werden verworfen.
* Wiederherstellung eines Mandanten setzt dasselbe `ADMIN_AUTH_SECRET` voraus (TOTP-Secrets sind
  damit verschlüsselt) – bei einem Backup einer anderen Installation werden MFA-Faktoren
  verworfen und gemeldet.
