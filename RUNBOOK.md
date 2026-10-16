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
docker compose -p hocx-dev -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Der Overlay setzt das Projekt fest auf `hocx-dev` (auch ohne `-p`). **Nie** auf einem Server mit
Echtdaten starten: er seedet Demo-Konten (`@hocx.local`/`ChangeMe123!`) und schaltet
Secure-Cookies ab.

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
(Backend, Frontend, Abgabebox, Docs, ClamAV) → Demo-Mandant neu befuellen
(`scripts/seed_test_tenant.py` loescht und baut den Mandanten "Jubla Sonnenberg" bei
jedem Test-Deploy komplett neu auf - Login siehe Skript-Output/-Docstring. Laeuft nur auf
`test`, nie auf `prod`).
`verify_release.sh test` prueft danach zusaetzlich:
- Backend / Abgabebox-Backend lokal erreichbar
- Frontend / Docs lokal erreichbar
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
5. Nach erfolgreicher Promotion aller sechs Images erstellt der Workflow automatisch
   den GitHub-Release mit Git-Tag auf dem getesteten Commit. Die Release Notes enthalten
   den passenden Versionsabschnitt aus `CHANGELOG.md` dieses Commits sowie die Image-Tags.
   Der Abschnitt (z.B. `## [1.2.0]`) muss bereits im Testkandidaten vorhanden und gefuellt
   sein; sonst stoppt der Workflow vor der Promotion. `Unveröffentlicht` wird nicht verwendet.
   Erlaubt sind stabile Versionen wie `v1.2.0` oder `1.2.0`; `update_latest` steuert auch
   die GitHub-Markierung als neuester Release. Bereits veroeffentlichte Releases werden
   bei Wiederholungen beibehalten; ein Tag auf einem anderen Commit fuehrt zum Abbruch.

Die Versionsnummer auf der Login-Seite oeffnet den passenden GitHub-Release samt
Changelog in einem neuen Tab. Entwicklungs-, Test- und moving tags oeffnen die
Release-Uebersicht. Fuer den direkten Versionslink `HOCX_VERSION` auf den exakten
Release-Tag setzen.

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

`deploy.sh` migriert eine bestehende `.env` bei jedem Lauf selbst auf das aktuelle Schema
(fehlende Variablen ergaenzen - Secrets werden neu erzeugt -, entfernte loeschen, Sicherung
als `.env.bak-<Zeitstempel>`, siehe `scripts/lib/env_migrate.sh`). Beim Update von 1.0.x auf
1.1.0 sind keine weiteren manuellen Schritte noetig; Details und der Umgang mit Konten in
mehreren Mandanten (`HOCX_SINGLE_TENANT_RESOLUTION=auto`) stehen im CHANGELOG unter
"Update von 1.0.x auf 1.1.0". Bricht die Migration `0078` ab, ist nichts veraendert: die
alte Version laeuft weiter, Ursache beheben und `deploy.sh` erneut starten.

### Vor dem Update auf 1.1.10: Vorab-Check Migration 0108

`0108_unified_participants` fuehrt Teilnehmer und Login-Konten zusammen und legt dabei eine
Check-Constraint (Login-Konto braucht E-Mail und Passwort) sowie einen Unique-Index auf die
kleingeschriebene Login-E-Mail an. Bestehende Daten, die das verletzen, lassen die Migration
abbrechen. Vor dem Deploy auf Prod (alter Stand laeuft noch) pruefen:

```bash
docker compose -p hocx exec -T db psql -U hocx hocx < scripts/precheck_0108.sql
```

Jede der drei Abfragen muss `(0 rows)` liefern:

| Check | Bedeutung | Bereinigen |
|---|---|---|
| `login_ohne_credentials` | Login-Konto ohne E-Mail oder Passwort | E-Mail/Passwort setzen oder Login deaktivieren |
| `email_kollision` | Login-E-Mails, die sich nur in Gross-/Kleinschreibung oder Leerzeichen unterscheiden | Ein Konto umbenennen oder zusammenfuehren |
| `teilnehmer_doppelt_verknuepft` | Mehrere Teilnehmer haengen am selben Konto | Teilnehmer zusammenfuehren, bis je Konto hoechstens einer verknuepft ist |

