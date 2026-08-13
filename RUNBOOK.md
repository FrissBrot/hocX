# RUNBOOK: Release, Test, Prod

Drei Umgebungen:

| | Dev | Test | Prod |
|---|---|---|---|
| Wo | dieser Server | dieser Server (separates Compose-Projekt) | eigener Server |
| Domain | hocx.example.com | test.hocx.example.com | hocx.ch |
| Woher kommt der Code | lokal, `build:` aus Source | Docker-Image von GHCR | Docker-Image von GHCR |
| Verzeichnis | `/docker/hocX` | `/docker/hocX-test` (Daten) + `/docker/hocX` (Compose-Dateien) | Repo-Checkout auf dem Prod-Server |

**Wichtig vor dem allerersten Start einer neuen Domain (Test wie Prod)**: DNS-Eintrag
zuerst setzen, dann erst den Stack starten. Traefik versucht bei jedem Container-Start
sofort ein Let's-Encrypt-Zertifikat zu beziehen; schlägt die HTTP-01-Challenge fehl
(weil DNS noch nicht auf den Server zeigt), zählt das als "failed authorization" gegen
Let's Encrypt's Rate-Limit (5 Fehlversuche/Domain/Stunde). Mehrfaches Neustarten des
Stacks vor gesetztem DNS kann dieses Limit auslösen - dann muss man bis zu 1h warten,
bevor ein neuer Zertifikatsversuch klappt. Betrifft nur die neue Domain, nicht die
bereits laufenden Zertifikate der anderen Umgebungen.

## 1. Release erstellen

1. Alle Änderungen sind auf `main` gemerged.
2. Auf GitHub ein neues Release erstellen mit einem Semver-Tag (z.B. `v1.2.0`).
3. `.github/workflows/release.yml` läuft automatisch los und baut+pusht 4 Images nach
   `ghcr.io/<namespace>/hocx-{backend,frontend,abgabebox-backend,abgabebox-frontend}`,
   getaggt mit `v1.2.0` und `latest`.
4. Fortschritt in GitHub → Actions verfolgen. Bei Erfolg sind die Images unter
   GitHub → Packages sichtbar.

## 2. Testumgebung aktualisieren

```bash
# In /docker/hocX-test/.env die Zeile HOCX_VERSION=... auf die neue Version setzen
vim /docker/hocX-test/.env

cd /docker/hocX
./scripts/deploy.sh test
```

Das Skript macht automatisch: DB-Backup (`/docker/hocX-test/backups/`) → Images pullen →
Container neu starten (Alembic migriert die Test-DB dabei automatisch) → Health-Check.

**Verifizieren** (mit einem Wegwerf-Testaccount, danach wieder löschen):
- https://test.hocx.example.com/login erreichbar, Branding lädt korrekt
- Login funktioniert, mindestens eine Tabellen-Seite lädt Daten
- Abgabebox: https://test-abgabe.hocx.example.com lädt (sofern ein Test-Mandant mit
  Abgabebox-Konfiguration existiert)
- `docker compose -p hocx-test logs backend --tail=50` zeigt keine Fehler, insbesondere
  keine Alembic-Fehler beim Start

## 3. Prod aktualisieren

Erst wenn Test erfolgreich verifiziert ist. Auf dem Prod-Server:

```bash
vim .env   # HOCX_VERSION auf die neue Version setzen
./scripts/deploy.sh prod
```

## 4. Rollback

Falls nach einem Update etwas kaputt ist:

```bash
vim .env   # (bzw. /docker/hocX-test/.env fuer Test) HOCX_VERSION auf die vorherige, bekannt gute Version zurücksetzen
./scripts/deploy.sh prod
```

Das rollt den Code zurück. Falls die Migration der neuen Version das Schema
**destruktiv** verändert hat (Spalte gelöscht, Typ geändert), reicht ein Code-Rollback
nicht - dann muss zusätzlich das vor dem Update gezogene Backup eingespielt werden:

```bash
gunzip -c backups/<timestamp>-pre-vX.Y.Z.sql.gz | docker compose -p hocx exec -T db psql -U hocx hocx
```

**Deshalb**: bei riskanten Schema-Änderungen (Spalte umbenennen/löschen, Typ ändern)
über zwei Releases gehen statt in einem Schritt - z.B. neue Spalte hinzufügen und
befüllen in Release A, alte Spalte erst in Release B entfernen. Das hält jeden
einzelnen Schritt rückwärtskompatibel und Rollback ohne Backup-Restore möglich.

## 5. Testumgebung neu aufsetzen (falls die Test-DB mal komplett zurückgesetzt werden soll)

```bash
cd /docker/hocX
docker compose -p hocx-test -f docker-compose.release.yml -f docker-compose.test.yml \
  --env-file /docker/hocX-test/.env --project-directory /docker/hocX-test down -v
./scripts/deploy.sh test
```

`-v` löscht auch das Postgres-Volume - Test startet dann wieder mit leerer DB und
durchläuft beim nächsten Start die komplette Alembic-Historie von Anfang an.

