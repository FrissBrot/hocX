# RUNBOOK: Release, Test, Prod

Drei Umgebungen:

| | Dev | Test | Prod |
|---|---|---|---|
| Wo | dieser Server | eigener Test-Server | eigener Prod-Server |
| Domain | hocx.example.com | test.hocx.ch | hocx.ch |
| Woher kommt der Code | lokal, `build:` aus Source | Docker-Image von GHCR | Docker-Image von GHCR |
| Verzeichnis | `/docker/hocX` | Repo-Checkout auf dem Test-Server | Repo-Checkout auf dem Prod-Server |

**Lokale Entwicklung** (Laptop/Workspace, nicht `hocx.example.com`) läuft jetzt bewusst separat
über den Overlay `docker-compose.dev.yml`:

```bash
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Optional dazu: `--profile scan` (ClamAV), `--profile docs` (Docs auf localhost:3002),
`--profile edge` (lokaler Traefik).

Bequemer Wrapper dafuer:

```bash
./scripts/dev.sh
./scripts/dev.sh stop
./scripts/dev.sh down
./scripts/dev.sh up --profile docs --profile scan
```

**Wichtig vor dem allerersten Start einer neuen Domain (Test wie Prod)**: DNS-Eintrag
zuerst setzen, dann erst den Stack starten. Traefik versucht bei jedem Container-Start
sofort ein Let's-Encrypt-Zertifikat zu beziehen; schlägt die HTTP-01-Challenge fehl
(weil DNS noch nicht auf den Server zeigt), zählt das als "failed authorization" gegen
Let's Encrypt's Rate-Limit (5 Fehlversuche/Domain/Stunde). Mehrfaches Neustarten des
Stacks vor gesetztem DNS kann dieses Limit auslösen - dann muss man bis zu 1h warten,
bevor ein neuer Zertifikatsversuch klappt. Betrifft nur die neue Domain, nicht die
bereits laufenden Zertifikate der anderen Umgebungen.

## 1. Candidate-Images manuell bauen

1. Alle Änderungen sind auf `main` gemerged und die PR-CI ist gruen.
2. In GitHub → Actions den Workflow `Build test candidate images` starten.
3. In der Actions-UI den gewuenschten Ref auswaehlen (normalerweise `main`). Der
   Workflow baut automatisch den neuesten Commit dieses Refs.
4. Der Candidate-Tag wird dabei automatisch erzeugt, Format:
   `test-<UTC-Datum>-<shortsha>-r<run_number>`, z.B. `test-20260825-abc1234-r42`.
5. Der Workflow baut+pusht alle Release-Images nach
   `ghcr.io/<namespace>/hocx-{backend,frontend,abgabebox-backend,abgabebox-frontend,docs}:<image_tag>`.
6. Diesen Candidate-Tag aus der Workflow-Summary notieren; genau derselbe Tag wird auf
   dem Test-Host deployed.

## 2. Testumgebung aktualisieren

Einmalig nach der Umstellung auf den sicheren Env-Loader sicherstellen, dass nur der
Eigentuemer die vorhandene Secret-Datei lesen kann: `chmod 600 .env`. Symlinks und
gruppen- oder weltlesbare `.env`-Dateien werden vom Deploy bewusst abgelehnt.

```bash
# Auf dem Test-Host im Repo-Root .env pflegen. Fehlt sie beim ersten Deploy,
# fragt deploy.sh die externen Werte ab und erzeugt alle Secrets automatisch.
vim .env

# HOCX_VERSION auf den eben gebauten Candidate-Tag setzen, z.B.:
# HOCX_VERSION=test-20260825-abc1234-r42

./scripts/deploy.sh test
./scripts/verify_release.sh test
```

`deploy.sh test` macht automatisch: Preflight + exklusiver Deploy-Lock → DB-Backup
(`backups/`) → Images pullen → Cosign-Signaturen pruefen → Digest-Manifest schreiben →
Alembic explizit ausfuehren → Container neu starten → Smoke-Checks
(Backend, Frontend, Abgabebox, Docs, ClamAV).
`verify_release.sh test` prueft danach zusaetzlich:
- Backend / Abgabebox-Backend lokal erreichbar
- Frontend / Website / Docs lokal erreichbar
- Alembic `current == heads`
- `https://test...`-Domains antworten ueber Traefik

**Verifizieren** (mit einem Wegwerf-Testaccount, danach wieder löschen):
- https://test.hocx.ch/login erreichbar, Branding lädt korrekt
- Login funktioniert, mindestens eine Tabellen-Seite lädt Daten
- Abgabebox: https://abgabe-test.hocx.ch lädt (sofern ein Test-Mandant mit
  Abgabebox-Konfiguration existiert)
