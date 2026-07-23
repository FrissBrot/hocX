# RUNBOOK: Release, Test, Prod

Drei Umgebungen:

| | Dev | Test | Prod |
|---|---|---|---|
| Wo | dieser Server | dieser Server (separates Compose-Projekt) | eigener Server |
| Domain | hocx.tweber.ch | test.hocx.tweber.ch | hocx.ch |
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
- https://test.hocx.tweber.ch/login erreichbar, Branding lädt korrekt
- Login funktioniert, mindestens eine Tabellen-Seite lädt Daten
- Abgabebox: https://test-abgabe.hocx.tweber.ch lädt (sofern ein Test-Mandant mit
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