Am sichersten zusaetzlich: das letzte Backup in eine Wegwerf-DB einspielen und dort
`alembic upgrade head` laufen lassen. Bricht die Migration trotzdem ab, ist nichts
veraendert (eine Transaktion); die alte Version laeuft weiter.

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
nicht - dann muss zusätzlich das vor dem Update gezogene Backup eingespielt werden, und
zwar **vor** dem Deploy der alten Version:

```bash
./scripts/restore_db.sh backups/<timestamp>-pre-vX.Y.Z.sql.gz
vim .env   # HOCX_VERSION auf die vorherige Version (…-pre-vX.Y.Z = Stand vor dem Update auf vX.Y.Z)
./scripts/deploy.sh prod
./scripts/verify_release.sh prod
```

`restore_db.sh` fragt zur Bestätigung den Datenbanknamen ab, stoppt `backend`,
`abgabebox-backend` und `photo-analysis-worker`, sichert den aktuellen Stand als
`backups/<zeit>-pre-restore.sql.gz`, legt die Datenbank leer neu an und spielt den Dump mit
`ON_ERROR_STOP=1` in einer einzigen Transaktion ein. Schlägt das fehl, bleibt die Datenbank leer
und das Skript nennt den Befehl, mit dem sich die eben gezogene Sicherung zurückspielen lässt.
Die Dienste bleiben gestoppt, bis `deploy.sh` (bzw. auf der Quellcode-Instanz `docker compose up -d`)
die passende Code-Version startet.

**Nie** einen Dump direkt per `gunzip -c … | psql` in die laufende Datenbank pipen: Die Dumps
sind Plain-SQL ohne `--clean`; in einer bereits migrierten, gefüllten Datenbank scheitern
`CREATE`/`COPY` an vorhandenen Objekten, `psql` läuft ohne `ON_ERROR_STOP` weiter und meldet
Erfolg, obwohl ein Mischzustand entsteht.

Die Dateiablage (`storage/`) ist **nicht** Teil des Dumps (siehe Abschnitt 10; mit Borg-Backup
siehe unten). Ein Restore
setzt nur die Datenbank zurück; Dateien, die nach dem Dump hochgeladen wurden, bleiben als
verwaiste Dateien liegen, nach dem Dump gelöschte Dateien fehlen.

Mit aktivem Borg-Backup (Abschnitt 14) gibt es zusätzlich den geschützten Wiederherstellungspunkt
«Vor Update auf vX.Y.Z», der Datenbank **und** Dateien desselben Zeitpunkts enthält: System →
Backups → Wiederherstellung → «Vollständige Wiederherstellung» (zuerst die alte Version deployen,
damit das Schema passt).

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
2. DNS: `test.hocx.ch`, `abgabe-test.hocx.ch`, optional `docs-test.hocx.ch`
   auf die Test-Server-IP zeigen lassen.
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

Der Fine-grained-Token liegt mit Dateirechten 600 in `.tools/github-api-token` im
Repo-Checkout des Benutzers `hocx-deploy` (siehe `scripts/lib/github.sh`) und gehoert nicht in
`.env`. Die Deployment-Schreibberechtigung kann ohne einen kuenstlichen
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

> **Ab dem Borg-Backup (Abschnitt 14) abgelöst:** Sobald `BACKUP_ENABLED=true` gesetzt ist,
> überspringen `backup_db.sh` und `backup_storage.sh` ihren Lauf, und die Jobs `backup_db`/
> `backup_storage` verschwinden aus der Job-Übersicht. Ihre Cron-Einträge dann entfernen;
> `cleanup_storage.sh` bleibt. Die Beschreibung unten gilt für Installationen ohne Borg-Backup.

