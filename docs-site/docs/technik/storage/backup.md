# Backup, Restore, Rollback und Recovery

!!! warning "Abgelöst durch das Borg-Backup"
    Sicherung und Wiederherstellung laufen über den `backup-worker` (BorgBackup, Hetzner Storage
    Box): siehe [Backup (BorgBackup)](../backup/index.md). Die unten beschriebenen Skripte
    `backup_db.sh`/`backup_storage.sh` laufen nur noch, solange `BACKUP_ENABLED` nicht gesetzt
    ist; der lokale Objekt-Spiegel und die Annahme "praktisch immer konsistent" sind durch den
    Backup-Hold (Copy-on-Write) ersetzt. Gültig bleiben die Abschnitte zu Migrationen und zur
    Bereinigung alter Generationen.

## Grundsatz

Datenbank und Objekte gehören zusammen: die Datenbank verweist per Key auf Objekte, das
Objektregister (`storage_object`) hält Grösse, SHA-256 und Version. Ein Backup gilt erst als
**verifiziert**, wenn seine Wiederherstellung tatsächlich getestet wurde.

## Sicherung

| Was | Werkzeug | Zeitplan |
|---|---|---|
| PostgreSQL | `scripts/backup_db.sh` (pg_dump, 14 Tage) | 03:15 |
| Objekte der aktiven Generation | `scripts/backup_storage.sh` → `python -m app.workers.storage_backup` (inkrementell, `manifest.json`, anschliessend `--verify`) | 03:30, **nach** dem DB-Backup |
| `.env` / `.secrets/` inkl. `STORAGE_CREDENTIALS_KEY` | Secret-Ablage des Betreibers | bei jeder Änderung |

Reihenfolge DB → Objekte: Keys werden nur einmal vergeben, Löschungen sind selten. Was der Dump
referenziert, ist beim anschliessenden Objekt-Backup daher praktisch immer noch vorhanden; die
seltene Ausnahme (dazwischen gelöscht) fällt bei der Prüfung nach dem Restore auf und ist
unkritisch (die Datei war ohnehin gelöscht).

Zusätzlich beim externen Anbieter:

- **Objektversionierung** aktivieren (Hetzner, AWS) – schützt vor Überschreiben/Löschen.
- **Object Lock / unveränderliche Backups**, wo verfügbar (AWS S3 Object Lock im
  Compliance-Modus; Hetzner unterstützt Object Lock ebenfalls) für das Backup-Ziel.
- Lebenszyklusregeln nur für alte Versionen, nie für aktuelle Objekte.

Das lokale Garage-S3 unterstützt keine Versionierung – sein Schutz ist das Objekt-Backup.

## Wiederherstellung

1. Volle Wartung starten (System → Wartung → «Jetzt starten»), damit nichts geschrieben wird.
2. Datenbank aus dem Dump zurückspielen (RUNBOOK, Abschnitt Rollback).
3. Objekte zurückspielen: Inhalt von `backups/storage/objects/<namespace>/<key>` in die aktive
   Generation kopieren – bei S3 z. B. mit `rclone copy` nach `<bucket>/<prefix>/g<generation>/<namespace>/`,
   beim Dateisystem direkt in die Stammverzeichnisse. Die Generation steht in `manifest.json`.
4. Prüfen: `docker compose exec backend python -m app.workers.storage_verify --full --json /tmp/verify.json`
   - `missing_references`: Datenbank zeigt auf fehlende Dateien,
   - `registry_missing` / `registry_mismatch`: Register und Speicher passen nicht zusammen,
   - `unregistered_objects`: Objekte ohne Registereintrag (z. B. DB älter als Objekte).
5. Erst bei Exit-Code 0 (oder bewusst bewerteten Abweichungen) Wartung beenden.

**Restore-Probe** (Pflicht für «verifiziert»): mindestens quartalsweise den Ablauf gegen den
E2E-Stack (`scripts/e2e.sh up`) mit einem aktuellen Backup durchspielen und das Ergebnis von
`storage_verify` dokumentieren.

## Rollback und Recovery bei Migrationen

| Situation | Zustand | Vorgehen |
|---|---|---|
| Fehler vor dem Cutover | Quelle aktiv, Fence gelöst | Ursache beheben, Migration läuft per Retry weiter oder abbrechen. Erstmigration: Wartung bleibt `failed`; nach Prüfung unter System → Wartung freigeben (Bedingung «Quelle nachweislich unverändert aktiv» wird angezeigt). |
| Cutover scheitert | zurück nach `ready_for_cutover`/`verifying`, Quelle aktiv | automatischer neuer Versuch mit Backoff |
| Backend startet direkt nach dem Cutover neu | aktiver Stand steht in `storage_state` | nichts zu tun – alle Prozesse lesen die neue Generation aus der DB |
| Prüfung nach dem Cutover scheitert | `rollback_required`, Ziel aktiv | kein automatischer Rückfall. Prüfbericht ansehen; «zur Kenntnis genommen» und eine **neue Migration** zurück zum vorherigen Profil starten (neue Generation; Änderungen seit dem Cutover werden mitgenommen). |
| Rückkehr innerhalb der Rückfallfrist | alte Generation `retained` | immer per neuer Migration – ein blindes Zurückschalten auf die alte Generation würde Änderungen seit dem Cutover verlieren und ist darum nicht vorgesehen |
| Worker-Absturz während Wartung | Wartung bleibt aktiv | Container startet neu (`restart: unless-stopped`) und übernimmt nach Ablauf der Lease |

## Bereinigung alter Daten

Abgelöste Generationen bleiben `STORAGE_FALLBACK_DAYS` (Default 14) unangetastet. Danach unter
System → Storage → Generationen «Bereinigen»: Eingabe `g<n>` zur Bestätigung, Owner-Recht,
Audit-Eintrag; der Worker löscht nur die Objekte dieser Generation (beim Dateisystem nur die von
einer abgeschlossenen Erstmigration nachweislich verifizierten Dateien). Die aktive Generation
und Generationen offener Migrationen sind gesperrt.
