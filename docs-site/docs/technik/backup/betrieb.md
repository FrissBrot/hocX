# Backup: Einrichtung und Betrieb

Architektur und Entscheidungen: [Architektur](architektur.md). Restore: [Wiederherstellung](restore.md).
Schutzgarantien: [Sicherheit](sicherheit.md).

## Überblick

| Was | Wo |
|---|---|
| Dienst | `backup-worker` (gleiches Image wie das Backend, `python -m app.workers.backup_worker`) |
| Ziel | Borg-Repository auf der Hetzner Storage Box, SSH Port 23, `repokey-blake2` |
| Zeitplan | alle 6 Stunden (00:15, 06:15, 12:15, 18:15 UTC), einstellbar unter System → Backups → Einstellungen |
| Aufbewahrung | alle Punkte 14 Tage, dazu 14 täglich, 8 wöchentlich, 12 monatlich (Vereinigung) |
| Prüfungen | Integritätsprüfung wöchentlich, Restore-Test monatlich (automatisch eingeplant) |
| Lokale Daten | `backups/borg-work/` (Borg-Cache, Security-Verzeichnis, Staging für den DB-Dump, Restore-Journal) |
| Admin | `/admin/backups` (Status, Verlauf, manuelles Backup, Prüfung, Restore-Assistent, Einstellungen) |
| CLI | laufender Stack: `docker compose -p hocx exec backup-worker python -m app.backup.cli --help`; ohne laufendes Backend: `docker compose -p hocx run --rm --no-deps --entrypoint python backup-worker -m app.backup.cli --help` |

## Umgebungsvariablen

Alle in `.env` (Allowlist in `scripts/lib/env.sh`); `deploy.sh` übergibt sie nur an den
`backup-worker`. Secrets landen über `.secrets/` als Docker-Secrets im Worker – nie im Backend.

| Variable | Default | Bedeutung |
|---|---|---|
| `BACKUP_ENABLED` | `false` | Backups planen und ausführen; auch im Backend für Anzeige/Monitoring |
| `BACKUP_STORAGEBOX_HOST` | – | z. B. `u123456.your-storagebox.de` |
| `BACKUP_STORAGEBOX_USER` | – | z. B. `u123456` oder Sub-Account `u123456-sub1` |
| `BACKUP_STORAGEBOX_PORT` | `23` | SSH-Port der Storage Box für Borg |
| `BACKUP_REPOSITORY_PATH` | `hocx-borg` | relativ zum Home der Storage Box (`./hocx-borg`) |
| `BACKUP_REMOTE_PATH` | `borg-1.4` | Borg-Version auf der Storage Box |
| `BACKUP_REPOSITORY_ID` | – | Pinning: ID aus `cli init`/`cli info`; Abweichung = Abbruch |
| `BACKUP_SSH_HOST_FINGERPRINT` | – | `SHA256:…` des Host-Keys (alternativ `BACKUP_KNOWN_HOSTS_PATH`) |
| `BACKUP_KNOWN_HOSTS_PATH` | – | Host-Datei mit `[host]:23 ssh-ed25519 …` (Modus 600) |
| `BACKUP_SSH_KEY_PATH` | – | privater Schlüssel des **Backup**-Zugangs (Modus 600) |
| `BACKUP_PASSPHRASE` | – | Borg-Passphrase (lang, zufällig) |
| `BACKUP_STAGING_MAX_BYTES` | 20 GiB | Obergrenze lokaler Platz für den Datenbank-Dump |
| `BACKUP_BATCH_MAX_BYTES` | 2 GiB | Grösse eines Pool-Archivs (Übertragungseinheit) |
| `BACKUP_UPLOAD_RATELIMIT_KIB` | `0` | Upload-Begrenzung in KiB/s |
| `BACKUP_COMPRESSION` | `auto,zstd,3` | Borg-Kompression (`auto` überspringt unkomprimierbare Bilder) |
| `BACKUP_STORAGEBOX_QUOTA_BYTES` | `0` | Kapazität der Box für die Belegungswarnung (85 %/95 %) |
| `BACKUP_TRUST_FILESYSTEM_REGISTRY` | `false` | nur Neuinstallationen ohne Erstmigration, siehe Architektur |
| `HOCX_PRE_DEPLOY_BACKUP` | `required` | `skip` = Deploy ohne vorheriges Offsite-Backup (bewusste Entscheidung) |
| `HOCX_PRE_DEPLOY_BACKUP_TIMEOUT` | `7200` | Sekunden, die `deploy.sh` auf das Backup wartet (inkl. Warten auf ein gerade laufendes Backup) |
| `HOCX_PRE_DEPLOY_BACKUP_ALLOW_PARTIAL` | `true` | teilweise erfolgreiches Backup (DB vollständig, einzelne Objekte fehlen) akzeptieren; fehlende Objekte stehen im Deploy-Log. `false` = Deploy abbrechen |
| `HOCX_LEGACY_BACKUP_FORCE` | `false` | alte Skripte trotz Borg-Backup ausführen |