Zwei eigenständige Skripte in `scripts/`, gedacht für periodische Ausführung per Cron
(zusätzlich zum automatischen Pre-Deploy-Backup, das `deploy.sh` bei jedem Update ohnehin
macht). Beide sind idempotent, loggen mit Zeitstempel nach stdout/stderr und brechen bei
Fehlern mit Exit-Code ≠ 0 ab (wichtig für Cron-Fehlerbenachrichtigung/Monitoring).

Beide Cron-Einträge laufen über `scripts/run_job.sh <jobname> <befehl>`: der Wrapper meldet
Start, Dauer und Ergebnis (inkl. der letzten Ausgabezeilen bei einem Fehler) an die Job-Übersicht
im Platform-Admin (`/admin/jobs`) und gibt den Exit-Code des Skripts unverändert zurück. Ein
fehlgeschlagener Lauf löst darüber eine ntfy-Benachrichtigung aus, ein ausbleibender Lauf (>26 h)
ebenfalls - siehe Abschnitt 12. Solange die Crons nicht eingerichtet sind, zeigt `/admin/jobs`
beide Jobs als „Nie gelaufen“ (ohne Alarm). Neue Cronjobs mit ihrem Namen in
`backend/app/core/job_registry.py` eintragen, sonst erscheinen sie nur als „Nicht registriert“
und werden bei Ausbleiben nicht gemeldet.

### `scripts/backup_db.sh`

- **Zweck**: nächtlicher Postgres-Dump, unabhängig vom Deploy-Zyklus. Nutzt denselben
  `pg_dump`-Mechanismus wie der Pre-Deploy-Backup in `deploy.sh` (`docker compose exec db
  pg_dump ... | gzip`) - ein Cron-Backup lässt sich also genauso mit
  `scripts/restore_db.sh` zurückspielen wie ein Pre-Deploy-Backup (siehe Abschnitt 5, Rollback).
- **Welche Instanz**: bestimmt `scripts/lib/stack.sh` mit explizitem Compose-Projekt und
  -Dateien (wie `deploy.sh`): Host-Markierung `prod` → Release-Stack, Projekt `hocx`;
  **keine** Markierung → Quellcode-Instanz aus `docker-compose.yml`, Projekt aus
  `HOCX_COMPOSE_PROJECT` (Default `hocx`; läuft die Instanz über `scripts/dev.sh`,
  `HOCX_COMPOSE_PROJECT=hocx-dev` in `.env` oder in der Cron-Zeile setzen, dann wird auch
  `docker-compose.dev.yml` geladen). Auf einem `test`-Host lehnt das Skript ab (nur Demo-Daten).
  `run_job.sh` und `restore_db.sh` verwenden dieselbe Zuordnung.
- **Braucht**: keine Argumente (`.env` im Repo-Root muss `POSTGRES_USER`/`POSTGRES_DB`
  enthalten; der `db`-Container muss laufen, sonst bricht das Skript kontrolliert ab).
- **Env-Var**: `RETENTION_DAYS` (Default 14) - Cron-Dumps, die älter sind, werden nach jedem
  Lauf automatisch gelöscht. Pre-Deploy-Dumps rotiert `deploy.sh` selbst: die neuesten
  `PRE_DEPLOY_BACKUP_KEEP` (Default 10, als Shell-Variable beim Aufruf von `deploy.sh`) bleiben.
- **Schreibt nach**: `backups/<timestamp>-cron.sql.gz` (derselbe Ordner wie die
  Pre-Deploy-Backups, gut unterscheidbar am `-cron`-Suffix).
- **Offsite**: Ist `OFFSITE_BACKUP_REMOTE` gesetzt, endet der Lauf mit Exit ≠ 0, wenn die
  rclone-Kopie fehlschlägt oder `rclone` fehlt (das lokale Backup ist dann trotzdem
  geschrieben). `run_job.sh` meldet den Lauf damit als Fehler statt als Erfolg.
- **Empfohlener Cron-Zeitplan**: täglich 03:15 Uhr, mit Logdatei im selben `backups/`-Ordner
  (Pfade an den Checkout anpassen; auf einer über `dev.sh` betriebenen Instanz
  `HOCX_COMPOSE_PROJECT=hocx-dev` voranstellen):
  ```
  15 3 * * * /docker/hocX/scripts/run_job.sh backup_db /docker/hocX/scripts/backup_db.sh >> /docker/hocX/backups/backup_db.log 2>&1
  ```