- `docker compose -p hocx-test logs backend --tail=50` zeigt keine Fehler, insbesondere
  keine Alembic-Fehler beim Start

## 3. Getesteten Candidate zum Release promoten

Wenn Test erfolgreich war:

1. In GitHub → Actions den Workflow `Promote tested release images` starten.
2. Eingaben:
   - `source_tag`: genau der getestete Candidate-Tag, z.B. `test-20260825-abc1234-r42`
   - `release_tag`: finaler Semver-Tag, z.B. `v1.2.0`
   - `update_latest`: in der Regel `true`
   - `confirm_production`: zur Fehlklick-Sicherung exakt `DEPLOY`
3. Der Workflow verlangt einen erfolgreichen, von `verify_release.sh test` erzeugten
   GitHub-Testnachweis fuer genau den `source_tag`. Danach laeuft er in der GitHub-
   Umgebung `production`. Fuer deinen Solo-Workflow muss dort kein Required Reviewer
   konfiguriert werden.
4. Der Workflow baut **nicht** neu, sondern setzt die finalen GHCR-Tags auf dieselben
   bereits getesteten Images.
5. Optional danach ein GitHub-Release fuer Release Notes / Changelog anlegen. Das ist
   rein dokumentarisch; Images sind zu diesem Zeitpunkt schon gepromoted.

Die GitHub-Umgebung wird beim ersten Workflow-Lauf automatisch angelegt. In
**Settings → Environments → production** keine Reviewer-Regel aktivieren, solange du
allein arbeitest. Die technische Test-Gate- und `DEPLOY`-Pruefung bleiben aktiv.

## 4. Prod aktualisieren

Erst wenn Test erfolgreich verifiziert **und** der Promotion-Workflow erfolgreich war.
Auf dem Prod-Server:

```bash
vim .env   # HOCX_VERSION auf die neue Version setzen
./scripts/deploy.sh prod
./scripts/verify_release.sh prod
```

Auf Prod immer den finalen Release-Tag pinnen, nie einen Candidate-Tag.

## 5. Rollback

Schlagen Containerstart oder Smoke-Checks fehl, startet `deploy.sh` automatisch das
letzte erfolgreiche Image-Set aus `.releases/current.env`. Das Manifest enthaelt
unveraenderliche Image-Digests, nicht nur Tags. Eine bereits erfolgreiche
Datenbankmigration wird dabei bewusst nicht automatisch zurueckgerollt.

Falls ein Problem erst spaeter auffaellt:

```bash
vim .env   # HOCX_VERSION auf die vorherige, bekannt gute Version zuruecksetzen
./scripts/deploy.sh prod
./scripts/verify_release.sh prod
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

## 6. Testumgebung neu aufsetzen (falls die Test-DB mal komplett zurückgesetzt werden soll)

```bash
docker compose -p hocx-test -f docker-compose.release.yml -f docker-compose.clamav.yml \
  -f docker-compose.traefik.yml -f docker-compose.test.yml --env-file .env \
  --project-directory "$(pwd)" down -v