Feste Werte im Container: `BACKUP_WORK_DIR=/backup-work`, `BACKUP_SSH_KEY_FILE`,
`BACKUP_PASSPHRASE_FILE`, `BACKUP_KNOWN_HOSTS_FILE` (Docker-Secrets), Wartungsschlüssel
`BACKUP_MAINTENANCE_SSH_KEY_FILE` absichtlich **nicht** gesetzt.

## Einrichtung der Storage Box

### 1. Zwei SSH-Schlüssel erzeugen

Auf dem Produktivserver (Backup-Zugang) und auf einem Admin-Rechner **ausserhalb** des Servers
(Wartungszugang):

```bash
install -d -m 700 ~/.hocx-backup
ssh-keygen -t ed25519 -N "" -C "hocx-backup $(hostname)" -f ~/.hocx-backup/id_backup
# auf dem Admin-Rechner, nicht auf dem Server:
ssh-keygen -t ed25519 -C "hocx-borg-maintenance" -f ~/hocx-borg-maintenance
```

### 2. Host-Key der Storage Box pinnen

```bash
ssh-keyscan -p 23 u123456.your-storagebox.de | tee /tmp/sb-hostkeys | ssh-keygen -lf -
```

Den angezeigten `SHA256:`-Fingerprint mit dem von Hetzner veröffentlichten Wert vergleichen
(Hetzner Docs, Storage Box, «SSH host keys»). Nur bei Übereinstimmung:

```bash
grep ed25519 /tmp/sb-hostkeys > ~/.hocx-backup/known_hosts && chmod 600 ~/.hocx-backup/known_hosts
```

Der Worker akzeptiert **nie** unbekannte Host-Keys (`StrictHostKeyChecking=yes`, eigene
`known_hosts`). Alternativ nur `BACKUP_SSH_HOST_FINGERPRINT=SHA256:…` setzen: dann wird der Key
bei jedem Start geholt und nur bei exakt diesem Fingerprint verwendet.

### 3. Schlüssel auf der Storage Box hinterlegen, Backup-Schlüssel auf append-only beschränken

`.ssh/authorized_keys` der Storage Box (bzw. des Sub-Accounts):

```text
command="borg-1.4 serve --append-only --restrict-to-repository /home/hocx-borg",restrict ssh-ed25519 AAAA… hocx-backup
command="borg-1.4 serve --restrict-to-repository /home/hocx-borg",restrict ssh-ed25519 AAAA… hocx-borg-maintenance
```

Der Backup-Schlüssel kann damit nur anhängen: Löschungen, Retention und `recreate` werden
protokolliert, geben aber keinen Platz frei und lassen sich rückgängig machen; endgültig
entfernt wird erst beim `compact` mit dem Wartungsschlüssel. **Abnahme auf der Box**: siehe
unten – ob die Storage Box `command=`-Einschränkungen in `authorized_keys` erzwingt und unter
welchem Pfad das Home liegt, muss auf der konkreten Box geprüft werden.

Zusätzlich empfohlen: **automatische Snapshots der Storage Box** in der Hetzner-Konsole
aktivieren (z. B. täglich, 14 Tage). Snapshots sind über SSH nicht löschbar und schützen auch
dann, wenn ein Schlüssel kompromittiert ist.