- **Dateiablage (Audit MAIN-OPS-006):** Der Dump enthält nur die Datenbank. Uploads,
  Abgabebox-Dateien, Vorlagen und Mandanten-Importe/-Klone sichert das Borg-Backup
  (Abschnitt 14) zusammen mit der Datenbank; ohne Borg das Objekt-Backup `backup_storage`
  (Abschnitt 13). Umfang und Ausnahmen: `docs-site/docs/technik/backup/architektur.md`,
  Abschnitt «Umfang der Sicherung».
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

- **Zweck**: räumt ausschließlich `storage/exports/` (generierte PDF-Exportdateien)
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
  45 3 * * * /docker/hocX/scripts/run_job.sh cleanup_storage /docker/hocX/scripts/cleanup_storage.sh >> /docker/hocX/backups/cleanup_storage.log 2>&1
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
   (neue Datei unter `backups/`) prüfen, bevor der Code aktualisiert wird. Der Host hat
   keine Markierung in `/etc/hocx/environment`; das Skript sichert deshalb das Compose-Projekt
   aus `HOCX_COMPOSE_PROJECT` (Default `hocx`). Läuft die Instanz über `scripts/dev.sh`
   (Projekt `hocx-dev`), `HOCX_COMPOSE_PROJECT=hocx-dev ./scripts/backup_db.sh` verwenden.
2. **Update durchführen**: `git pull` + `docker compose up -d --build` (Alembic migriert
   die DB dabei automatisch, wie bei den anderen Umgebungen auch).
3. **Nach dem Update verifizieren** (analog zur Test-Verifikation in Abschnitt 2, mit
   einem Wegwerf-Testaccount, danach wieder löschen):
   - https://hocx.example.com/login erreichbar, Branding lädt korrekt
   - Login funktioniert, mindestens eine Tabellen-Seite lädt Daten
   - `docker compose logs backend --tail=50` zeigt keine Fehler, insbesondere keine
     Alembic-Fehler beim Start
4. **Bei Problemen**: Rollback wie in Abschnitt 5 beschrieben (`scripts/restore_db.sh`), mit
   dem in Schritt 1 frisch gezogenen Backup statt eines älteren Cron-Backups.

## 12. Monitoring und Benachrichtigungen

Im Platform-Admin unter **System**:

- **Systemstatus** (`/admin/system`): Container (Status, Healthcheck, Neustarts, CPU/RAM,
  Version) und Dienste (Postgres, Redis, ClamAV inkl. Signaturalter, Speicherplatz,
  Fehlerrate, Rückstand der Virenprüfung, Bildanalyse-Warteschlange, öffentliche
  Prüfseite der Dokumente), offene Probleme und
  die letzten Ereignisse. Gesammelt alle 30 s vom Loop `system_monitor` im Backend
  (`app/services/system_health_service.py`, Schwellwerte dort oben).
- **Jobs** (`/admin/jobs`): alle Hintergrund-Loops, der Bildanalyse-Worker und die
  Host-Cronjobs aus Abschnitt 10.
- **Benachrichtigungen** (`/admin/notifications`): ntfy-Konfiguration und das Status-Token
  für Uptime Kuma.

### Container-Übersicht: docker-socket-proxy

Das Backend liest Container-Daten über den Dienst `docker-socket-proxy`
(`lscr.io/linuxserver/socket-proxy`, per Digest gepinnt) - nur GET auf `/containers`,
`/_ping`, `/version`; alles andere beantwortet der Proxy mit 403. Er hängt allein mit dem
Backend im internen Netz `docker-api`, damit die öffentlich erreichbaren Dienste die
Docker-API (und darüber die Umgebungsvariablen aller Container) nicht erreichen. Das Backend
hat deshalb zwei Netze; das Label `traefik.docker.network=${COMPOSE_PROJECT_NAME}_default`
sorgt dafür, dass Traefik die richtige Backend-IP nimmt. Nach dem ersten Deploy mit diesem
Stand ist `docker compose up -d` nötig (neuer Dienst + Netz), nicht nur ein Neustart.