./scripts/deploy.sh test
./scripts/verify_release.sh test
```

`-v` löscht auch das Postgres-Volume - Test startet dann wieder mit leerer DB und
durchläuft beim nächsten Start die komplette Alembic-Historie von Anfang an.

## 7. Test-Host das erste Mal aufsetzen

1. Test-Server provisionieren, Docker + Docker Compose installieren.
2. DNS: `test.hocx.ch`, `abgabe-test.hocx.ch`, optional `docs-test.hocx.ch` und
   `web-test.hocx.ch` auf die Test-Server-IP zeigen lassen.
3. Repo als root klonen: `git clone git@github.com:FrissBrot/hocX.git`.
4. Im Repo als root `./scripts/provision_deploy_user.sh test` ausfuehren. Das Skript erstellt
   `hocx-deploy`, installiert bei Debian/Ubuntu fehlende Werkzeuge (`gh`, `jq`, `curl`),
   richtet Docker-Zugriff und alle Besitz-/Runtime-Rechte ein und zeigt
   danach den erforderlichen Benutzerwechsel an. `/etc/hocx/environment` bindet den Host
   dauerhaft an `test`; Prod- und Dev-Starts werden auf diesem Host abgelehnt.
5. Mit `sudo -iu hocx-deploy` wechseln, ins Repository gehen und
   `./scripts/deploy.sh test` starten. Falls `.env` fehlt, fragt das Skript die nicht
   automatisch erzeugbaren Werte interaktiv ab, legt die Datei mit zufaelligen Secrets
   und Dateirechten 600 an und startet danach direkt die Umgebung.
6. Bei spaeteren Deploys in `.env` `HOCX_VERSION` auf den neuen Candidate-Tag setzen.
7. Nach dem ersten Deploy und nach Updates `./scripts/verify_release.sh test` ausfuehren.
   Bei erfolgreichen Checks schreibt das Skript automatisch einen maschinenlesbaren
   GitHub-Deployment-Status fuer exakt diesen Candidate-Tag. Dieser Nachweis ist die
   technische Voraussetzung fuer eine spaetere Prod-Promotion.
8. Test-Admin-Login mit `INITIAL_ADMIN_EMAIL`/`INITIAL_ADMIN_PASSWORD` pruefen, danach
   weitere Test-Admins anlegen und das Bootstrap-Passwort aendern.

Beim ersten Deploy fragt `deploy.sh` zwei getrennte Tokens verdeckt ab. Empfohlen sind:

- ein Fine-grained PAT, ausschliesslich fuer `FrissBrot/hocX`, mit `Contents: read`,
  `Actions: read` und `Deployments: read and write`;
- ein klassischer PAT mit ausschliesslich `read:packages` fuer GHCR.

Die Trennung verhindert, dass der Registry-Token auch Repository-Rechte erhaelt. Beide
werden mit Modus 600 unter `.tools/` statt in `.env` gespeichert. Das Skript prueft
Repository-, Actions-, Deployment- und GHCR-Anmeldung bei jedem Deploy erneut.

Der Status kann bei Bedarf manuell kontrolliert werden:

```bash
sudo -iu hocx-deploy
gh auth status
```

Der Token wird von `gh` im geschuetzten Benutzer-Credential-Speicher verwaltet und
gehoert nicht in `.env`. Die Deployment-Schreibberechtigung kann ohne einen kuenstlichen
Testeintrag nicht vorab geprueft werden; sie wird spaetestens beim ersten erfolgreichen
`verify_release.sh test` real validiert. Scheitert dieser Eintrag, bleibt die
Prod-Promotion gesperrt.

## 8. Prod-Server das erste Mal aufsetzen (sobald der Server existiert)

1. Server provisionieren, Docker + Docker Compose installieren.
2. DNS: `hocx.ch` und `abgabe.hocx.ch` (oder analog) auf die Server-IP zeigen lassen.
3. Repo als root klonen (nur für die Compose-Dateien und `infra/traefik/` nötig, kein
   Source-Build): `git clone git@github.com:FrissBrot/hocX.git`.
4. Im Repo als root `./scripts/provision_deploy_user.sh prod` ausfuehren. Danach mit
   `sudo -iu hocx-deploy` zum dedizierten Deploy-Benutzer wechseln. Direkte
   `deploy.sh`-Aufrufe als root werden bewusst abgelehnt. Die Root-eigene Markierung
   `/etc/hocx/environment` blockiert auf diesem Host Test- und Dev-Starts.
5. Im Repo `./scripts/deploy.sh prod` starten. Falls `.env` fehlt, fragt das Skript Domains,
   Image-Version und externe Zugangsdaten interaktiv ab. Ableitbare Werte und sichere
   Zufalls-Secrets erzeugt es selbst; die neue `.env` erhaelt Dateirechte 600.
6. Das Skript zieht die in `.env` gepinnte Version und startet den
   kompletten Stack inkl. eigenem Traefik (Let's-Encrypt-Zertifikate werden beim ersten
   Start automatisch bezogen, dauert ein paar Minuten).
   Vor dem Start verifiziert es jedes Image gegen die Signatur des
   `build-test-images.yml`-Workflows. Eine fest gepinnte Cosign-Version wird bei Bedarf
   nach `.tools/` geladen und gegen die im Skript hinterlegte SHA-256-Pruefsumme geprueft;
   eine systemweite Installation ist nicht erforderlich.
7. Bootstrap-Admin-Login mit `INITIAL_ADMIN_EMAIL`/`INITIAL_ADMIN_PASSWORD` aus `.env`
   prüfen, danach im Admin-Panel weitere Admins anlegen und das Bootstrap-Passwort
   ändern.

## 9. Deploy-Code kontrolliert aktualisieren

Ein normaler `deploy.sh`-Lauf aktualisiert Skripte und Compose-Dateien niemals selbst.
Als `hocx-deploy` wird ein Update bewusst separat ausgefuehrt:

```bash
cd /docker/hocX
./scripts/update_deploy_code.sh
./scripts/deploy.sh prod  # auf dem Testhost entsprechend: test
```

Optional kann das erfolgreiche Fast-Forward-Update direkt den an den Host gebundenen
Deploy starten:

```bash
./scripts/update_deploy_code.sh --deploy
```

Der Updater akzeptiert nur die fest hinterlegte hocX-GitHub-Remote, den Branch `main`,
einen sauberen tracked Worktree und einen reinen Fast-Forward auf `origin/main`. Vor dem
Fast-Forward lädt er den zum Commit gehoerenden CI-Nachweis, prueft dessen keyless
Cosign-Signatur gegen den festen `build-test-images.yml`-Workflow und verifiziert die
Hashes aller Deploy-Skripte, Compose- und Traefik-Dateien. Damit reicht ein blosses
Manipulieren von Git oder `origin/main` nicht mehr aus. Hierfuer wird dieselbe einmalige
GitHub-Anmeldung wie fuer den Testnachweis benoetigt; fehlt sie, wird der Token auch hier
verdeckt abgefragt und geprueft. Der Updater nutzt denselben
exklusiven Lock wie `deploy.sh`. `.env`, Storage, Backups, `.tools` und `.releases` sind
ignoriert und werden nicht veraendert.

## 10. Backup- und Cleanup-Cronjobs

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
- **⚠️ Offenes Risiko: kein Offsite-Backup aktiv (Audit I5, 2026-08-16).** `backups/`
  liegt auf derselben Partition wie das Docker-Volume der Live-DB (`postgres_data`) -
  bei Festplatten- oder Hostausfall sind Live-Daten und alle lokalen Backups gleichzeitig
  weg. Das Skript unterstützt seit diesem Fund einen optionalen rclone-Sync (siehe
  Kommentar am Ende von `backup_db.sh`): `OFFSITE_BACKUP_REMOTE` in `.env` setzen (z.B.
  `s3:mein-bucket/hocx-backups`) und `rclone` installieren + konfigurieren
  (`rclone config`, siehe [rclone.org/docs](https://rclone.org/docs/#configure)) - ohne
  das bleibt der Sync ein No-op und dieses Risiko besteht weiter. **Noch nicht
  eingerichtet** - eine bewusste Entscheidung dazu (welcher Anbieter, wer die Kosten
  trägt) steht noch aus.

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
  Dateien, löscht nichts), danach bei Bedarf ohne Flag fuer den echten Lauf.

## 11. hocx.example.com ist faktisches Prod, nicht lokales Dev

Die Tabelle in Abschnitt "Drei Umgebungen" oben führt `hocx.example.com` als "Dev" -
das beschreibt korrekt, *wie* die Umgebung technisch betrieben wird (lokaler Build aus
Source, kein GHCR-Image, kein `HOCX_VERSION`-Pinning), sagt aber nichts darüber aus, *wer*
davon abhängt. In Wirklichkeit laufen dort echte Mandanten mit echten Daten - die Instanz
wird faktisch wie Prod genutzt, auch wenn sie technisch wie Dev aufgesetzt ist. Ein
Update dort ohne Vorsicht (kein vorheriges Backup, kein Health-Check danach) ist damit
ein echtes Ausfallrisiko für echte Nutzer, nicht nur für einen Wegwerf-Testaccount.

Das echte **lokale** Entwickeln ist davon inzwischen bewusst getrennt: dafür ist der
Overlay `docker-compose.dev.yml` gedacht (siehe Abschnitt oben), nicht die Server-Instanz
`hocx.example.com`.

**Deshalb gilt für jedes Update von hocx.example.com** (der lokale Source-Build-Mechanismus
selbst bleibt unverändert - das ist eine bewusste, hier nicht revidierte Entscheidung,
keine Pipeline-Umstellung auf GHCR-Images ist im Rahmen dieses Punkts vorgesehen):

1. **Vor jedem Update**: Backup ziehen, unabhängig vom nächtlichen Cron-Lauf aus
   Abschnitt 10 - `./scripts/backup_db.sh` im Repo-Root ausführen und den Erfolg
   (neue Datei unter `backups/`) prüfen, bevor der Code aktualisiert wird.
2. **Update durchführen**: `git pull` + `docker compose up -d --build` (Alembic migriert
   die DB dabei automatisch, wie bei den anderen Umgebungen auch).
3. **Nach dem Update verifizieren** (analog zur Test-Verifikation in Abschnitt 2, mit
   einem Wegwerf-Testaccount, danach wieder löschen):
   - https://hocx.example.com/login erreichbar, Branding lädt korrekt
   - Login funktioniert, mindestens eine Tabellen-Seite lädt Daten
   - `docker compose logs backend --tail=50` zeigt keine Fehler, insbesondere keine
     Alembic-Fehler beim Start
4. **Bei Problemen**: Rollback wie in Abschnitt 4 beschrieben, mit dem in Schritt 1
   frisch gezogenen Backup statt eines älteren Cron-Backups.