### 4. `.env` und Repository anlegen

```bash
BACKUP_STORAGEBOX_HOST=u123456.your-storagebox.de
BACKUP_STORAGEBOX_USER=u123456
BACKUP_KNOWN_HOSTS_PATH=/home/hocx-deploy/.hocx-backup/known_hosts
BACKUP_SSH_KEY_PATH=/home/hocx-deploy/.hocx-backup/id_backup
BACKUP_PASSPHRASE=<openssl rand -base64 48>
BACKUP_STORAGEBOX_QUOTA_BYTES=1099511627776
BACKUP_ENABLED=false   # erst nach erfolgreichem Test auf true
```

`./scripts/deploy.sh prod` schreibt die Secrets und startet den Worker (im Leerlauf). Das
Repository wird **nur** ausdrücklich angelegt – nie durch `deploy.sh`:

```bash
docker compose -p hocx exec backup-worker \
  python -m app.backup.cli init --i-understand-this-creates-a-new-repository
```

Die ausgegebene Repository-ID als `BACKUP_REPOSITORY_ID` in `.env` eintragen. Hinweis: `init`
läuft mit dem append-only-Schlüssel; das ist zulässig.

### 5. Schlüssel und Passphrase sichern (Pflicht)

```bash
docker compose -p hocx exec backup-worker python -m app.backup.cli export-key --paper
```

Ausdruck plus Passphrase getrennt und offline aufbewahren (Tresor/Passwortmanager). Ohne
Passphrase **und** Schlüssel sind die Backups unbrauchbar – auch für Hetzner und für uns.
Zusätzlich gehören `STORAGE_CREDENTIALS_KEY`, `ADMIN_AUTH_SECRET` und die `.env` in dieselbe
Notfallmappe (für einen Restore auf einem neuen Server, siehe [Wiederherstellung](restore.md)).

### 6. Aktivieren und erstes Backup

`BACKUP_ENABLED=true` setzen, `./scripts/deploy.sh prod`. Der Worker legt sofort den Auftrag für
das aktuelle Zeitfenster an (Erstsicherung: alle Objekte, dauert je nach Datenmenge und
Upload-Rate Stunden). Danach unter System → Backups:

1. Erstes Backup «Erfolgreich», Wiederherstellungspunkt sichtbar.
2. «Restore-Test starten» – muss «Restore getestet» ergeben.
3. Integritätsprüfung (Verlauf → Aktionen → Prüfen) – muss «Geprüft» ergeben.
4. ntfy unter System → Benachrichtigungen eingerichtet (Probleme werden darüber gemeldet).

### 7. Umstellung vom bisherigen Backup

1. Bestehende Backups liegen in `backups/*.sql.gz` und `backups/storage/` – **nicht löschen**.
2. Neues Repository einrichten (oben), erstes Backup + Restore-Test erfolgreich.
3. Zeitplan aktiv (Standard). Ab `BACKUP_ENABLED=true` überspringen `backup_db.sh` und
   `backup_storage.sh` ihren Lauf (Meldung im Log), die Cron-Einträge `backup_db` und
   `backup_storage` aus der crontab des Deploy-Users entfernen (`crontab -e`).
4. Alte lokale Backups erst nach einer bewussten Entscheidung entfernen (z. B. nach 30 Tagen
   stabilem Betrieb); `backups/storage/` ist ein vollständiger Spiegel und kann sehr gross sein.

## Laufender Betrieb

- **Manuelles Backup**: System → Backups → «Backup jetzt starten» (Owner). Der Auftrag läuft im
  Hintergrund weiter, auch wenn das Browserfenster geschlossen wird.
- **Vor Deployments** legt `deploy.sh` ein geschütztes Backup an und wartet darauf
  (`HOCX_PRE_DEPLOY_BACKUP`). Schlägt es fehl, bricht das Update ab, bevor Migrationen laufen.