Ohne `DOCKER_API_URL` zeigt die Seite „Container-Übersicht nicht eingerichtet“; alle übrigen
Prüfungen laufen trotzdem.

### ntfy einrichten

1. `/admin/notifications` öffnen, Server-URL (z. B. `https://ntfy.example.com`), Topic und
   - falls der Server Zugriffsschutz hat - ein Access Token (`tk_…`) oder `benutzer:passwort`
   eintragen. Optional die Adresse des Admin-Portals, dann öffnet ein Tipp auf die Nachricht
   direkt die passende Seite.
2. Speichern, dann **Testnachricht senden**. Fehler (falsche URL, 401/403) erscheinen direkt
   auf der Seite.

Gemeldet wird:

| Ereignis | Priorität |
|---|---|
| Neues Problem, erst nach 90 s Bestand (Deploys lösen so keinen Alarm aus) | 3 (Warnung) / 4 (kritisch) |
| Problem verschärft sich (Warnung → kritisch) | 4 |
| Problem weiterhin offen (Erinnerung, Standard alle 6 h, 0 = aus) | wie das Problem |
| Problem behoben | 2 |
| Container neu gestartet (gleicher Container, neuer Start; ein Deploy zählt nicht) | 3 |

Mehr als fünf Meldungen auf einmal gehen als eine Sammelnachricht raus. Der Token liegt
verschlüsselt in `platform_notification_settings` (Schlüssel aus `ADMIN_AUTH_SECRET`) - wird
`ADMIN_AUTH_SECRET` rotiert, das ntfy-Token und das Status-Token neu setzen.

### Uptime Kuma (Überwachung von aussen)

Fällt das Backend oder der ganze Host aus, kann es selbst nichts mehr melden. Dafür:

1. In `/admin/notifications` unter „Überwachung von aussen“ ein Token erzeugen und die
   angezeigte URL kopieren (`https://<TRAEFIK_DOMAIN>/api/system-status/summary?token=…`).
2. In Uptime Kuma einen Monitor vom Typ **HTTP(s)** mit dieser URL anlegen, akzeptierte
   Statuscodes `200-299`, Intervall z. B. 60 s, Benachrichtigung über denselben ntfy-Server.

Der Endpunkt antwortet `200` (`status` = `ok` oder `warning`) bzw. `503` bei einem offenen
kritischen Problem oder wenn der Systemstatus älter als 3 Minuten ist (`status` = `critical`
/ `stale`). Die Antwort enthält nur Zähler. Wer auch bei Warnungen alarmiert werden will:
Monitor-Typ **HTTP(s) - Keyword** mit dem Keyword `"warnings":0`.

Ist die Landing Page aktiv (`TRAEFIK_WEBSITE_DOMAIN` gesetzt), einen zweiten Monitor anlegen:
Typ **HTTP(s)** auf `https://<TRAEFIK_WEBSITE_DOMAIN>/`, akzeptierte Statuscodes `200-299`,
**Zertifikatsablauf-Benachrichtigung** aktivieren. Die Website läuft im `frontend`-Container
mit; der Systemstatus sieht deshalb nur den Container, nicht ein falsches Routing, fehlendes
DNS oder ein abgelaufenes Zertifikat der Website-Domain.

### Wenn etwas nicht stimmt

- „Systemstatus veraltet“: Backend-Logs auf `Background-Loop system_monitor` prüfen;
  `/admin/jobs` zeigt den letzten Lauf und Fehler des Loops `system_monitor`.
- „Container-Status nicht verfügbar“: `docker compose ps docker-socket-proxy`, Logs des
  Proxys; läuft das Backend im Netz `docker-api`?
- Virensignaturen veraltet: Logs des `clamav`-Containers (freshclam) prüfen.

## 13. Öffentliche Prüfseite (Echtheit von PDFs)