## 6. Prod-Server das erste Mal aufsetzen (sobald der Server existiert)

1. Server provisionieren, Docker + Docker Compose installieren.
2. DNS: `hocx.ch` und `abgabe.hocx.ch` (oder analog) auf die Server-IP zeigen lassen.
3. Repo klonen (nur für die Compose-Dateien und `infra/traefik/` nötig, kein
   Source-Build): `git clone git@github.com:FrissBrot/hocX.git`.
4. `.env.prod.example` nach `.env` kopieren (im Repo-Root auf dem Prod-Server), alle
   `change-me`-Werte durch echte, zufällige Werte ersetzen (`openssl rand -hex 32` für
   Secrets).
5. `mkdir -p storage/abgabebox-uploads infra/traefik/letsencrypt infra/traefik/dynamic`
6. `./scripts/deploy.sh prod` - zieht die in `.env` gepinnte Version, startet den
   kompletten Stack inkl. eigenem Traefik (Let's-Encrypt-Zertifikate werden beim ersten
   Start automatisch bezogen, dauert ein paar Minuten).
7. Bootstrap-Admin-Login mit `INITIAL_ADMIN_EMAIL`/`INITIAL_ADMIN_PASSWORD` aus `.env`
   prüfen, danach im Admin-Panel weitere Admins anlegen und das Bootstrap-Passwort
   ändern.

## 7. Backup- und Cleanup-Cronjobs

Zwei eigenständige Skripte in `scripts/`, gedacht für periodische Ausführung per Cron
(zusätzlich zum automatischen Pre-Deploy-Backup, das `deploy.sh` bei jedem Update ohnehin
macht). Beide sind idempotent, loggen mit Zeitstempel nach stdout/stderr und brechen bei
Fehlern mit Exit-Code ≠ 0 ab (wichtig für Cron-Fehlerbenachrichtigung/Monitoring).

### `scripts/backup_db.sh`

- **Zweck**: nächtlicher Postgres-Dump, unabhängig vom Deploy-Zyklus. Nutzt denselben
  `pg_dump`-Mechanismus wie der Pre-Deploy-Backup in `deploy.sh` (`docker compose exec db
  pg_dump ... | gzip`) - ein Cron-Backup lässt sich also genauso zurückspielen wie ein
  Pre-Deploy-Backup (siehe Abschnitt 4, Rollback).
- **Braucht**: keine Argumente, läuft immer gegen den Checkout, in dem es liegt (`.env`
  im Repo-Root muss `POSTGRES_USER`/`POSTGRES_DB` enthalten; der `db`-Container muss
  laufen, sonst bricht das Skript kontrolliert ab).
- **Env-Var**: `RETENTION_DAYS` (Default 14) - Dumps, die älter sind, werden nach jedem
  Lauf automatisch gelöscht.
- **Schreibt nach**: `backups/<timestamp>-cron.sql.gz` (derselbe Ordner wie die
  Pre-Deploy-Backups, gut unterscheidbar am `-cron`-Suffix).
- **Empfohlener Cron-Zeitplan**: täglich 03:15 Uhr, mit Logdatei im selben `backups/`-Ordner:
  ```
  15 3 * * * /docker/hocX/scripts/backup_db.sh >> /docker/hocX/backups/backup_db.log 2>&1
  ```
- **Manuell testen**: `./scripts/backup_db.sh` direkt im Repo-Root ausführen und danach
  `ls -lh backups/` prüfen.

### `scripts/cleanup_storage.sh`

- **Zweck**: räumt ausschließlich `storage/exports/` (generierte PDF/LaTeX-Exportdateien)
  nach Alter auf. Bewusst **nicht** angefasst werden `storage/tenant_imports`,
  `storage/tenant_clones` und `storage/abgabebox-uploads` - das sind laut Code- und
  Live-DB-Prüfung permanente Speicherorte für echte Mandantendaten, keine Temp-Dateien
  (Details dazu direkt im Skript-Kommentar).
- **Braucht**: keine Pflicht-Argumente. Optionales `--dry-run` zeigt nur an, was gelöscht
  würde, ohne etwas zu löschen.
- **Env-Var**: `RETENTION_DAYS` (Default 30).
- **Schreibt/löscht**: Dateien älter als `RETENTION_DAYS` Tage unter `storage/exports/`
  (außer `.gitkeep`) sowie danach leer gewordene Unterverzeichnisse; Ausgabe geht nach
  stdout/stderr (kein eigenes Logfile im Skript, daher beim Cron-Eintrag umleiten).
- **Empfohlener Cron-Zeitplan**: täglich 03:45 Uhr, also nach `backup_db.sh`, damit ein
  Backup immer vor einer Cleanup-Runde derselben Nacht liegt:
  ```
  45 3 * * * /docker/hocX/scripts/cleanup_storage.sh >> /docker/hocX/backups/cleanup_storage.log 2>&1
  ```
- **Manuell testen**: erst `./scripts/cleanup_storage.sh --dry-run` (zeigt betroffene
  Dateien, löscht nichts), danach bei Bedarf ohne Flag für den echten Lauf.