- **Monitoring**: `/admin/system` zeigt die Checks *Backup*, *Backup-Repository* und
  *Backup-Prüfungen*; `/admin/jobs` die Läufe `backup_run`, `backup_verify`,
  `backup_restore_test`, `backup_retention` und das Lebenszeichen `backup_worker`. ntfy meldet:
  fehlgeschlagenes oder teilweises Backup, Intervall überschritten, Storage Box nicht
  erreichbar, Prüfung/Restore-Test fehlgeschlagen oder überfällig, Speicher knapp, Repository-
  Fehler (falsche ID, Passphrase, Host-Key) und jeden Restore. Erfolgsmeldungen: keine, täglich
  zusammengefasst (Default) oder nach jedem Backup.
- **Zeitplan/Retention ändern**: System → Backups → Einstellungen (Owner, Audit-Log).

## Lokaler Speicherbedarf und Kapazitätsplanung

| Bereich | Bedarf |
|---|---|
| Objekte | **kein lokaler Spiegel** – Inhalte werden als Stream aus dem ObjectStore in Borg geschrieben |
| Datenbank-Dump | ≤ Grösse der Datenbank (Custom-Format, komprimiert), begrenzt durch `BACKUP_STAGING_MAX_BYTES`; wird vor dem Dump geprüft |
| Manifest/Inventar | ca. 60–120 Byte je Objekt (gzip), z. B. 1 Mio. Objekte ≈ 100 MB |
| Borg-Cache | wächst mit der Zahl der Chunks, Richtwert < 1 % der Repository-Grösse |
| Restore eines Mandanten | Temp-Datenbank auf dem PostgreSQL-Server + jeweils eine Datei für die Virenprüfung |

Gemessen im Lasttest (`tests/test_backup_resilience.py`): 2000 Objekte / 123 MiB → Staging-Spitze
0,8 MiB (davon 0,6 MiB Dump), Borg-Cache 0,2 MiB; Folgesicherung ohne neue Objekte: 0 Bytes
übertragen.

**Storage Box**: Erstsicherung ≈ Objektdaten (Bilder kaum komprimierbar) + Dump. Danach je
Backup nur neue Inhalte plus der Dump (dedupliziert, meist ein Bruchteil). Faustregel für die
Boxgrösse: 1,5 × aktuelle Objektdaten + 100 × Dumpgrösse × Änderungsrate, mindestens 2 ×
Objektdaten bei hoher Löschrate (gelöschte Inhalte bleiben bis zum Ablauf der Retention).
Bei append-only gibt die Retention erst nach `compact` (Wartungsschlüssel) Platz frei – dafür
quartalsweise einplanen:

```bash
# auf dem Admin-Rechner mit dem Wartungsschlüssel, nicht auf dem Server
docker compose -p hocx run --rm --no-deps --entrypoint python -v ~/hocx-borg-maintenance:/maint:ro backup-worker \
  -m app.backup.cli compact --maintenance-key /maint
```

Vorher mit `list` prüfen, dass keine unerwarteten Löschungen erfolgt sind.

## Abnahme auf der Hetzner Storage Box

Lokal getestet sind Borg 1.4 über SSH mit `borg serve --append-only`, Host-Key-Pinning,
Verbindungsabbrüche und beschädigte Repositories. **Auf der echten Box einmalig prüfen:**

1. `ssh -p 23 -i ~/.hocx-backup/id_backup u123456@u123456.your-storagebox.de` – mit
   `command=`-Einschränkung muss die Verbindung sofort mit einer Borg-Meldung enden (kein Shell).
2. `cli info` zeigt `repokey-blake2`, die gepinnte ID und `borg 1.4.x`; `BACKUP_REMOTE_PATH`
   passt zu einer auf der Box verfügbaren Version (`borg-1.4`, sonst `borg-1.2`).
3. Append-only wirksam: Testarchiv mit dem Backup-Schlüssel löschen, mit dem Wartungsschlüssel
   `list` – nach `borg delete` ist es weg, aber `compact` mit dem Backup-Schlüssel gibt keinen
   Platz frei (Box-Belegung in der Hetzner-Konsole unverändert).
4. Restore-Test im Admin-Portal erfolgreich.
5. Automatische Snapshots der Box aktiv.