hocX signiert keine PDFs. Jedes erzeugte PDF wird mit seinem SHA-256 im Dokumentenregister
erfasst; die öffentliche Prüfseite `https://<TRAEFIK_ABGABEBOX_DOMAIN>/verify` (Abgabebox)
vergleicht den im Browser berechneten Hash einer Datei mit dem Register. Es gibt keine
Zertifikate und keine Schlüssel zu verwalten.

### Konfiguration

- `DOCUMENT_VERIFY_BASE_URL` (optional): Prüf-URL, die in jedem PDF steht (Fusszeile, QR-Code,
  XMP). Leer = `ABGABEBOX_BASE_URL` + `/verify`. Bewusst die Plattform-Domain, nicht eine
  Mandanten-Domain - gedruckte Links müssen stabil bleiben. Nach einer Änderung tragen nur neue
  PDFs die neue Adresse; alte Links funktionieren nur, solange die alte Domain auf die Abgabebox
  zeigt.
- Traefik: Router `abgabebox-verify` (30 Anfragen/min, Burst 10, Body 4 KiB) ist Teil der
  Compose-Labels bzw. der generierten Mandanten-Domain-Router; nichts einzurichten.
- Die Abgabebox-Rolle `hocx_abgabebox` darf nur die Funktion `verify_document` ausführen
  (Migration 0117), nicht das Register lesen.

### Systemcheck

`/admin/system` → «Öffentliche Prüfseite»: das Backend fragt den Endpoint intern
(`ABGABEBOX_INTERNAL_URL`, Standard `http://abgabebox-backend:8000`) mit einem Hash ohne Treffer
ab und erwartet `{"found": false}`. Kritisch heisst: `abgabebox-backend` nicht erreichbar oder die
Funktion/Rechte fehlen (Migration 0117 gelaufen? `docker compose logs abgabebox-backend`).

### Organisationen verifizieren (Plattform-Admin)

1. Mandanten-Admins beantragen die Verifizierung unter Dokumente → Echtheitsprüfung.
2. Offene Anträge: Admin-Panel → **Verifizierungen** (oder Mandant öffnen → Tab «Verifizierung»).
3. Identität prüfen, z. B. Handelsregister/UID-Register, Statuten, Website mit Impressum, Rückruf
   an eine unabhängig gefundene Nummer. Erst dann **Bestätigen** und in der Notiz festhalten, wie
   geprüft wurde. Ablehnen nur mit Begründung (der Mandant sieht sie).
4. Bei Missbrauch: **Verifizierung entziehen** (sofort wirksam auf der Prüfseite).

Eine Namensänderung des Mandanten hebt die Verifizierung automatisch auf (auch durch einen
Plattform-Admin). Alle Schritte stehen im Audit-Log (`identity_verification.*`,
`admin.identity_verification_*`).

### Nach dem Update auf die Dokument-Engine / das Document Studio

Migration `0115` übernimmt die alten Dokumentvorlagen, `0118_document_studio` macht daraus
Brand-Profile (Hausstile → Profile, Rezepte → Vorlagen, Hausstil-Wahl der Protokollvorlagen →
Zuweisungen) und entfernt die alten Tabellen. Beides läuft beim Deploy automatisch. Vorher ein
frisches Backup ziehen: `0115` ist nicht umkehrbar, der Downgrade von `0118` stellt nur die
Struktur wieder her.

Danach die nicht mehr benutzten Vorlagen-Dateien entfernen (erst mit `--dry-run` ansehen):

```bash
./scripts/cleanup-legacy-document-templates.sh --dry-run "${HOCX_STORAGE_PATH:-./storage}"
./scripts/cleanup-legacy-document-templates.sh "${HOCX_STORAGE_PATH:-./storage}"
```

Hochgeladene Logos, Fussbilder und Schriften bleiben erhalten. Bestehende Dateien bleiben unter
`document_style_assets/` liegen (der Pfad steht in der Datenbank), neue Uploads landen unter
`document_assets/`. Beide Verzeichnisse gehören ins Backup.

Kontrolle nach dem Deploy:

1. Backend-Log: `ensure_document_studio` gleicht beim Start die mitgelieferten Vorlagen ab
   (keine Fehler im Admin-Fehlerlog).
2. Als Mandanten-Admin **Dokumente → Vorlagen** öffnen: alle Dokumenttypen haben Vorlagen mit
   Vorschaubild. **Corporate Design** zeigt mindestens ein Standardprofil.
3. Ein Protokoll exportieren (Export-Dialog, PDF erstellen) und auf `/verify` prüfen: «Original».

Ändert sich nach einem Update die Gestaltung einer mitgelieferten Vorlage, entsteht beim Start
eine neue Revision. Bestehende Exporte behalten ihre Revision (`document_export.template_revision_id`).

## 14. Dateispeicher (S3) und Wartung

Ausführlich: `docs-site/docs/technik/storage/` (Architektur, Betrieb, lokales S3, Migrationen,
Wartungsmodus, Backup & Recovery).

**Update auf 1.2**: `deploy.sh` ergänzt die neuen Secrets in `.env`, startet `local-s3`,
`storage-init` und `storage-worker`. Danach ist weiterhin das Dateisystem aktiv - es wird nichts
verschoben, bis die Erstmigration gestartet wird.

**Cronjobs ergänzen** (nach `backup_db`; `backup_storage` entfällt mit dem Borg-Backup, Abschnitt 14):

```cron
30 3 * * * /docker/hocX/scripts/run_job.sh backup_storage env HOCX_COMPOSE_PROJECT=hocx HOCX_COMPOSE_FILES="docker-compose.release.yml docker-compose.clamav.yml docker-compose.traefik.yml" /docker/hocX/scripts/backup_storage.sh >> /docker/hocX/backups/backup_storage.log 2>&1
*/5 * * * * /docker/hocX/scripts/run_job.sh storage_controller env HOCX_COMPOSE_PROJECT=hocx HOCX_COMPOSE_FILES="docker-compose.release.yml docker-compose.clamav.yml docker-compose.traefik.yml" /docker/hocX/scripts/storage_controller.sh >> /docker/hocX/backups/storage_controller.log 2>&1
```

**Erste produktive Migration** (Dateisystem → lokales S3):

1. Frisches DB-Backup (`scripts/backup_db.sh`) und Plattenplatz prüfen: das lokale S3 braucht
   etwa so viel Platz wie `storage/` belegt (die Originale bleiben während der Rückfallfrist liegen).
2. Wartung ankündigen: System → Wartung → «Wartung planen» (erscheint auf der Anmeldeseite).
3. System → Storage → Profil «Lokales S3 (Garage)» → «Verbindung testen».
4. «Migration vorbereiten» → Preflight abwarten → Schätzung prüfen → «Migration starten».
5. Fortschritt unter System → Storage verfolgen; die Wartung endet automatisch nach
   bestandener Endprüfung und Beobachtungsphase. Verweist die Datenbank auf fehlende Dateien
   (abgelaufene Exporte zählen nicht dazu), wartet der Cutover in voller Wartung auf
   «Umschalten bestätigen» (Liste im Prüfbericht) - Prüfbericht während der Wartung im Blick
   behalten. Scheitert die Prüfung nach dem Umschalten dreimal in Folge (`rollback_required`):
   «zur Kenntnis genommen», danach lässt sich die Wartung freigeben, sobald der automatische
   Healthcheck des aktiven Ziels bestanden ist.
6. Danach: `docker compose exec backend python -m app.workers.storage_verify --full`.

**Notfall**: Bei Fehlern bleibt die Wartung bestehen und das Dateisystem aktiv. Ursache im
Migrationsverlauf/Fehlerprotokoll prüfen, Migration fortsetzen oder abbrechen; die Wartung lässt
sich unter System → Wartung erst beenden, wenn alle Freigabebedingungen erfüllt sind.

## 14. Offsite-Backup (BorgBackup, Hetzner Storage Box)

Ausführlich: `docs-site/docs/technik/backup/` (Architektur, Einrichtung & Betrieb,
Wiederherstellung, Sicherheit). Kurzfassung:

**Einrichten (einmalig)** – Details und Hetzner-Abnahme in `backup/betrieb.md`:

1. Backup-Schlüssel auf dem Server (`~/.hocx-backup/id_backup`), Wartungsschlüssel **nur** offline.
2. Host-Key der Box prüfen und als `~/.hocx-backup/known_hosts` ablegen (Fingerprint mit Hetzner
   vergleichen) – nie ungeprüft akzeptieren.
3. In `authorized_keys` der Box: Backup-Schlüssel mit `command="borg-1.4 serve --append-only
   --restrict-to-repository …",restrict`, Wartungsschlüssel ohne `--append-only`. Automatische
   Snapshots der Box aktivieren.
4. `.env`: `BACKUP_STORAGEBOX_HOST/USER`, `BACKUP_SSH_KEY_PATH`, `BACKUP_KNOWN_HOSTS_PATH`,
   `BACKUP_PASSPHRASE` (zufällig, lang), `BACKUP_STORAGEBOX_QUOTA_BYTES`; `BACKUP_ENABLED=false`;
   `./scripts/deploy.sh prod`.
5. `docker compose -p hocx exec backup-worker python -m app.backup.cli init --i-understand-this-creates-a-new-repository`,
   ausgegebene ID als `BACKUP_REPOSITORY_ID` eintragen.
6. `… python -m app.backup.cli export-key --paper` → mit Passphrase, `.env` und
   `STORAGE_CREDENTIALS_KEY` in die Notfallmappe (offline, getrennt).
7. `BACKUP_ENABLED=true`, `./scripts/deploy.sh prod`. Unter System → Backups: erstes Backup
   erfolgreich, «Restore-Test starten» erfolgreich, Integritätsprüfung erfolgreich.
8. Cron-Einträge `backup_db` und `backup_storage` entfernen (`crontab -e`). Alte lokale Backups
   (`backups/*.sql.gz`, `backups/storage/`) erst nach bewusster Entscheidung löschen.

**Betrieb**: Backups alle 6 h (System → Backups → Einstellungen), Integritätsprüfung wöchentlich,
Restore-Test monatlich; Probleme meldet ntfy (Abschnitt 12). Vor jedem Deploy legt `deploy.sh`
ein geschütztes Backup an und bricht bei Fehlschlag ab (bewusst überspringen:
`HOCX_PRE_DEPLOY_BACKUP=skip`). Quartalsweise mit dem Wartungsschlüssel `compact` ausführen
(gibt durch die Retention freigegebenen Platz frei, siehe `backup/betrieb.md`).

**Notfälle** (Details `backup/restore.md`):

| Situation | Vorgehen |
|---|---|
| Mandant versehentlich verändert/gelöscht | System → Backups → Wiederherstellung → «Mandant als Kopie» (neuer Mandant, Original bleibt) |
| Gesamtzustand muss zurück | «Vollständige Wiederherstellung» (Rettungspunkt, isolierte DB, neue Storage-Generation, Tausch mit automatischem Rücktausch bei Fehler) |
| Server verloren / Datenbank weg | neuer Server, `.env` aus der Notfallmappe, nur `db` starten, `run --rm --no-deps --entrypoint python backup-worker -m app.backup.cli restore-full …`, dann `swap-database`, Deploy, Wartung freigeben |
| Storage Box nicht erreichbar | Backups laufen nach Rückkehr automatisch weiter (Retry mit Backoff, Fortsetzung ohne Neuübertragung); Hetzner-Status prüfen |
| `repository_id_mismatch`, `host_key_mismatch`, `repository_replay` | **nicht** übergehen – möglicher Angriff oder falsches Ziel; Box und Fingerprint manuell prüfen |
| Worker hängt/abgestürzt | Container startet neu und setzt den Auftrag fort; verwaister Backup-Hold wird automatisch gelöst |
| Verwaister Borg-Lock nach Absturz | nur wenn sicher kein Worker läuft: `… python -m app.backup.cli break-lock --yes` |

