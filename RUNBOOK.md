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

./scripts/update_deploy_code.sh --deploy   # Skripte/Compose auf den Stand des Candidates, dann deploy.sh test
./scripts/verify_release.sh test
```

Immer zuerst den Deploy-Code aktualisieren: neue Images brauchen die dazugehörigen Skripte und
Compose-Dateien (neue Dienste, Secrets, `.env`-Migration). `deploy.sh` bricht deshalb ab, wenn
der Checkout den Commit eines `test-<datum>-<sha>-r<n>`-Candidates nicht enthält. Ebenso bricht
es vor jeder Änderung ab, wenn Dateien im Checkout nicht `hocx-deploy` gehören (z. B. nach einem
`git pull` als root), und gibt den passenden `chown`-Befehl für root aus.

**Host-spezifische Anpassungen** (eigene CA, Port-Bindungen, ...) gehören in
`docker-compose.local.yml` im Repo-Root (nicht versioniert, Vorlage
`docker-compose.local.example.yml`), nie in versionierte Dateien: `deploy.sh`,
`verify_release.sh` und die Hilfsskripte laden sie automatisch zuletzt, und
`update_deploy_code.sh` bleibt frei von lokalen Änderungen.

`deploy.sh test` macht automatisch: Preflight + exklusiver Deploy-Lock → DB-Backup
(`backups/`) → Images pullen → Cosign-Signaturen pruefen → Digest-Manifest schreiben →
Alembic explizit ausfuehren → Container neu starten → Smoke-Checks
(Backend, Frontend, Abgabebox, Docs, ClamAV) → Demo-Mandant neu befuellen
(`scripts/seed_test_tenant.py` loescht und baut den Mandanten "Jubla Sonnenberg" bei
jedem Test-Deploy komplett neu auf - Login siehe Skript-Output/-Docstring. Laeuft nur auf
`test`, nie auf `prod`).
Nach den Smoke-Checks prueft `deploy.sh` jeden Traefik-Router von aussen (`scripts/lib/traefik_checks.sh`:
Frontend und Backend-API der Hauptdomain, Abgabebox-Frontend und -API inklusive `POST /api/public/verify`,
Admin-Frontend und -API ueber Port `TRAEFIK_ADMIN_PORT`, Docs, Website). Erreicht ein Router seinen Dienst
nicht (z. B. 504 wegen falschem Docker-Netz), rollt `deploy.sh` automatisch auf das vorherige Release zurueck;
bei der allerersten Installation gibt es nur eine Warnung.
Docs- und Website-Domain sind davon ausgenommen (nur Warnung). Ein automatischer Rollback setzt nur
die App-Images zurück, die Datenbank bleibt migriert: über Migration `0198_submission_manual_elements`
hinweg (1.4.1 → 1.4.0) ist das alte Backend für Einzelabgaben nicht mehr schemakompatibel - in
diesem Fall den Fehler beheben und vorwärts deployen statt beim alten Release zu bleiben.

`verify_release.sh test` prueft danach zusaetzlich:
- Backend / Abgabebox-Backend lokal erreichbar
- Frontend / Docs lokal erreichbar
- Alembic `current == heads`
- `https://test...`-Domains antworten ueber Traefik (per `curl` vom Host mit dem echten
  Host-Namen; ohne DNS bzw. bei privater Bindung wird direkt Traefik angesprochen. Eine eigene
  Test-CA per `HOCX_VERIFY_CA_FILE` in `.env` angeben.)

**Verifizieren** (mit einem Wegwerf-Testaccount, danach wieder löschen):
- https://test.hocx.ch/login erreichbar, Branding lädt korrekt
- Login funktioniert, mindestens eine Tabellen-Seite lädt Daten
- Abgabebox: https://abgabe-test.hocx.ch lädt (sofern ein Test-Mandant mit
  Abgabebox-Konfiguration existiert)
- `docker compose -p hocx-test logs backend --tail=50` zeigt keine Fehler, insbesondere
  keine Alembic-Fehler beim Start

**Abnahme durch Claude Code** auf dem Test-Host: Skill `testhost-abnahme`
(`.claude/skills/testhost-abnahme/SKILL.md`) führt `scripts/testhost/abnahme.sh` aus und wertet
die Ergebnisse selbst aus: Traefik-Komprimierung, Migrationen, Bereichs-CSS inklusive Dialoge,
Übersetzungen, Ladezeiten. Zugangsdaten stehen in `~/.hocx-testhost.env`, nie im Repository.

## 3. Getesteten Candidate zum Release promoten

Wenn Test erfolgreich war:

1. In GitHub → Actions den Workflow `Promote tested release images` starten.
2. Eingaben:
   - `source_tag`: genau der getestete Candidate-Tag, z.B. `test-20260825-abc1234-r42`
   - **Keine Versionseingabe:** Der Release-Tag kommt aus `CHANGELOG.md` des getesteten Commits
     (oberster Versionsabschnitt, z.B. `## [1.3.0] - 2026-11-16`; `[Unreleased]` muss leer sein).
     `Build test candidate images` schreibt dieselbe Version als Label
     `org.opencontainers.image.version` in jedes Image (Zusammenfassung des Builds: «release
     version»); die Promotion bricht ab, wenn ein Image eine andere oder keine Version trägt oder
     die Version unter der zuletzt veröffentlichten liegt. Ein Kandidat mit «unreleased» ist nur
     ein Testbuild: erst den Versionsabschnitt im Changelog anlegen, dann neu bauen.
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
   sein; sonst stoppt der Workflow vor der Promotion. `[Unreleased]` wird nicht verwendet.
   `update_latest` steuert auch
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
./scripts/update_deploy_code.sh --deploy
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

**Alte Images:** Nach einem erfolgreichen Update entfernt `deploy.sh` alte App-Images
(`ghcr.io/<namespace>/hocx-*`, `scripts/lib/image_cleanup.sh`). Es bleiben alle Images, die ein
Container verwendet, das aktuelle Release und die Images der letzten `HOCX_IMAGE_KEEP_RELEASES`
Release-Manifeste in `.releases/` (Default 3, als Shell-Variable beim Aufruf von `deploy.sh`);
`HOCX_IMAGE_CLEANUP=0` schaltet das ab. Fremde Images (postgres, redis, traefik …) werden nicht
angefasst, auch kein globales `docker image prune`. Ein Zurückgehen auf ein älteres Release zieht dessen
Images einfach neu.

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
./scripts/restore_db.sh backups/<timestamp>-pre-vX.Y.Z.sql.gz.gpg   # bzw. .sql.gz ohne Dump-Schlüssel
vim .env   # HOCX_VERSION auf die vorherige Version (…-pre-vX.Y.Z = Stand vor dem Update auf vX.Y.Z)
./scripts/deploy.sh prod
./scripts/verify_release.sh prod
```

**Rückweg hinter das PostgreSQL-18-Update (1.2.0 → 1.1.x):** Releases bis 1.1.x betreiben
PostgreSQL 16 auf dem Volume `<projekt>_postgres_data`, ab 1.2.0 läuft PostgreSQL 18 auf
`<projekt>_postgres18_data` (Umzug durch `deploy.sh`, `scripts/lib/pg_upgrade.sh`). Der alte
Deploy-Code startet wieder auf dem alten Volume - solange es noch existiert, also mit dem Stand
unmittelbar vor dem Update; ein `restore_db.sh` vorab wirkt dann nur auf die 18er-Datenbank und
ist überflüssig. Ist das alte Volume schon gelöscht, legt PostgreSQL 16 ein leeres an: dann
**zuerst** den alten Stand deployen und **danach** den Pre-Deploy-Dump mit `restore_db.sh`
einspielen. Ein Dump von PostgreSQL 18 lässt sich in 16 meist, aber nicht garantiert einspielen;
für den Rückweg deshalb den Dump *vor* dem Update (`…-pre-v1.2.0…`) nehmen.

**Rückweg hinter das Redis-8-Update (1.6 → 1.5.x):** Ab 1.6 läuft Redis 8 (`redis:8-alpine`). Redis 8
schreibt seinen Snapshot (`dump.rdb` im anonymen `/data`-Volume des Dienstes `redis`) im RDB-Format 15,
das Redis 7 nicht lesen kann: ein Redis-7-Container auf diesem Volume bricht beim Start mit «Can't handle
RDB format version 15» ab (geprüft 2026-11-23). Der automatische Rollback von `deploy.sh` ist davon nicht
betroffen - er tauscht nur die App-Images, Redis bleibt auf der Version aus dem Deploy-Code. Wer bewusst
auf den Deploy-Code von 1.5.x zurückgeht, muss **vorher** den Redis-Dienst samt Volume entfernen
(vom Betreiber akzeptiert). Dabei geht alles verloren, was nur in Redis liegt: Login-Tickets und MFA-Flows
(wer gerade mitten in einer Anmeldung ist, beginnt neu), Domain-Bridge-Tokens, Rate-Limit- und
Sperrzähler sowie temporäre Anmeldesperren (Stufe 4/5), Kollaborations-Sperren und Präsenz im
Protokoll-Editor, der Cache der Leak-Prüfung und Überlast-Markierungen. Angemeldete Sessions (signiertes
Cookie + Session-Register in PostgreSQL) und die Job-Warteschlange (PostgreSQL) bleiben erhalten:

```bash
docker compose --env-file .env -f docker-compose.release.yml rm -s -f -v redis   # -v: anonymes /data-Volume mit
./scripts/deploy.sh prod                                                          # Deploy-Code 1.5.x startet Redis 7 leer
```

Prüfen: `docker compose -f docker-compose.release.yml logs redis` zeigt «Ready to accept connections»
und keine RDB-Fehlermeldung. Ein Rollback nur der App-Images (gleicher Deploy-Code) braucht diesen Schritt nicht.

Hinweise zu Redis 8: Lizenz ist ab 8.0 wahlweise AGPLv3, RSALv2 oder SSPLv1 (Redis 7.4 war RSALv2/SSPLv1);
hocX betreibt das unveränderte offizielle Image nur intern und verteilt Redis nicht weiter. Das Image lädt
beim Start automatisch die mitgelieferten Module (Search, JSON, TimeSeries, Bloom, Vector Sets; ca. 20 MiB
RSS statt 4 MiB); hocX nutzt sie nicht. Konfiguration (`requirepass` aus dem Secret, `maxmemory` mit
`noeviction`), Standardbenutzer-ACL und RDB-Snapshots (`save 3600 1 300 100 60 10000`) verhalten sich wie
unter Redis 7.

Verschlüsselte Dumps (`.sql.gz.gpg`, siehe Abschnitt 10 «Verschlüsselung der Dumps») brauchen den
privaten Schlüssel aus der Notfallmappe: `BACKUP_DUMP_PRIVATE_KEY_PATH=/pfad/dump-private.asc` vor
den Aufruf setzen oder den Schlüssel im GPG-Schlüsselbund des Benutzers haben.

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
   prüfen (beim ersten Login wird ein Passkey eingerichtet, Abschnitt 22), danach im
   Admin-Panel weitere Admins anlegen und das Bootstrap-Passwort ändern.

## 9. Deploy-Code kontrolliert aktualisieren

Ab 1.2.4 aktualisiert `deploy.sh` den Deploy-Code vor jedem Lauf selbst: es ruft
`update_deploy_code.sh` auf und startet sich danach mit dem neuen Stand neu (Schleifenschutz
über `HOCX_DEPLOY_CODE_UPDATED`). Beim Update auf 1.2.3 hatte sonst ein veraltetes `deploy.sh`
das neue Release ausgerollt. Scheitert das Update (kein Netz, keine GitHub-Anmeldung, lokale
Änderungen), bricht der Deploy ab und das bisherige Release läuft weiter. Bewusst mit dem
vorhandenen Code deployen:

```bash
HOCX_SKIP_DEPLOY_CODE_UPDATE=1 ./scripts/deploy.sh prod  # auf dem Testhost entsprechend: test
```

Nur den Code aktualisieren (ohne Deploy) bzw. aktualisieren und deployen geht weiterhin direkt:

```bash
cd /docker/hocX
./scripts/update_deploy_code.sh
./scripts/update_deploy_code.sh --deploy
```

Der Updater akzeptiert nur die fest hinterlegte hocX-GitHub-Remote, den Branch `main`,
einen sauberen tracked Worktree und einen reinen Fast-Forward auf den neuesten Commit von
`origin/main` mit erfolgreichem `build-test-images.yml`-Lauf. Hat der neueste Commit keinen
eigenen Build (z. B. ein reiner Changelog-Commit), nimmt er den neuesten signierten Vorgänger,
nie einen älteren Stand als den aktuellen. Vor dem
Fast-Forward lädt er den zum Commit gehoerenden CI-Nachweis, prueft dessen keyless
Cosign-Signatur gegen den festen `build-test-images.yml`-Workflow und verifiziert die
Hashes aller Deploy-Skripte, Compose-, Traefik- und Garage-Dateien. Damit reicht ein blosses
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
- **Schreibt nach**: `backups/<timestamp>-cron.sql.gz.gpg` (verschlüsselt) bzw. ohne Schlüssel
  `…-cron.sql.gz` (derselbe Ordner wie die Pre-Deploy-Backups, gut unterscheidbar am
  `-cron`-Suffix).
- **Offsite**: Ist `OFFSITE_BACKUP_REMOTE` gesetzt, endet der Lauf mit Exit ≠ 0, wenn die
  rclone-Kopie fehlschlägt oder `rclone` fehlt (das lokale Backup ist dann trotzdem
  geschrieben). `run_job.sh` meldet den Lauf damit als Fehler statt als Erfolg. Ein
  **unverschlüsselter** Dump geht nur auf ein rclone-Remote vom Typ `crypt`, sonst bricht der Lauf
  ab. Nach jeder Kopie löscht das Skript Offsite-Dumps, die älter als `OFFSITE_RETENTION_DAYS`
  (Default = `RETENTION_DAYS`) sind - früher blieben sie unbegrenzt liegen.

#### Verschlüsselung der Dumps (Datenschutz-Audit PRIV-009)

`deploy.sh` (Pre-Deploy), `backup_db.sh` (Cron) und `restore_db.sh` (Sicherung vor dem Restore)
verschlüsseln Dumps mit einem **öffentlichen** GPG-Schlüssel. Auf dem Server liegt nur dieser; den
privaten Schlüssel gibt es nur in der Notfallmappe. Wer die Dumps kopiert (Fehlkonfiguration,
Offsite-Speicher, Hardware-Tausch), kann sie damit nicht lesen. Einmalig auf einem Admin-Rechner
**ausserhalb** des Servers:

```bash
export GNUPGHOME="$(mktemp -d)"
gpg --batch --passphrase '' --pinentry-mode loopback \
  --quick-gen-key "hocx dumps <ops@example.invalid>" future-default default never
gpg --armor --export > dump-public.asc                      # auf den Server
gpg --armor --export-secret-keys > dump-private.asc         # nur in die Notfallmappe
```

`future-default` erzeugt den nötigen Verschlüsselungs-Unterschlüssel (`ed25519` allein reicht
nicht). Auf dem Server `dump-public.asc` nach `~/.hocx-backup/dump-public.asc` legen (oder
`BACKUP_DUMP_PUBLIC_KEY_PATH` in `.env`). Fehlt der Schlüssel, schreiben die Skripte wie bisher
`.sql.gz` und warnen; `HOCX_REQUIRE_DUMP_ENCRYPTION=true` macht ihn zur Pflicht.

Pre-Deploy-Dumps bleiben höchstens `PRE_DEPLOY_BACKUP_MAX_DAYS` Tage (Default 30, Shell-Variable
beim Aufruf von `deploy.sh`), der neueste immer.
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
  liegt auf derselben Partition wie das Docker-Volume der Live-DB (`postgres18_data`) -
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
hat deshalb mehrere Netze; das Label `traefik.docker.network=${COMPOSE_PROJECT_NAME}_edge`
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
- **ntfy fällt aus**: Alarme gehen nicht verloren. Ein Ereignis gilt erst als gemeldet, wenn ntfy
  es angenommen hat (`system_health_event.notified_at`); bis dahin sendet der Loop
  `system_monitor` es bei jedem Lauf erneut, höchstens 24 Stunden lang. Der letzte Sendefehler
  steht unter `/admin/notifications`, im Fehlerprotokoll nur beim ersten Auftreten. Solange ntfy
  weg ist, `/admin/system` direkt ansehen (oder Uptime Kuma). Ist ntfy ausgeschaltet, werden
  Ereignisse der letzten 24 Stunden nach dem Einschalten nachgeliefert.
- **„Prüfung … schlägt fehl“** (Grund `check_failed`): Eine reine DB-Prüfung des Systemstatus
  wirft seit mindestens 15 Minuten eine Exception, meist nach einer Migration. Details im
  Fehlerprotokoll (`/admin/error-logs`), dort steht der Traceback.

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

hocX speichert Dateien nur noch in S3; eine Neuinstallation startet direkt auf dem lokalen S3
(Garage). `deploy.sh` ergänzt die nötigen Secrets in `.env` und startet `local-s3`,
`storage-init` und `storage-worker`.

**Update auf 1.2.3 (S3-only)**: Voraussetzung ist eine abgeschlossene Erstmigration auf S3 und
keine offene Storage-Migration, sonst bricht `deploy.sh` mit «Upgrade gesperrt» ab (das bisherige
Release läuft weiter). Liegt der alte Dateisystem-Bestand noch in der Rückfallfrist, fragt
`deploy.sh` «Rückfallfrist jetzt beenden und den Dateisystem-Bestand bereinigen? [j/N]»
(nicht interaktiv: `HOCX_SKIP_STORAGE_FALLBACK=1`) und wartet, bis der `storage-worker` des
bisherigen Releases bereinigt hat (`HOCX_STORAGE_PURGE_TIMEOUT`, Default 3600 s). Bereinigt werden
nur Dateien, deren Kopie die Erstmigration verifiziert hat. Danach gibt es keinen Weg zurück auf
das Dateisystem; Backups von vor der S3-Migration lassen sich nur mit 1.2.2 wiederherstellen.
Details: `docs-site/docs/technik/storage/migration.md`, Abschnitt «Upgrade auf S3-only».

**Cronjob `storage_controller`** richtet `deploy.sh` selbst ein (Marker
`# hocx-managed:<projekt>:storage_controller` in der crontab von `hocx-deploy`, abschaltbar mit
`HOCX_MANAGE_CRON=false`). Ein früher von Hand eingetragener `storage_controller`-Job bleibt
unverändert; ihn entfernen (`crontab -e`), damit der verwaltete Eintrag beim nächsten Deploy
übernimmt. Ohne Borg-Backup zusätzlich von Hand (`backup_storage` entfällt mit Abschnitt 15):

```cron
30 3 * * * /docker/hocX/scripts/run_job.sh backup_storage env HOCX_COMPOSE_PROJECT=hocx HOCX_COMPOSE_FILES="docker-compose.release.yml docker-compose.clamav.yml docker-compose.traefik.yml" /docker/hocX/scripts/backup_storage.sh >> /docker/hocX/backups/backup_storage.log 2>&1
```

**Notfall bei einer Migration**: Bei Fehlern vor dem Umschalten bleibt die Quelle aktiv. Ursache
im Migrationsverlauf/Fehlerprotokoll prüfen, Migration fortsetzen oder abbrechen; eine Wartung
lässt sich unter System → Wartung erst beenden, wenn alle Freigabebedingungen erfüllt sind.
Danach: `docker compose exec backend python -m app.workers.storage_verify --full`.

## 15. Offsite-Backup (BorgBackup, Hetzner Storage Box)

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
| Server verloren | neuer Server (Abschnitt 8 bis `provision_deploy_user.sh`), dann `./scripts/deploy.sh prod --restore-from-backup` - führt durch `.env`, Storage-Box-Zugang, Punktwahl und Restore ins lokale S3; danach Wartung freigeben (`backup/restore.md`) |
| Datenbank weg, Server läuft noch | nur `db` starten, `run --rm --no-deps --entrypoint python backup-worker -m app.backup.cli restore-full …`, dann `swap-database`, Deploy, Wartung freigeben |
| Storage Box nicht erreichbar | Backups laufen nach Rückkehr automatisch weiter (Retry mit Backoff, Fortsetzung ohne Neuübertragung); Hetzner-Status prüfen |
| `repository_id_mismatch`, `host_key_mismatch`, `repository_replay` | **nicht** übergehen – möglicher Angriff oder falsches Ziel; Box und Fingerprint manuell prüfen |
| Worker hängt/abgestürzt | Container startet neu und setzt den Auftrag fort; verwaister Backup-Hold wird automatisch gelöst |
| Verwaister Borg-Lock nach Absturz | nur wenn sicher kein Worker läuft: `… python -m app.backup.cli break-lock --yes` |


## 16. Dokumentverarbeitung (PDF-Ansicht, Textextraktion)

Ausführlich: `docs-site/docs/technik/dokumente.md`.

**Update**: Migration `0115_documents` (neue Tabellen, keine Datenänderung) läuft mit dem
normalen Deploy (`0116_protocol_export_formats` ist seit der Dokument-Engine ein No-op). Das Backend-Image enthält jetzt LibreOffice, Tesseract und Poppler (grösseres
Image). `deploy.sh` startet den neuen Dienst `document-worker` automatisch (`up -d`). Keine neuen
Secrets oder Umgebungsvariablen nötig; Grenzwerte sind optional (`DOCUMENT_*`, siehe Doku).

**Nach dem Deploy**: Der Loop `document_sync` legt Dokumente für bestehende Dateien und Exporte
in Batches an (alle 2 Minuten, `DOCUMENT_SYNC_BATCH_SIZE`); der Worker verarbeitet sie danach.
Bei vielen Altdateien läuft das einige Zeit - Fortschritt:

```bash
docker compose exec backend python -m app.workers.document_admin status
```

Sofort statt schrittweise: `... document_admin backfill`. Fehlgeschlagene Aufträge nach einer
Störung erneut einreihen: `... document_admin requeue`. Übernahme pausieren:
`DOCUMENT_BACKFILL_ENABLED=false` (stoppt auch die Anlage für neue Abgabebox-Uploads).

**Überwachung**: `/admin/jobs` → Kategorie Dokumente (`document_sync`, `document_worker`). Ein
überfälliger `document_worker` heisst: Container läuft nicht oder hängt
(`docker compose logs document-worker`). Aufträge mit abgelaufener Lease übernimmt ein neu
gestarteter Worker automatisch.


## 17. Job-Worker und Lastgrenzen (Concurrency-Audit 1.2)

Hintergrund: `ROBUSTNESS_CONCURRENCY_AUDIT.md` (Befunde CONC-001..024), Lasttests unter `loadtest/`.

**Neuer Dienst `job-worker`** (Backend-Image, `python -m app.workers.job_worker`): Galerie-Ingest,
PDF-Aufträge, Vereinsexport, Qualitäts-Backfill, Album-Sync, Virenscan-Nachprüfung und die grossen
Aufräumjobs laufen nicht mehr in den uvicorn-Workern. `deploy.sh` startet und prüft ihn automatisch
(`BACKEND_IMAGE_WORKERS`); ein Rollback auf ein Release ohne Job-Worker stoppt ihn, das ältere
Backend führt die Jobs dann wieder selbst aus. Ohne laufenden Job-Worker entstehen keine PDFs aus
Exporten und keine Galerie-Importe - `/admin/jobs` meldet `job_worker` als überfällig,
`/admin/system` die Prüfung «PDF-Aufträge».

**PDF-Export als Auftrag**: `POST /api/documents/render` prüft Rechte sofort und antwortet 202 mit
einem Auftrag (`document_render_job`); der Browser fragt `GET /api/documents/render-jobs/{id}` ab.
Auch das PDF nach dem Abschliessen eines Protokolls ist ein Auftrag (übersteht Neustarts, wird bei
«Compile-Platz belegt» oder Timeout bis zu dreimal wiederholt). Hängende Aufträge (> 15 min
`running`) setzt der Worker automatisch zurück.

**Überwachung**:
- `/admin/system` → «Auslastung der Dienstprozesse» (`runtime`): Event-Loop-Verzögerung,
  DB-Pool- und Threadpool-Belegung, Pool-Zeitüberschreitungen aller Prozesse der letzten Minute.
  Warnung ab 1 s Loop-Lag oder vollem Pool, kritisch ab 10 s.
- `/admin/system` → «PDF-Aufträge» (`render_queue`): Warteschlange älter als 10 min oder
  gescheiterte Aufträge (24 h).
- `pg_stat_activity.application_name` unterscheidet `hocx-backend`, `hocx-job-worker`,
  `hocx-document-worker`, `hocx-abgabebox-backend` usw.

**Stellschrauben** (Umgebung, Defaults in Klammern):

| Variable | Wirkung |
|---|---|
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` (12/8, Worker kleiner) | DB-Pool je Prozess; bei Erschöpfung nach `DB_POOL_TIMEOUT_SECONDS` (5) Antwort 503 `db_busy` mit Retry-After |
| `DB_ADMISSION_LIMIT` (leer = Pool + Overflow minus `DB_ADMISSION_RESERVE` 4, also 16; im Release-Stack nur über Pool und Reserve einstellbar) / `DB_ADMISSION_WAIT_SECONDS` (20) | gleichzeitige HTTP-Requests je Backend-Worker; der Rest wartet ohne Thread und Verbindung, danach 503 `db_busy`. Verhindert den Stau aus Threadpool und Pool unter Last (`app/core/db_admission.py`). Wer den Pool vergrössert, vergrössert die Annahme mit |
| `OVERLOAD_THRESHOLD_LOW` (0.75) / `OVERLOAD_THRESHOLD_NORMAL` (1.0) / `OVERLOAD_ACTIVE_MINUTES` (15) | Überlast-Schutz nach Abo: ab dieser geglätteten Auslastung (Requests in Arbeit + wartend je Platz der Request-Annahme) sehen *neue* Nutzer von Abos mit Priorität „niedrig“ bzw. „normal“ die Überlast-Seite; „hoch“ wird nie vorab abgewiesen. Wer in den letzten 15 Minuten gearbeitet hat, bleibt drin. Die Stufe je Abo steht im Adminportal (Preiskatalog), Abweisungen unter System → Überlast und als Warnung `overload` (ntfy) |
| `SECURITY_FAILED_LOGINS_WARNING` / `_CRITICAL` (50/200 in 15 min), `SECURITY_FAILED_LOGINS_PER_ACCOUNT` (20 in 15 min), `SECURITY_EXPORTS_PER_HOUR` (3), `SECURITY_ALERT_ADMIN_LOGINS` (false) | Schwellen des Checks «security» in `/admin/system` und ntfy |
| `GALLERY_UPLOAD_CONCURRENCY` (2) / `GALLERY_UPLOAD_SLOT_WAIT_SECONDS` (60) | gleichzeitige Galerie-Uploads je Backend-Worker, Wartezeit auf einen Platz |
| `CLOUD_IMPORT_MAX_JOB_FILES` (50000) / `CLOUD_IMPORT_MAX_JOB_BYTES` (107374182400 = 100 GiB) | Obergrenzen je Datei-Import (Mandanten › Dateien › Importieren); höchstens die Standardwerte. Einzeldateien behalten die Upload-Grenzen (20 MB Dokument, 100 MB Bild), ZIP-Archive je bis 10 GiB. Import-Uploads (`/api/cloud-import/uploads/`) nutzen dieselbe Upload-Annahme wie die Galerie (`GALLERY_UPLOAD_CONCURRENCY`, eigene Plätze) und stagen unter `UPLOAD_ROOT/_staging/cloud-import/<Auftrag>`; verarbeitet wird im job-worker (Job `cloud_import`) |
| `ABGABEBOX_UPLOAD_CONCURRENCY` (2) / `ABGABEBOX_UPLOAD_SLOT_WAIT_SECONDS` (120) | gleichzeitige öffentliche Uploads je Abgabebox-Worker (je bis 150 MiB im Speicher) |
| `DOCUMENT_RENDER_CONCURRENCY` (2) | Typst-Compiles je Prozess (Backend: Vorschau; Job-Worker: PDF-Aufträge) |
| `BACKUP_HEAVY_WINDOW_HOURS` (`1-5`) | lokales Zeitfenster (Europe/Zurich) für Backup-Verify und Restore-Test; der Backup-Worker läuft mit niedriger CPU-Priorität |

Teure Monitor-Zählungen (verwaiste Dateien, Belegung des lokalen S3) rechnet `/admin/system` nur noch
stündlich. Der Admin-Entrypoint hat dieselben Lese-/Schreibfristen (1 h) wie der öffentliche, damit
grosse Mandantenimporte nicht nach Traefiks Default von 60 s abbrechen; vor dem Entpacken eines
Imports wird freier Speicher geprüft.

PostgreSQL läuft mit `max_connections=150` (Budget rund 100, siehe Kommentar in der Compose-Datei).
Wer Pools oder Worker erhöht, rechnet das Budget nach.

## 18. Eigene Domains der Mandanten

Mandanten tragen eigene Domains selbst ein (Mandant-Einstellungen → Domains, Benutzer-Doku
`benutzer/einstellungen.md`). Das Backend schreibt daraus die Traefik-Datei
`infra/traefik/dynamic/tenant-domains.yml` (im Container `/app/traefik_dynamic`), nur für aktive
Domains mit gebuchtem Feature; Traefik lädt sie ohne Neustart und holt das Zertifikat über
`letsencrypt` (HTTP-Challenge, die Domain muss also schon auf den Server zeigen).

- **Ablauf**: Eine neue Domain ist `pending`, bis TXT-Besitznachweis und CNAME/A-Routing geprüft
  sind. Hat der Mandant für denselben Zweck schon eine aktive Domain, bleibt diese bis zur
  erfolgreichen Prüfung der neuen aktiv; erst dann tauscht `verify_domain` beide in einer
  Transaktion (Migration 0179: je Zweck höchstens eine aktive und eine ausstehende Domain).
- **Kontingente je Mandant und Stunde**: 5× anlegen, 20× prüfen, 10× löschen.
- **Zertifikat fehlt / Browser-Warnung**: Traefik-Logs nach der Domain durchsuchen (ACME-Fehler).
  Häufig zeigt die Domain (noch) nicht auf den Server oder ein CAA-Eintrag verbietet Let's Encrypt.
  Nach der Korrektur genügt es, die Seite erneut aufzurufen; Traefik versucht es selbst wieder.
- **„Nicht erreichbar“**: Der Loop `domain_health_check` prüft aktive Domains alle 30 Minuten (`DOMAIN_HEALTH_CHECK_INTERVAL_MINUTES`). Eine
  Domain, die nicht mehr auf den Server zeigt oder deren Feature nicht mehr gebucht ist, wird als
  ungesund markiert. Ungesunde, aber gebuchte Domains bleiben bewusst geroutet (DNS-Prüfungen können kurz falsch negativ sein); ohne gebuchtes Feature entfernt `regenerate()` den Router.
- **Domain manuell entfernen**: `/admin/domains` → Domain löschen (auditiert, schreibt die
  Traefik-Datei neu). Nie die YAML-Datei von Hand bearbeiten: sie wird beim nächsten
  `regenerate()` überschrieben.
- **Plan-Änderung**: Entfernt ein Admin `custom_domain`/`verify_domain` aus einem Plan, verlieren
  alle Mandanten auf diesem Plan das Feature sofort und die Traefik-Datei wird neu geschrieben.

## 19. Cashflow und Forderungen

`/admin/cashflow` zeigt Kosten und Forderungen. Forderungen entstehen je Abrechnungsperiode ab dem
Abo-Start beim Öffnen der Übersicht, der Forderungsliste oder der Mandantenseite «Abo & Nutzung»
(`cashflow_service.sync_charges`). Der Abgleich ist idempotent (Cursor
`tenant.billing_charged_until`, eindeutig je Mandant und Periodenbeginn) und läuft unter dem
Advisory-Lock `202600040`; lesende Aufrufe warten nicht darauf, sondern überspringen den Abgleich,
wenn er gerade anderswo läuft.

- **Forderung fehlt**: Abo-Start und Plan des Mandanten prüfen; Perioden ohne Preis werden
  übersprungen, der Cursor rückt trotzdem vor (keine rückwirkenden Forderungen nach einer
  Preisänderung).
- **Abo-Start geändert**: offene Forderungen werden verworfen und neu erzeugt, bezahlte und
  erlassene bleiben.
- **Fehler beim Abgleich**: Auf der Mandantenseite werden dann die bisherigen Forderungen gezeigt
  und der Fehler landet im Fehlerprotokoll; im Adminportal antwortet die Übersicht mit 500.

## 20. Wartungsseite bei Updates und Ausfällen

Ab 1.4.3 sehen Nutzer während eines Updates oder wenn ein App-Container nicht erreichbar ist statt
einer nackten Traefik-Fehlerseite (502/503/504, bzw. 404, wenn die Container ganz fehlen) eine
Wartungsseite. API-Aufrufe bekommen ein JSON-503.

**Aufbau**

- Dienst `maintenance-page` in `docker-compose.traefik.yml`: nginx-unprivileged (dasselbe, per
  Digest gepinnte Image wie `docs-site`), read-only, ohne Capabilities, 64 MB / 0.25 CPU, ohne
  Ports, ohne Secrets, nur im internen Netz `maintenance` (das ausser ihm nur Traefik nutzt). Er gehört zum Traefik-Teil des Stacks; ein App-Update erstellt ihn nicht neu.
  `deploy.sh` startet ihn vor den Migrationen und erstellt ihn nur neu, wenn sich
  `infra/maintenance/nginx.conf` ändert (`sync_maintenance_page_config`, Hash unter
  `.releases/maintenance-nginx.sha256`).
- Inhalte in `infra/maintenance/` (read-only gemountet; `deploy.sh` setzt Gruppe 5001 nur lesend,
  `prepare_maintenance_dir`):
  `maintenance.html` (eine Seite für alle Varianten, nginx setzt per SSI Variante, Prüfadresse und
  `tokens.css` ein), `api-503.json`, `tokens.css` (Kopie von `design/tokens.css`, nur über
  `./scripts/sync-design-tokens.sh`), `nginx.conf`.
- Traefik (`infra/traefik/dynamic/maintenance.yml`, Dateiprovider): errors-Middlewares
  `maintenance-errors` (Hauptdomain), `-admin`, `-abgabebox` (HTML, Status 502–504) und
  `maintenance-errors-api` (JSON, nur 502 und 504) stehen an allen App-Routern zuerst (nicht an
  Docs und Website). Sie liegen bewusst im Dateiprovider: fehlt der Container, bleibt die
  Konfiguration gültig und die App läuft unverändert weiter.
- Ausweich-Router (Labels am Dienst): `Host(<Domain>)` mit Priorität 1 je Domain (Hauptdomain,
  Abgabebox, Admin-Zugang) und ein API-Router mit Priorität 50 (über den Frontend-Routern 10, unter
  allen Backend-Routern 100–300). Sie gewinnen nur, wenn die App-Router fehlen.

**Verhalten**

| Fall | Antwort |
|---|---|
| App-Container gestoppt, entfernt oder noch nicht `healthy` (Update, Neustart) | Ausweich-Router: Wartungsseite bzw. JSON, **503**, `Retry-After: 30`, `Cache-Control: no-store` |
| Container läuft, Traefik erreicht ihn nicht (502/504) | errors-Middleware: dieselbe Antwort, Status auf 503 umgeschrieben |
| Backend antwortet selbst mit 503 (Wartungsmodus `maintenance`, Überlast `overloaded`, `db_busy`) | unverändert durchgereicht (das Frontend wertet den Code aus) |
| API während des Ausfalls | `{"detail": "...", "code": "service_unavailable", "retry_after": 30}`; das Frontend zeigt seinen normalen Fehler, die Abgabebox wiederholt Uploads nach `Retry-After` |
| `/api/health`, `/api/system-status/summary` (Uptime Kuma) während des Ausfalls | JSON-503, nie 200 |
| `deploy.sh`/`verify_release.sh` (`traefik_checks.sh`) | `curl --fail`: die Wartungsseite zählt nie als erreichbar |

Die Seite wählt die Sprache nach `navigator.languages` (alle Sprachen aus `i18n/locales.json`,
sonst Deutsch), folgt Hell/Dunkel des Systems, prüft alle 10 s `/api/health` (Admin-Zugang:
`/api/admin/auth/health`) ohne Cookies und lädt neu, sobald dort 200 kommt und die
Seite selbst nicht mehr von der Wartungsseite stammt (Kopfzeile `X-Hocx-Maintenance-Page`). Ohne
JavaScript lädt sie alle 30 s neu.

**Welche Meldung wann (ab 1.5.1)**

| Situation | Ausgeliefert von | Meldung |
|---|---|---|
| Update: Deploy-Fenster offen, alte bzw. neue App läuft | In-App `/maintenance` (angemeldete Nutzer), Hinweis auf `/login`, Banner der Abgabebox | **Update** («hocX wird aktualisiert», `vX → vY`, «Jetzt neu laden», nach 15 min «Das Update dauert länger») |
| Update: Container werden neu gestartet (502–504 bzw. kein Router) | statische Seite `maintenance.html` (hier) | **Update**, dieselben Texte |
| Ausfall ausserhalb eines Updates | statische Seite | **Update** ohne Versionen (die Seite weiss nicht, warum der Container fehlt) |
| Geplante/manuelle Wartung, Speicher, Wiederherstellung | In-App `/maintenance` | **Wartung** (Pill «Wartung läuft», voraussichtliches Ende mit Spanne und Balken bzw. «Noch kein genauer Zeitpunkt», Countdown bis zur nächsten Prüfung) |
| Deploy-Fenster **und** Admin-Wartung gleichzeitig | In-App | **Wartung** (nach dem Update kommt hocX nicht zurück) |

Die öffentliche Statusroute `/api/public/maintenance-status` liefert dafür `kind`
(`update`/`maintenance`) und beim Update `from_version`/`to_version` (nur Zeichen
`0-9A-Za-z._+-`, `maintenance_service.clean_version`); die Abgabebox liest dasselbe über
`maintenance_public_update()` (Migration 0212). Die Versionen schreibt `begin-deploy
--version <neu> --from-version <laufend>` ins Deploy-Fenster (`progress`).

Für die statische Seite schreibt `deploy.sh` vor `begin-deploy` die Datei
`infra/maintenance/update-info.json` (`write_maintenance_info`: Versionen, Beginn, optional
Statusseite; nicht im Repo, `.gitignore`), nginx bettet sie per SSI als JSON-Datenblock ein
(`location = /update-info.json` nur `internal`). Am Ende des Deploys (EXIT-Trap, auch bei Abbruch
oder Rollback) bleibt davon nur der Statusseiten-Link (`clear_maintenance_info`). Eine Info, die
älter als 6 Stunden ist, ignoriert die Seite.

**Statusseite (optional):** `HOCX_STATUS_PAGE_URL=https://…` in `.env` (nur einfache
https-Adressen, sonst ignoriert). Die Update-Seite (In-App und statisch) zeigt dann nach 15 Minuten
«Hält das länger als 15 Minuten an, schau auf der Statusseite nach.»; ohne Wert entfällt der Satz.
Die statische Seite übernimmt den Wert erst mit dem nächsten Deploy.

**Testen**

- Statisch (auch in der CI): `bash scripts/tests/test_maintenance_page.sh`.
- Echt mit Traefik in Docker (Wegwerf-Projekt, zufällige Ports, berührt keine Instanz):
  `flock /docker/.hocx-heavy.lock bash scripts/tests/test_maintenance_page.sh --live`.
- Auf dem Test-Host: `docker compose -p hocx-test … stop frontend` → `https://<Domain>/login`
  zeigt die Wartungsseite (503), `curl -sI https://<Domain>/api/health` nach `stop backend` liefert
  503 mit JSON; danach `… start frontend backend`. Nur auf dem Test-Host, nie auf Prod.

**Anpassen**

- Texte: `infra/maintenance/maintenance.html` (Objekt `TEXTS`, alle Sprachen vollständig; gleiche
  Wortwahl wie `frontend/messages/<locale>/maintenance.json` → `update.*`). Danach
  `bash scripts/tests/test_maintenance_page.sh` – er nennt den neuen CSP-Hash des Skripts, der in
  `infra/maintenance/nginx.conf` (`script-src 'sha256-…'`) eingetragen werden muss. Änderungen an
  HTML/JSON wirken sofort nach dem Deploy-Code-Update, eine geänderte `nginx.conf` erstellt
  `deploy.sh` den Dienst neu.
- Farben/Abstände nur über `design/tokens.css` und `./scripts/sync-design-tokens.sh`.

**Eigene Domains der Mandanten** (Abschnitt 18): `traefik_config_service.regenerate()` hängt an
jeden generierten Router dieselbe errors-Middleware (App-Domain: hocX-Seite, Abgabebox- und
Prüf-Domain: Abgabebox-Seite, API: JSON) und schreibt je Domain die Router `…-fallback`
(Priorität 1) und `…-fallback-api` (50) mit genau den Pfaden der Domain (Prüf-Domain: nur
Prüfseite und ihre API). Sie zeigen auf `maintenance-page@file`. Fehlt
`infra/traefik/dynamic/maintenance.yml` im Verzeichnis, lässt `regenerate()` all das weg.

**Wartungsmodus während des Updates** (`deploy.sh`, `backend/app/maintenance_cli.py`):

1. Vor `alembic upgrade`: `python -m app.maintenance_cli begin-deploy --version <v> --from-version <laufend>` (per
   `docker compose run --rm --no-deps backend`, mit dem Backend-Image des neuen Releases) legt ein
   volles Wartungsfenster an (`reason_code=deploy`, `source_job_type=deploy`) und setzt es sofort
   aktiv. Die noch laufenden alten Container sperren damit die API (503 `maintenance`); das
   Frontend leitet angemeldete Nutzer auf seine Update-Ansicht, die Anmeldeseite zeigt den
   Hinweis, die Abgabebox ihr Banner (ab 1.5.1 überall die Update-Meldung, siehe oben). Offen bleiben Admin-API, `/api/health`,
   `/api/system-status/summary` und der Wartungsstatus. Idempotent: ein offenes Deploy-Fenster wird
   wiederverwendet. Erste Installation (Tabelle fehlt): übersprungen.
2. Nach den Smoke-Checks, **vor** den Prüfungen über Traefik: `end-deploy --outcome success`. Vorher
   ginge nicht: in voller Wartung sperrt die Abgabebox auch die Prüfseite, deren Prüfung sonst ein
   Rollback auslöste. Lässt sich die Wartung nicht beenden (CLI und SQL scheitern), bricht
   `deploy.sh` hier ab **ohne Rollback** (das neue Release läuft) und nennt den Befehl zum Beenden;
   danach `verify_release.sh` und erneut `deploy.sh`. Die Prüfseiten-Prüfung meldet eine 503 mit
   Code `maintenance` ausdrücklich als «Wartung noch aktiv».
3. `rollback_apps` beendet die Wartung immer (`--outcome rollback`), ebenso eine fehlgeschlagene
   Migration und jeder andere Abbruch (EXIT-Trap, `--outcome aborted`).
4. `end-deploy` beendet nur Fenster mit `source_job_type=deploy` (auch verwaiste aus einem
   abgebrochenen Lauf), nie von Admins geplante oder Speicher-Fenster, und ohne die
   Freigabebedingungen (ein offener Speicher-Cutover hat sein eigenes Fenster). Scheitert die CLI,
   beendet `deploy.sh` das Fenster direkt per SQL im `db`-Container (mit Verlauf und Audit-Eintrag
   `outcome: sql-fallback`); scheitert auch das, steht im
   Log «Wartungsmodus des Updates ist NOCH AKTIV» mit dem Befehl. Von Hand:
   `docker compose -p <projekt> <compose-dateien> run --rm --no-deps backend python -m app.maintenance_cli end-deploy --outcome aborted`
   oder Admin-Portal → System → Wartung → Fenster «Update» freigeben. `status` zeigt offene
   Deploy-Fenster.
5. Begin-Fehler sind nur Warnungen. Abschalten: `HOCX_DEPLOY_MAINTENANCE=0
   ./scripts/deploy.sh <test|prod>`.
6. Systemmonitoring: die Prüfung `deploy_maintenance` (Adminportal → System, ntfy) warnt, wenn ein
   Deploy-Fenster länger als 30 Minuten aktiv ist, kritisch ab 2 Stunden.

Tests: `tests/test_maintenance_cli.py`, `tests/test_traefik_config_service.py` (Backend),
Reihenfolge in `deploy.sh` in `scripts/tests/test_maintenance_page.sh`; der Live-Test prüft mit
`MTEST_TENANT_FILE=<datei>` zusätzlich eine generierte `tenant-domains.yml`.

## 21. Plattform-Admin-Zugang (OpenZiti, Admin-Gate)

Das Plattform-Admin-Panel (`/admin…`, API `/api/admin…`) ist **ausschliesslich** über
`https://<TRAEFIK_ADMIN_DOMAIN>` auf Traefiks Entrypoint `adminsecure` erreichbar. Dessen Host-Port
(`TRAEFIK_ADMIN_PORT`, Default 8443) ist nur an `127.0.0.1` gebunden; erreichbar ist er nur über den
OpenZiti-Tunnel. Seit dem Auth-Audit (SEC-AUTH-001) ist das auf mehreren Ebenen abgesichert:

1. **Router:** Kein öffentlicher Router (Haupt-, Abgabebox-, Docs-, Website-, Mandanten-Domains)
   matcht `/admin` oder `/api/admin` (`!PathPrefix` in den Labels und in `tenant-domains.yml`).
   Mandanten-Domains, die einer Systemdomain gleichen oder Subdomain der Admin-Domain sind, werden
   bei Anlage, Prüfung und Import abgelehnt und beim Generieren übersprungen.
2. **Sperr-Router** `admin-block` (`infra/traefik/dynamic/admin-isolation.yml`, versioniert): auf
   `websecure` mit höchster Priorität für jeden Host, antwortet mit 404 ohne Backend.
3. **Gate-Header und Quelle:** Die Admin-Router setzen `X-Hocx-Admin-Gate` auf `ADMIN_GATE_SECRET`
   (Middleware `admin-gate@file` in `infra/traefik/dynamic/admin-gate.yml`, eine Kette). Davor
   lässt `admin-gate-source` nur die Quelladresse des Ziti-Tunnels zu: Über die Docker-
   Portweiterleitung von `127.0.0.1:<TRAEFIK_ADMIN_PORT>` sieht Traefik das Gateway des Netzes
   `<projekt>_edge`; ein Container im selben Netz, der `traefik:8443` direkt anspricht, bekommt
   403. Traefik hängt nur im Netz `<projekt>_edge` (mit Frontend, Admin-Frontend, Backend,
   Abgabebox, Docs), nicht im Netz von Datenbank und Workern; die Datenbank läuft ohne NET_RAW.
   `deploy.sh` ermittelt das Gateway von `<projekt>_edge` nach `compose up`; abweichend über
   `HOCX_ADMIN_SOURCE_CIDRS` (Komma-Liste, IPv4 mindestens /16, IPv6 mindestens /48).
   `admin-gate.yml` ist 0640 (Deploy-Benutzer), das Verzeichnis `infra/traefik/dynamic` 3770 mit
   Sticky-Bit: das Backend ersetzt nur seine eigene `tenant-domains.yml`. `verify_release.sh`
   vergleicht `admin-gate.yml` mit dem erwarteten Inhalt und prüft die versionierten Dateien
   (`git diff`). `websecure` und `adminsecure` entfernen einen von aussen
   mitgeschickten Header zuerst (`admin-gate-strip@file`).
4. **Backend** (`app/core/admin_gate.py`, äusserste Middleware): `/api/admin/*` nur mit korrektem
   Gate-Header und Host = Admin-Domain, sonst 404. Der Next.js-Server reicht Gate-Header und Host bei
   serverseitigen Admin-Aufrufen weiter (`frontend/lib/admin-gate.ts`), kennt das Secret aber nicht.
5. **Frontend:** Das Admin-Panel läuft als eigener Dienst `admin-frontend` (gleiches Image,
   `HOCX_FRONTEND_ROLE=admin`), nur hinter dem Admin-Entrypoint. Das öffentliche Frontend
   (`HOCX_FRONTEND_ROLE=public`) liefert `/admin` nie aus und reicht nie einen Gate-Header weiter
   (`frontend/proxy.ts`, `frontend/lib/admin-gate.ts`). Der Gate-Header geht nur an ein internes
   `INTERNAL_API_URL` (`deploy.sh` bricht sonst ab). Das Admin-Session-Cookie ist host-only und
   `SameSite=Strict`.
6. **Deploy/Verify** (`scripts/lib/traefik_checks.sh`): prüft über den Admin-Entrypoint
   `GET /api/admin/auth/health` (öffentlich, ohne Session) und über den öffentlichen Entrypoint, dass
   `/api/admin/…` und `/admin/…` auf Haupt-, Abgabebox-, Admin-, Docs-, Website- und einer
   Mandanten-Domain (`HOCX_VERIFY_TENANT_DOMAIN` oder die erste aus `tenant-domains.yml`, falls
   lesbar) 404 **mit** `X-Hocx-Admin-Block: 1` liefern - auch `/api/%61dmin/…`, `//api/admin/…` und
   `POST /api/admin/auth/login`, für alle aktiven Mandanten-Domains (aus dem Backend-Container,
   höchstens `HOCX_VERIFY_TENANT_DOMAIN_LIMIT`, Standard 20). Zusätzlich dürfen im
   Traefik-Dateiprovider-Verzeichnis nur `security.yml`, `admin-isolation.yml`, `admin-gate.yml`
   und `tenant-domains.yml` liegen (das Backend kann dort schreiben; ein eigenes Unterverzeichnis
   ginge nicht, weil Traefik Unterverzeichnisse nicht beobachtet). Sonst scheitert der Deploy mit
   Rollback.

**Secret:** `ADMIN_GATE_SECRET` (64 Hex) erzeugt `scripts/lib/env_migrate.sh` beim ersten Deploy
einmalig in der `.env`. `deploy.sh` schreibt bei jedem Deploy `.secrets/admin_gate_secret` (nur für
das Backend) und `infra/traefik/dynamic/admin-gate.yml` (0660, Gruppe 5001, nicht im Repo, kein
Docker-Label - sonst sähe man den Wert per `docker inspect`). Traefik lädt die Datei per `watch`
selbst; die geänderte `infra/traefik/traefik.yml` (Strip-Middleware an den Entrypoints) übernimmt
`deploy.sh` mit einem automatischen Traefik-Neustart (`sync_traefik_static_config`).
Secret rotieren: Wert in `.env` ersetzen (`openssl rand -hex 32`), `./scripts/deploy.sh <env>`.

**Fehlerbilder:**

- *Admin-Panel/-API überall 404, Fehlerprotokoll «ADMIN_GATE_SECRET fehlt»*: Backend läuft in
  production/test ohne Secret (fail closed). `.env` prüfen, neu deployen.
- *Admin-API 404, Admin-Seiten laden aber*: `admin-gate.yml` fehlt oder enthält einen anderen Wert
  als `.secrets/admin_gate_secret` (z. B. nach einer Rotation ohne Deploy). `deploy.sh` erneut
  laufen lassen. Traefik-Log: `middleware "admin-gate@file" does not exist` → Datei fehlt oder ist
  für Gruppe 5001 nicht lesbar.
- *Admin-API 403 über den Ziti-Zugang*: Quelladresse passt nicht (anderer Tunnel-Endpunkt, Netz neu
  erstellt ohne Deploy). `docker logs <traefik>`/Zugriff prüfen, `HOCX_ADMIN_SOURCE_CIDRS` setzen oder
  `deploy.sh` erneut laufen lassen.
- *Admin über die Hauptdomain erreichbar*: darf nie sein - `traefik_checks.sh` schlägt dann Alarm.
  `infra/traefik/dynamic/admin-isolation.yml` vorhanden? `docker logs <traefik>` auf Fehler im
  Dateiprovider prüfen (ein YAML-Fehler in einer Datei dort legt alle Datei-Middlewares lahm).
- **Entwicklung:** ohne `ADMIN_GATE_SECRET` und mit `HOCX_ENVIRONMENT=development` ist das Gate offen
  (kein OpenZiti-Einstieg, Next-Rewrite statt Traefik). `scripts/dev.sh` legt eine Entwicklungs-
  `admin-gate.yml` an, falls sie fehlt (für `--profile edge`). Die Quellcode-Instanz
  (`docker-compose.yml`) mit `HOCX_ENVIRONMENT=production` startet ohne `ADMIN_GATE_SECRET` und
  `TRAEFIK_ADMIN_DOMAIN` nicht; Produktion läuft über den Release-Stack (`deploy.sh`).
- **Tests:** `scripts/tests/test_admin_isolation.sh` (statisch, Labels, Secret-Verdrahtung) und
  `scripts/tests/test_admin_isolation_live.sh` (echter Traefik in Wegwerf-Containern).

## 22. Admin-Anmeldung: Passwort + Passkey, Notausgang

Seit Migration `0205_admin_passkey_only` melden sich Plattform-Admins **nur** mit Passwort und
Passkey an (WebAuthn, `userVerification: required`). TOTP und das Admin-SSO (OIDC) gibt es nicht
mehr. RP-ID ist die Admin-Domain (`TRAEFIK_ADMIN_DOMAIN`), erwarteter Origin fest
`https://<Admin-Domain>` - nie aus Headern des Clients. Über OpenZiti wird die Admin-Domain ohne
Port aufgerufen; ein Aufruf über den Host-Port (`…:8443`) wird für Passkeys nicht unterstützt.
Ausserhalb der Entwicklung startet die API ohne `TRAEFIK_ADMIN_DOMAIN` und `ADMIN_GATE_SECRET`
(≥ 32 Zeichen) gar nicht.

- **Erster Login / nach dem Update / neues Konto:** Nach dem Passwort verlangt die Login-Seite
  zwingend die Einrichtung eines Passkeys (Trust on first use). Erst danach gibt es eine Session;
  vorher erreicht das Konto keine andere Admin-API.
- **Weitere Passkeys** (empfohlen: zweites Gerät oder Sicherheitsschlüssel): Profil-Dialog
  (`/admin/security`). Der letzte Passkey lässt sich nicht entfernen. Sicherheitsschlüssel ohne
  PIN/Biometrie funktionieren nicht - die Nutzerverifikation ist Pflicht.
- **Passkey-Bestätigung (Step-up)** zusätzlich zur Session, gebunden an genau die eine Anfrage
  (Methode, Pfad, SHA-256 des Bodys; `app/core/admin_step_up.py`):
  Passkey hinzufügen/entfernen, Admin anlegen/ändern (Rolle, Passwort, Deaktivieren),
  Mandanten-Konten anlegen/ändern/löschen und ihre Rolle setzen, Benachrichtigungs- und
  E-Mail-Einstellungen (SMTP, ntfy, Status-Token), Mandant löschen/bereinigen/klonen,
  Mandanten-Export, MFA eines Mandanten-Kontos zurücksetzen,
  Speicherprofil löschen, Speicher-Migration anlegen/umschalten/fehlende Objekte akzeptieren,
  Generation endgültig löschen, Backup-Einstellungen, Wiederherstellung, Feature-/Plan-/
  Speicherpaket-Änderungen (Feature ändern, Plan/Paket löschen, Katalog-Import). Alle übrigen
  mutierenden Admin-Routen stehen begründet in `backend/tests/test_admin_step_up.py` (EXEMPT); eine
  neue Route ohne Bestätigung und ohne Begründung lässt die Tests scheitern.
- **Gesperrter Passkey:** Läuft der Zähler eines Passkeys zurück (geklonter Schlüssel?), wird er
  gesperrt (gilt für Login und Bestätigungen nicht mehr); Systemcheck «Admin-Passkeys» kritisch,
  Eintrag im Fehlerprotokoll. Schlüssel prüfen, dann den gesperrten Passkey in den
  Kontoeinstellungen entfernen (Bestätigung mit einem anderen Passkey) oder, falls es der einzige
  war, Notausgang `reset-passkeys`.
- **Prüfadresse** für Deploy, `verify_release.sh` und die Wartungsseite:
  `GET https://<Admin-Domain>/api/admin/auth/health` → `{"status":"ok"}` (ohne Session, ohne DB).
  `/api/admin/auth/oidc/public-config` gibt es nicht mehr.

**Notausgang** (Passkey oder Passwort verloren, letzter Admin ausgesperrt) - nur auf dem Host:

```bash
docker compose -p <projekt> exec backend python -m app.admin_cli reset-passkeys --email <admin-email>
docker compose -p <projekt> exec backend python -m app.admin_cli reset-password --email <admin-email>
```

`reset-passkeys` löscht alle Passkeys des Kontos, `reset-password` setzt ein neues zufälliges
Passwort und zeigt es genau einmal an. Beide beenden alle Sessions und offenen Login-Vorgänge,
löschen die Sperrzähler des Kontos und schreiben den Audit-Eintrag (`actor_email = cli`) in
derselben Transaktion. Nach `reset-passkeys` richtet das Konto beim nächsten Login nach dem Passwort
einen neuen Passkey ein - wer in diesem Moment das Passwort kennt, kann das tun. Deshalb sofort
selbst anmelden (bei Verdacht vorher `reset-password`).

**Benutzerkonto mit Login anlegen** (seit 1.5.1 setzt das Admin-Panel keine Passwörter mehr, dort
gibt es «Einladung senden» bzw. «Zurücksetzungslink senden»; die CLI ist für Testumgebungen wie
`scripts/e2e.sh` und Notfälle ohne Mailversand). Passwort nur über stdin, nie als Argument:

```bash
printf '%s' "$PASSWORT" | docker compose -p <projekt> exec -T backend python -m app.admin_cli \
  create-user --tenant-name "<Mandant>" --email <adresse> --role reader
```

## 23. Anmeldeschutz (Auth-Audit 2026-11-20)

Code: `backend/app/auth_security/` (Zähler und Schichten `guard.py`, Risk Engine `risk.py`,
IP-Sperren `blocks.py`, Sessions `sessions.py`, Step-up `step_up.py`, Alarme `threats.py`,
Ereignisse `events.py`), gemeinsame Zähler-Primitive `backend/app/core/rate_limit.py`.

### Was passiert bei einer Anmeldung

1. Quelle gesperrt (automatisch/manuell)? → 429 `source_blocked` (bekannte Geräte ausgenommen).
2. Versuchsrate je Quelle (GCRA: IPv4 /32 und /24, IPv6 /64, /48 und /32) → 429 `rate_limited`.
3. Zähler **vor** der Passwortprüfung (Lua, atomar): Konto+Quelle (`AUTH_ACCOUNT_IP_FAILURES`, 10/15 min,
   hart), Konto (`AUTH_ACCOUNT_FAILURES_CHALLENGE` 30 → zusätzliche Prüfung,
   `AUTH_ACCOUNT_FAILURES_KNOWN_ONLY` 100 → unbekannte Geräte nur noch mit Faktor/E-Mail-Code), Quelle
   (`AUTH_IP_FAILURES_SOFT/HARD` 20/60), Netz (IPv4 /24, IPv6 /48 mit Faktor `AUTH_NET6_FACTOR` 4;
   `AUTH_NET_FAILURES_SOFT` 60/15 min, `AUTH_NET_FAILURES_HARD_HOUR` 300/h), je Gerät (10/15 min,
   danach verliert ein bekanntes Gerät seine Ausnahme), global (Angriffsmodus ab
   `AUTH_GLOBAL_ATTACK_MIN` 100/15 min und 5 × gewohnte Rate; endet von selbst, sobald die
   Fehlversuche im gleitenden 15-min-Fenster abklingen).
4. Risk Engine (Score 0-100, Gründe im Ereignis): normal → wie bisher; moderat/hoch → zweiter Faktor,
   ohne Faktor ein **Code per E-Mail**; kritisch → diese Verbindung 30 min abgewiesen.
5. Erfolg: Gerät wird als bekannt gespeichert (Cookie `__Host-hocx_device`, 90 Tage), Session im Register
   (`auth_session`), Ereignis `login.success`, ggf. Mail an die Person.

**Bekannte Geräte** sind von der Kontosperre und den Quellgrenzen ausgenommen: ein Angreifer kann die
Inhaberin nicht mehr aussperren. Eine Geräte-ID wird nur an ein Konto gebunden, wenn sie bei diesem Konto
neu ausgestellt wurde; das Gerät, auf dem «Passwort vergessen» abgeschlossen wird, gilt danach als bekannt.

**Passwort vergessen** (`POST /api/auth/password-reset/request`, immer 202): je Quelle 10 Anfragen in
15 min (sonst 429 nur für diese Quelle), je Adresse und je Adresse+Quelle höchstens 3 Mails pro Stunde.
Haben Fremde das Adress-Kontingent aufgebraucht, bekommt die Inhaberin von einem **bekannten Gerät
ihres Kontos** (signiertes Cookie `__Host-hocx_device`, Eintrag in `auth_known_device` dieses Kontos)
trotzdem eine Mail: eigenes Kontingent von 3 Mails pro Stunde je Gerät (höchstens 6 pro Stunde und Konto). Konto und Gerät prüft erst die
Hintergrundaufgabe nach der Antwort - Antwort und Laufzeit verraten nichts. Fremde, gefälschte oder einem
anderen Konto gehörende Gerätecookies bekommen kein Zusatzkontingent.

**Ohne E-Mail-Versand** gilt: Konten mit zweitem Faktor werden nie abgewiesen (der Faktor ist die Prüfung).
Konten ohne Faktor auf unbekanntem Gerät werden nur bei Quellsignalen (L1/L2) oder über L5 abgewiesen
(429 `login_denied`, gleich für falsches und richtiges Passwort); der Angriffsmodus allein weist nie ab.
**E-Mail-Versand einrichten** (Adminportal → Benachrichtigungen), dann bekommen diese Fälle einen Code.

**E-Mail-Versand gestört** (ab 1.5.1, `app/notifications/delivery_status.py`): Jeder Versandversuch
(Benachrichtigungen, Login-Code, Test-Mail) meldet Erfolg/Fehler zentral. Ab dem ersten Fehler seit dem
letzten Erfolg gilt der Versand als gestört (Ausnahme: einzelne abgelehnte Empfängeradressen erst ab drei
in Folge, und dann nur als Warnung). Solange er gestört ist, bekommen Anmeldungen, die einen Mailcode
bräuchten, sofort 503 `auth_email_unavailable` («Anmeldung aktuell nicht möglich, wende dich an deinen
Administrator»); höchstens ein Login je Minute versucht den Versand echt. Bekannte Geräte und Konten mit
zweitem Faktor sind nicht betroffen - **ausser** Konten ohne zweiten Faktor, deren Passwort seit 1.5.2 als
geleakt markiert ist (Leak-Prüfung beim Login): sie brauchen bei jeder Anmeldung den Mailcode, auch auf
bekannten Geräten, und sind während einer Störung ausgesperrt. Je nach Verbreitung schwacher Passwörter
kann das viele Konten treffen; Abhilfe ist die Behebung der Störung (nicht das Abschalten der Prüfung).
Einzelne Personen können ein neues Passwort über die Verwaltung bekommen (Zurücksetzungslink ebenfalls
per Mail) oder einen zweiten Faktor einrichten, sobald sie wieder angemeldet sind. `/admin/system` zeigt die Prüfung «E-Mail-Versand» (kritisch, ntfy-
Problem `email:smtp:<grund>`), das Fehlerprotokoll den ersten Fehler je Fehlerklasse (danach stündlich).
Behebung: Adminportal → Einstellungen → Benachrichtigungen, SMTP prüfen, Test-Mail senden; der erste
Erfolg hebt die Störung auf. Bei Verbindungs-, TLS- und Anmeldefehlern prüft zusätzlich der Loop
`notification_dispatch` jede Minute die Verbindung (ohne Mail) und hebt die Störung selbst auf.

### Einstellungen (`.env`, Startwerte aus dem Audit)

| Variable | Standard | Wirkung |
|---|---|---|
| `AUTH_RISK_MODE` | `enforce` | `monitor`: Risk Engine nur protokollieren (Zähler-Sperren gelten weiter) |
| `AUTH_SESSION_IDLE_MINUTES` / `AUTH_SESSION_ABSOLUTE_HOURS` | 480 / 336 | Inaktivität / absolute Dauer einer Session |
| `AUTH_STEP_UP_MFA_MINUTES` / `AUTH_STEP_UP_ADMIN_MINUTES` | 10 / 15 | Höchstalter der letzten starken Anmeldung für Faktor-Änderungen bzw. Rollen, Exporte, Sicherheitseinstellungen |
| `AUTH_EVENT_RETENTION_DAYS` | 90 | Aufbewahrung `auth_event` |
| `AUTH_ACCOUNT_IP_FAILURES`, `AUTH_ACCOUNT_FAILURES_CHALLENGE`, `AUTH_ACCOUNT_FAILURES_KNOWN_ONLY` | 10, 30, 100 | Konto-Schichten L4/L5 |
| `AUTH_IP_FAILURES_SOFT/HARD`, `AUTH_NET_FAILURES_SOFT`, `AUTH_NET_FAILURES_HARD_HOUR` | 20/60, 60, 300 | Quell-Schichten L1/L2 |
| `AUTH_GLOBAL_ATTACK_MIN` | 100 | Angriffsmodus (L7) |
| `AUTH_BLOCK_STRIKES`, `AUTH_BLOCK_MINUTES` | 3, `60,360,1440` | Automatische Sperre nach Strikes in 24 h, Dauer je Wiederholung (max. 24 h) |
| `AUTH_DEVICE_TTL_DAYS` | 90 | Lebensdauer «bekanntes Gerät» |
| `AUTH_SECRET_PREVIOUS` | leer | Schlüsselrotation (unten) |
| `AUTH_LEGACY_COOKIE_UNTIL` | leer (= Start + 72 h) | bis wann der bisherige Cookie-Name `hocx_session` noch gelesen wird |
| `AUTH_NET6_FACTOR` | 4 | IPv6: L2-Grenzen je /48 = Netz-Grenzen × Faktor |
| `SECURITY_ALERT_ADMIN_LOGINS` | `true` (neu) | jede Plattform-Anmeldung meldet sich im Check «security» |
| `PASSWORD_LEAK_CHECK` | `on` | Leak-Prüfung neuer Passwörter: `on` (HIBP-Range-API, Rückfall lokale Liste), `local-only`, `off` |
| `PASSWORD_LEAK_MIN_COUNT` | 1 | ab so vielen Vorkommen in HIBP abgelehnt |
| `PASSWORD_LEAK_FETCH_PER_MINUTE` | 600 | höchstens so viele HIBP-Abfragen je Minute (alle Prozesse), darüber lokale Liste |
| `PASSWORD_BREACH_RECHECK_DAYS` | 30 | Leak-Prüfung beim Login (1.5.2): Nachtjob `password_breach_recheck` merkt Konten mit älterer Prüfung vor, die nächste Anmeldung prüft ohne Cache |
| `GEOIP_AUTO_UPDATE` | `true` | Job `geoip_update` lädt DB-IP «IP to Country Lite» monatlich (`false`: kein Download) |

Weitere Werte (Body-Limit 16 KiB für `/api/auth/*`, GCRA-Raten, Alarmschwellen `AUTH_ALERT_*`) stehen in
`backend/app/core/config.py` und können bei Bedarf ebenfalls gesetzt werden (Allowlist in
`scripts/lib/env.sh` und `docker-compose.release.yml` ergänzen).

### Leak-Prüfung neuer Passwörter (SEC-AUTH-015)

Jeder Setzpfad (Einladung, Passwort vergessen, Profil, Verwaltung, Plattform-Admin-Konten) prüft nach
der Stärkeregel, ob das Passwort aus einem Datenleck bekannt ist (`backend/app/core/password_leak.py`,
Antwort 400 `password_leaked`). Standard: Range-API von «Have I Been Pwned» mit k-Anonymität - nur die
ersten **5 Hex-Zeichen** des SHA-1 gehen an `api.pwnedpasswords.com` (Header `Add-Padding: true`,
User-Agent `hocx-password-check`, Timeout 2 s), Antwort je Präfix 1 h im Redis. Nicht erreichbar →
lokale Liste im Image (`backend/app/core/leaked_passwords.bin`, rund 74 000 SHA-1-Präfixe der
häufigsten geleakten Passwörter ab 12 Zeichen aus SecLists, MIT; neu erzeugen mit
`python3 scripts/build-leaked-password-list.py`). Fehlt beides, wird das Passwort angenommen (Warnung im
Log, Check `password_leak` im Systemmonitor). Anmeldungen prüfen nie gegen HIBP.

Ausgehend braucht das Backend dafür HTTPS zu `api.pwnedpasswords.com`; ohne Internetzugang
`PASSWORD_LEAK_CHECK=local-only` setzen.

### Länder-Geolocation (Signal «neues Land»)

Der job-worker lädt monatlich DB-IP «IP to Country Lite» (CC BY 4.0, ohne Konto,
`https://download.db-ip.com/free/dbip-country-lite-JJJJ-MM.mmdb.gz`), prüft die Datei gegen die SHA1-Prüfsumme
der offiziellen Download-Seite (`https://db-ip.com/db/download/ip-to-country-lite`; ohne passende Prüfsumme
wird nichts übernommen), dann inhaltlich (Typ «Country», IPv6-Baum, Grösse, Erstelldatum, Stichproben) und ersetzt die alte atomar im Volume `geoip_data`
(`/var/lib/hocx/geoip`, Backend nur lesend). Job `geoip_update` unter `/admin/jobs` (täglicher Tick,
Download nur bei neuer Monatsausgabe). Gespeichert wird nur der Ländercode (`auth_event.src_country`,
`auth_session.country`, `auth_known_device.last_country`, Migration `0215_auth_geo_country`), nie die IP;
Löschfristen wie die Anmeldeereignisse bzw. Sessions/Geräte. Risk Engine: Land in 90 Tagen erfolgreicher
Anmeldungen nie gesehen → `new_country` (10 Punkte, allein nie entscheidend; ohne frühere Anmeldung mit
Land kein Signal). Fehlt die Datei, entfällt das Signal still (Check `geoip`: «nicht eingerichtet», kein
Alarm). Ohne Internetzugang `GEOIP_AUTO_UPDATE=false` und die MMDB-Datei bei Bedarf selbst ins Volume
legen (`docker compose cp … job-worker:/var/lib/hocx/geoip/dbip-country-lite.mmdb`).

### Notfallzugang und Entsperren

Im Backend-Container (`docker compose exec backend …`):

```bash
python -m app.auth_security.cli list                    # aktive IP-Sperren (nur Pseudonyme)
python -m app.auth_security.cli unblock-ip 203.0.113.7  # Sperre einer Adresse, ihres /24 und ihres Netz-Fingerprints aufheben
python -m app.auth_security.cli unblock <subject>       # Sperre per Pseudonym aus "list"
python -m app.auth_security.cli reset-account person@example.org   # Fehlversuchszähler eines Kontos löschen
python -m app.auth_security.cli attack-mode-off         # Angriffsmodus 1 h aussetzen
```

Dieselben Sperren sind über `/api/admin/auth-security/blocks` (Plattform-Admin, nur Owner) lesbar,
setzbar (Stufe 5, Begründung + Ablauf, max. 30 Tage), verlängerbar (`…/blocks/{subject}/extend`, macht
auch eine automatische Sperre zur manuellen Stufe 5) und aufhebbar - jeweils mit Passkey-Bestätigung
(`security-block`); jedes Setzen/Verlängern/Aufheben erzeugt ein Ereignis `block.set`/`block.clear`
(gekürztes Subjekt, Admin, ab 1.7 Vorfall) und einen Audit-Eintrag.

**Konsole › Sicherheit (1.6):** *Sperren* zeigt die Abwehrleiter (Stufen 1-3 zählen bewusst **Ereignisse** der letzten 24 h -
Fehlversuche, wegen Grenzen abgewiesene Versuche, Zusatzprüfungen -, nicht Quellen, weil es dafür nur
gleitende Redis-Zähler je Quelle ohne Übersicht gibt; 4-5 aktive Sperren), Karten mit Countdown und Zähler «Abgewiesen» (Redis `authblock:hits:*`) und den
Verlauf 7 Tage aus `block.set`/`block.clear` (Ereignisse vor 1.6 haben kein Subjekt und fehlen dort).
*Anmeldeereignisse* filtert mit Pflicht-Zeitraum (max. 14 Tage) nach Pseudonym-Präfixen, Land, Typ,
Ergebnis und Mandant; «Quelle sperren» sperrt den **Netz-Fingerprint** des Ereignisses (Bereich
`net_fp`, dasselbe Pseudonym wie `auth_event.src_net_hash`/`audit_log.ip_hash`, /24 bzw. /48) -
`is_blocked` prüft ihn zusätzlich zu den Zähler-Pseudonymen. *Alarmregeln* zeigt je Regel den Messwert
auch unter der Schwelle, eine Kurve 24 h (Näherung: feste Abschnitte = Fenster der Regel, mind. 15 min,
statt gleitendem Fenster; in der Oberfläche vermerkt) und die Auslösungen 30 Tage (aus `system_health_event`);
Schwellen bleiben `.env`-Einstellungen. Migration `0280_auth_event_subject_index` baut den Index
`(subject_hash, ts)` mit `CREATE INDEX CONCURRENTLY` (ohne Schreibsperre; bei 90 Tagen Aufbewahrung
Sekunden bis wenige Minuten). Bricht sie ab, bleibt ein ungültiger Index zurück, den der nächste Lauf
selbst entfernt und neu baut. Der Plattform-Login ist von den App-IP-Sperren
ausgenommen (Ziti ist der stärkere Nachweis). Wer nicht mehr hineinkommt, obwohl das Konto in Ordnung
ist: vom gewohnten Gerät anmelden (bekannte Geräte sind ausgenommen) oder `reset-account`.

**Redis voll (noeviction):** Die Zählerschlüssel sind kurz und laufen nach höchstens 2 h ab; der Check
`auth_protection` warnt ab 70 %. Optional kann ein eigenes Redis nur für die Zähler betrieben werden
(`RATELIMIT_REDIS_URL` in `backend/app/core/config.py`, z. B. mit `maxmemory-policy volatile-lru`):
unter einem Angriff werden dort Zähler verdrängt, statt dass das Haupt-Redis (Login-Tickets) volläuft.
Der Release-Compose bringt diesen Dienst noch nicht mit (offen, Entscheid Betrieb).

**Redis weg/voll:** bekannte Geräte melden sich weiter an (lokale Notgrenze je Prozess, 5/min/IP,
20/min/Konto); unbekannte Geräte bekommen 503 `auth_temporarily_unavailable`; Konten mit zweitem Faktor
brauchen Redis für das Login-Ticket. Bestehende Sessions laufen ohne Redis weiter. Der Check
`auth_protection` wird kritisch (ntfy).

### Alarme (ntfy, Systemstatus)

Check `auth_protection`: Limiter-Ausfälle (kritisch), Redis über 70 % belegt, verlorene Ereignisse,
Anteil Anmeldungen mit privater Quelladresse ≥ 50 % (SEC-AUTH-019: IPv6 über docker-proxy oder zu
weite `TRUSTED_PROXY_CIDRS` - dann teilen sich alle Nutzer einen Zähler; Docker-IPv6 aktivieren bzw.
`TRUSTED_PROXY_CIDRS` auf das Compose-Netz einengen). Probleme `auth:<regel>`: `stuffing` (kritisch),
`spraying`, `account_attack` (Admin: kritisch), `admin_mfa` (kritisch), `admin_new_device`, `blocks`,
`network`, `cross_tenant`, `tenant`, `limiter` (kritisch). Entprellung und «Behoben» wie bei allen
anderen Problemen. Vorgehen bei Stuffing: Angriffsmodus läuft automatisch (unbekannte Geräte brauchen
Code/Faktor); betroffene Konten mit Erfolg aus neuem Netz → Sessions der Person beenden
(`/api/admin/auth-security/events?event_type=login.success`), Passwort zurücksetzen lassen.

### Sessions und Schlüsselrotation

- Profil › Sicherheit › «Angemeldete Geräte»: einzelne Sessions oder alle anderen abmelden. «Abmelden»
  beendet nur die eigene Session, `/api/auth/logout-all` alle.
- Passwort- oder Faktor-Änderung beendet alle **anderen** Sessions, ein Passwortwechsel vergisst zudem die
  anderen bekannten Geräte; «Passwort vergessen» beendet alle Sessions und vergisst alle Geräte ausser dem,
  auf dem der Reset abgeschlossen wird. Bekannte Geräte lassen sich im Profil einzeln vergessen.
- Sessions auf einer Mandanten-Domain (Domain-Bridge) erben Frische und Ende der Ausgangs-Session und
  enden mit ihr. Sessions von vor dem Update werden bei Passwort-/Faktorwechsel, «Alle anderen
  abmelden» oder Step-up ins Register übernommen, ohne verlängert zu werden.
- **Rotation von `AUTH_SECRET`:** alten Wert in `AUTH_SECRET_PREVIOUS`, neuen in `AUTH_SECRET`,
  `./scripts/deploy.sh`. Sessions und Geräte-Cookies gelten weiter; nach `AUTH_SESSION_ABSOLUTE_HOURS`
  (14 Tage) `AUTH_SECRET_PREVIOUS` leeren und erneut deployen. Pseudonyme (Zähler, Netz-Baselines)
  beginnen nach der Rotation neu - kurz mehr «neues Netz»-Signale, keine Mails dadurch.

### Wartungsjob

«Passwort vergessen»: je Adresse gehen höchstens 3 Mails pro Stunde raus (auch je Quelle 3); weitere
Anfragen bekommen 202 ohne Versand, 429 nur die anfragende Quelle (10 in 15 min).

`auth_security_maintenance` (stündlich, `/admin/jobs`): löscht `auth_event` nach 90 Tagen, beendete
Sessions nach 30 Tagen, Geräte nach 120 Tagen ohne Nutzung und repariert Zähler ohne Ablauf
(`repaired_keys` > 0 im Lauf deutet auf einen Fehler).

## 24. Admin-Konsole, Kennzahlen-Aggregation und Sicherheitsansichten (Admin-Redesign 1.5.0)

**Aufbau:** Das Plattform-Admin ist in sieben Bereiche gegliedert (Übersicht, Mandanten, Benutzer &
Zugänge, Sicherheit, Betrieb, Analysen, Einstellungen); Ctrl+K/⌘K sucht Seiten, Mandanten und Domains
(für owner auch Benutzer, Jobs, Checks, Audit-Codes). Alte Adressen leiten um: `/admin/audit` →
`/admin/security/audit`, `/admin/notifications` → `/admin/settings/notifications` (E-Mail-Versandprotokoll
unter `/admin/operations/delivery`), Profil/Passkeys unter `/admin/account`. `/admin/system` und
`/admin/jobs` bleiben (ntfy-Links).

**Status-Token (Uptime Kuma):** Die Status-URL mit Token wird nur noch direkt nach «Neuen Token
erzeugen» angezeigt (Einstellungen › Benachrichtigungen & E-Mail), danach nur «gesetzt, endet auf …».
Bei Verlust neuen Token erzeugen und in Uptime Kuma eintragen.

**Job `metrics_rollup`** (job-worker, Lock-ID 202600037, Kategorie Wartung, Takt stündlich):
- rechnet fehlende Kalendertage bis gestern (Europe/Zurich) in `platform_metric_daily` und
  `tenant_metric_daily` (RLS) nach, idempotent; der erste Lauf ergänzt 90 Tage rückwirkend aus
  `audit_log`/`created_at`. Speicher, gebuchte Features und MRR gibt es nur ab Einführung (kein Backfill).
- Läuft er nicht (Jobs-Seite «überfällig»), zeigen die Analysen den letzten Stand; ein späterer Lauf holt
  die Lücke ohne Doppelzählung nach. Einen Tag neu rechnen: Zeilen des Tages in beiden Tabellen löschen,
  der nächste Lauf rechnet ihn neu.
- Der Systemmonitor schreibt höchstens alle ~5 min Stichproben nach `system_metric_sample`
  (Aufbewahrung 14 Tage über `log_cleanup`).

**Neue Rechte:** Mandanten-Berechtigung `security.read` (nur Standardrolle «admin») für
Einstellungen › Sicherheit & Anmeldungen (`/tenant-settings/security`, API `/api/auth-security/activity`).
`access.manage` allein reicht dafür nicht mehr; Sitzungen eines Kontos beenden verlangt weiterhin
`access.manage` und eine frische Anmeldung.

**Rechte-Übersicht:** `permissions/route-map.json` führt für Plattform-Routen `admin_level`
(A = jeder Admin, W = owner schreibend, O = owner lesend) und `step_up` (Passkey-Zweck). Eine
Herabstufung erscheint im Diff und gehört begründet in die Commit-Nachricht.

## 25. Upload-Verlauf (1.6)

Migrationen `0250_upload_history`, `0251_capture_change_batches`, `0252_upload_history_abgabebox`
(Tabellen mit RLS, Spalten an `stored_file`/`gallery_upload_job`, zwei Trigger mit SECURITY
DEFINER). Kein neues Secret, keine neue Einstellung, kein neuer periodischer Job (verlassene Vorgänge
schliesst `log_cleanup`). Technik: `docs-site/docs/technik/upload-verlauf.md`.

**Einmal nach dem Update:** Altbestand rekonstruieren (idempotent, je Mandant kurze Transaktionen,
Ausgabe nur Zählungen; darf jederzeit wiederholt oder abgebrochen werden):

```bash
docker compose -p <projekt> <compose-dateien> exec -T backend python -m app.workers.upload_history_backfill
# nur ein Mandant:
docker compose -p <projekt> <compose-dateien> exec -T backend python -m app.workers.upload_history_backfill --tenant <tenant-public-id>
```

Ohne diesen Lauf funktioniert alles; ältere Dateien zeigen dann keinen Upload-Vorgang und lassen sich
nicht über den Verlauf als Ganzes bearbeiten. Last: liest nur Datenbankzeilen (keine Dateien aus S3).

**Kamera-Kürzel:** abgeleitet aus `ADMIN_AUTH_SECRET` (HKDF je Mandant). Wird dieses Secret gewechselt,
erscheinen ältere und neuere Fotos derselben Kamera als zwei Geräte; sonst keine Folgen.
Für Fotos von vor 1.6 trägt der Job `camera_serial_backfill` (job-worker) die Kürzel selbst nach;
Fortschritt je Verein: `SELECT tenant_id, last_file_id, upper_file_id, checked, keyed, finished_at FROM
camera_serial_backfill WHERE finished_at IS NULL;`. Neu starten für einen Verein (z. B. nach einem
Secret-Wechsel): `UPDATE stored_file SET camera_serial_key = NULL WHERE tenant_id = <id>;` und die
Zeile in `camera_serial_backfill` löschen - der nächste Tick nimmt den Verein neu auf.
Die Seriennummer selbst steht in keiner Datenbankspalte, bleibt aber in den EXIF-Daten der
unverändert gespeicherten Originaldatei (wie vor 1.6, bewusst so entschieden).

**Datenexport:** `Uploads.xlsx` im Vereinsexport enthält neben den Vorgängen die Einträge je Datei
(auch Namen abgelehnter Dateien), Datei-Importe mit Quellpfad und Datumskorrekturen; die Auskunft
einer Person dasselbe für ihre eigenen Vorgänge.

## 26. Foto-Standorte (1.6)

Migration `0260_photo_places`: globale Ortsdaten (`geo_place`, `geo_dataset`, Zwischenablage
`geo_place_import`), Ort je Foto (`photo_location` mit RLS), Rückgängig-Tabellen. Neue DB-Rolle
**`hocx_geo`** nur für den Import der Ortsdaten: sie schreibt die Zwischenablage und führt
`hocx_geo_import_apply` aus, liest `geo_place`/`geo_dataset` und hat keinen Zugriff auf
Mandantentabellen. `hocx_app` liest die Ortsdaten nur. Technik: `backend/UPLOAD_DUPLICATES.md` §16.

**Neues Secret `GEO_DB_PASSWORD` (+ `GEO_DATABASE_URL`).** Upgrade bestehender Installationen:

1. `scripts/deploy.sh` wie gewohnt ausführen. `scripts/lib/env_migrate.sh` ergänzt beide Werte in
   der `.env` (64 Hex-Zeichen, einmalig erzeugt) und meldet «ergaenzt: GEO_DB_PASSWORD»; deploy.sh
   schreibt `.secrets/geo_db_password` (Backend, für die Migration) und `.secrets/geo_database_url`
   (nur job-worker) und bricht ab, wenn das Passwort fehlt oder ein Platzhalter ist.
2. Die Migration legt die Rolle an (fehlt `GEO_DB_PASSWORD` und gibt es die Rolle noch nicht,
   bricht sie ab - wie bei den anderen Rollen). Gibt es die Rolle schon (z. B. beim Restore älterer
   Sicherungen durch den backup-worker), läuft sie ohne Passwort durch und lässt es unverändert.
3. Danach lädt der job-worker die Ortsdaten (Job `geo_places_update`, ~70 MB von
   `download.geonames.org` und `data.geo.admin.ch`, ~1-2 min, ~300 MB in Postgres) und
   `photo_places_resolve` beschriftet den Altbestand in Stücken. Läuft der job-worker in der
   Produktion ohne `GEO_DATABASE_URL` und mit `GEO_PLACES_AUTO_UPDATE=true`, startet er nicht.

Manuelle Installationen ohne deploy.sh (z. B. die Dev-Instanz mit `docker-compose.yml`): vor dem
Update `GEO_DB_PASSWORD` (zufällig, `openssl rand -hex 32`) und
`GEO_DATABASE_URL=postgresql+psycopg://hocx_geo:<passwort>@db:5432/<POSTGRES_DB>` in die `.env`
eintragen. Ohne Netz zu den Quellen: `GEO_PLACES_AUTO_UPDATE=false` und
`docker compose exec backend python -m scripts.import_geo_places --geonames-cities … --swissnames …`
(nutzt `GEO_DATABASE_URL`, sonst den Owner-Zugang des Backends).

Restore auf einen neuen Server: `restore-full` legt `hocx_geo` wie die anderen Laufzeitrollen an,
sofern `GEO_DB_PASSWORD` gesetzt ist (`scripts/lib/restore_from_backup.sh` reicht es durch).
**Passwort wechseln** (die Migration läuft nicht erneut, ein neuer Wert in `.env` allein ändert die
Rolle nicht):

1. In der Datenbank setzen, der Client hasht das Passwort selbst (nicht in Shell-Verlauf/Logs):
   `docker compose -p <projekt> <compose-dateien> exec db psql -U <POSTGRES_USER> -d <POSTGRES_DB> -c '\password hocx_geo'`
2. Denselben Wert als `GEO_DB_PASSWORD` und in `GEO_DATABASE_URL` in die `.env` eintragen.
3. `scripts/deploy.sh` ausführen (schreibt die Secret-Dateien neu, startet den job-worker neu).


## 27. Cloud-Import einrichten (1.6)

Datei-Import direkt aus Cloud-Diensten (Technik: `docs-site/docs/technik/datei-import.md`, Abschnitt
«API-Quellen»). Ein Anbieter erscheint im Wizard nur, wenn er vollständig konfiguriert ist; ZIP- und
Ordner-Import brauchen nichts davon. Dieselbe Anleitung liegt für die Planung unter
`audit-reports/plans/2026-11-25-cloud-import-registrierung.md`.

**Gemeinsam für alle Anbieter**

- Redirect-URI je Umgebung: `https://<TRAEFIK_DOMAIN>/api/cloud-import/oauth/<anbieter>/callback`
  (zentrale Domain; hocX springt danach selbst auf die Vereinsdomain zurück). Andere Basis nur über
  `CLOUD_IMPORT_REDIRECT_BASE_URL`.
- `CLOUD_IMPORT_TOKEN_KEY` (Secret) verschlüsselt die OAuth-Tokens; `deploy.sh` erzeugt ihn einmalig
  (`scripts/lib/env_migrate.sh`). Zusammen mit `.env` sichern. Rotation: neuen Wert setzen, bisherigen
  als `CLOUD_IMPORT_TOKEN_KEY_PREVIOUS`, deployen, nach 7 Tagen `_PREVIOUS` leeren (länger lebt keine
  ungenutzte Verbindung). Geht der Schlüssel verloren, melden sich laufende Importe einfach neu an.
- `CLOUD_IMPORT_ENABLED=false` schaltet alle Cloud-Anbieter ab.
- `CLOUD_IMPORT_MAX_PARALLEL_DOWNLOADS` (Standard 2, höchstens 8): gleichzeitige Downloads je Import im
  job-worker. Zusätzlich bremst ein Token-Bucket je Konto in Redis (der job-worker ist dafür im Netz
  `cache`). Bei vielen 429 im Log den Wert senken.
- Laufende Importe aller Mandanten, Kennzahlen und Notfall-Abbruch: Adminportal → Betrieb →
  **Datei-Importe** (`/admin/cloud-imports`).
- Nach jeder Änderung: `scripts/deploy.sh`; Kontrolle unter /admin/system, Prüfung **Cloud-Import**
  (aktive Importe, hängende Importe, warten auf Anmeldung, Ablauf der Client-Secrets).
- Tokens werden gelöscht, sobald ein Import endet; unterbrochene Importe behalten sie höchstens 7 Tage
  ohne Nutzung (Job `cloud_import` räumt auf).

### 27.1 Microsoft (OneDrive privat, OneDrive for Business, SharePoint)


**Ziel:** eine Entra-App-Registrierung (mehrinstanzenfähig + persönliche Konten), vertraulicher
Client mit Client-Secret, nur delegierte Lese-Berechtigungen, verifizierter Herausgeber.

**Empfehlung zu Umgebungen:** Produktion bekommt eine **eigene** App-Registrierung. Test-Host und
hocx-dev dürfen sich eine zweite Registrierung teilen (zwei Redirect-URIs). So betrifft ein Fehler oder
ein abgelaufenes Secret im Test nie die Vereine in Produktion, und der Consent-Dialog in Produktion
zeigt nie Test-URLs.

#### Voraussetzungen

1. Ein Microsoft-Entra-Tenant des Betreibers (Entra ID Free reicht, kostenlos). Wer noch keinen hat:
   mit dem Betreiberkonto unter <https://entra.microsoft.com> anmelden bzw. einen Microsoft-365-
   oder Azure-Tenant anlegen.
2. Konto mit der Rolle **Anwendungsadministrator** (oder Cloudanwendungsadministrator) in diesem Tenant,
   mit MFA (Pflicht für die Herausgeberverifizierung).
3. Für die Herausgeberverifizierung: die Betreiber-Domain (z. B. die Domain der Website) als
   **verifizierte benutzerdefinierte Domain** im Tenant und ein Konto im **Microsoft AI Cloud Partner
   Program** (Partner Center), siehe Schritt 7. Vorlauf: einige Tage bis Wochen - früh starten.
4. Öffentlich erreichbare Seiten für **Datenschutzerklärung** und **Nutzungsbedingungen** (URLs).

#### Schritt 1 - App registrieren

1. <https://entra.microsoft.com> → **Identität** → **Anwendungen** → **App-Registrierungen** →
   **Neue Registrierung**.
2. **Name:** `hocX Datei-Import` (Test: `hocX Datei-Import (Test)`). Der Name erscheint im
   Anmeldedialog der Vereinsmitglieder.
3. **Unterstützte Kontotypen:** «Konten in einem beliebigen Organisationsverzeichnis (beliebiger
   Microsoft Entra ID-Mandant – mehrinstanzenfähig) und persönliche Microsoft-Konten (z. B. Skype,
   Xbox)».
4. **Umleitungs-URI:** Plattform **Web**, `https://<TRAEFIK_DOMAIN>/api/cloud-import/oauth/microsoft/callback`
   - Produktion: `https://<prod-domain>/api/cloud-import/oauth/microsoft/callback`
   - Test-Host: `https://<test-domain>/api/cloud-import/oauth/microsoft/callback`
   - hocx-dev: `https://<dev-domain>/api/cloud-import/oauth/microsoft/callback`
     (Entra verlangt https; `http` nur für `localhost`).
5. **Registrieren**.
6. Auf der Übersichtsseite die **Anwendungs-ID (Client-ID)** kopieren → `.env`:
   `CLOUD_IMPORT_MS_CLIENT_ID=<Anwendungs-ID>`. Die Verzeichnis-(Tenant-)ID wird **nicht** gebraucht
   (hocX nutzt die Autorität `common`).

#### Schritt 2 - Authentifizierung prüfen

**Authentifizierung** (bzw. «Authentication»):

- Weitere Redirect-URIs (Test/Dev) unter **Plattform Web → URI hinzufügen** ergänzen. Keine Wildcards.
- **Implizite Genehmigung und Hybridflows:** beide Häkchen (Zugriffstoken, ID-Token) **aus**.
- **Öffentliche Clientflows zulassen:** **Nein**.
- URL für Front-Channel-Abmeldung: leer lassen.
- **Manifest** → `"requestedAccessTokenVersion": 2` (bzw. `accessTokenAcceptedVersion: 2` im alten
  Manifest). Bei «persönliche Konten» setzt Entra das automatisch; nur kontrollieren.

#### Schritt 3 - Client-Secret mit Ablaufdatum

1. **Zertifikate & Geheimnisse** → **Geheime Clientschlüssel** → **Neuer geheimer Clientschlüssel**.
2. Beschreibung: `hocX <Umgebung> <JJJJ-MM>`; **Ablauf: 24 Monate** (Maximum; kürzer ist sicherer,
   bedeutet aber häufigeres Wechseln).
3. **Wert** (nicht «Geheimnis-ID») sofort kopieren - er ist nur jetzt sichtbar → `.env`:
   - `CLOUD_IMPORT_MS_CLIENT_SECRET=<Wert>`
   - `CLOUD_IMPORT_MS_CLIENT_SECRET_EXPIRES=<Ablaufdatum JJJJ-MM-TT>` (aus der Spalte «Läuft ab»).
4. Erinnerung im Kalender setzen. hocX warnt zusätzlich: Prüfung **Cloud-Import** in /admin/system
   wird 30 Tage vor Ablauf gelb (ntfy), nach Ablauf rot. `deploy.sh` verweigert den Deploy, wenn die
   Client-ID gesetzt ist, aber Secret oder Ablaufdatum fehlen.

**Wechsel vor Ablauf:** neues Secret anlegen (altes bleibt gültig), `.env` mit neuem Wert und neuem
Datum aktualisieren, `scripts/deploy.sh`, danach das alte Secret in Entra löschen. Laufende Importe
behalten ihre Tokens; nur neue Anmeldungen und Refreshes nutzen das neue Secret.

#### Schritt 4 - API-Berechtigungen (nur delegiert, nur lesend)

**API-Berechtigungen** → **Berechtigung hinzufügen** → **Microsoft Graph** → **Delegierte
Berechtigungen**:

| Berechtigung | Wofür | Zeitpunkt der Abfrage in hocX |
|---|---|---|
| `openid`, `profile`, `offline_access` | Anmeldung, Refresh-Token | erste Anmeldung |
| `User.Read` | Anzeige «Verbunden als …» | erste Anmeldung |
| `Files.Read` | eigene Dateien (OneDrive privat/Business; privat inkl. geteilte) | erste Anmeldung |
| `Files.Read.All` | «Für mich freigegeben» (Geschäftskonten) | erst wenn jemand das im Baum aufklappt |
| `Sites.Read.All` | SharePoint-Bibliotheken | erst wenn jemand SharePoint aufklappt |

- **Keine** Anwendungsberechtigungen, **keine** Schreibberechtigungen.
- «Administratorzustimmung für <Betreiber-Tenant> erteilen» ist nur für Konten des Betreiber-Tenants
  nötig; Vereine stimmen in ihrem eigenen Tenant zu.
- Die Liste ist wichtig für den Admin-Consent in Vereins-Tenants: der Link
  `/{tenant}/adminconsent?client_id=…` erteilt genau diese statisch eingetragenen Berechtigungen.

#### Schritt 5 - Branding und Eigenschaften

**Branding & Eigenschaften**:

- Name, **Logo** (hocX-Logo, 215×215 px, PNG/JPG, < 100 KB).
- **URL der Startseite:** Website von hocX.
- **URL der Nutzungsbedingungen** und **URL der Datenschutzerklärung** (Pflicht für Verifizierung
  und Vertrauen im Consent-Dialog; die Datenschutzerklärung beschreibt den Cloud-Import, Plan §11.3).
- **Herausgeberdomäne:** die verifizierte Betreiber-Domain auswählen (statt `*.onmicrosoft.com`).
  Fehlt sie: **Identität → Einstellungen → Domänennamen → Benutzerdefinierte Domäne hinzufügen**, den
  TXT-Eintrag beim DNS-Anbieter setzen, **Überprüfen**.

#### Schritt 6 - Optional: Zustimmung nur für bestimmte Konten

Nicht nötig. hocX schränkt selbst ein (nur Personen mit «Dateien importieren», nur gewählte Ordner).
«Zuweisung erforderlich» in der Unternehmensanwendung **nicht** einschalten - das erzwingt in jedem
Tenant einen Admin-Consent.

#### Schritt 7 - Herausgeberverifizierung (Partner Center)

Ohne Verifizierung können Nutzer in vielen Tenants (Richtlinie «nur verifizierte Herausgeber»,
risikobasierte Zustimmung) der App nicht zustimmen; persönliche Konten sehen eine Warnung.

1. Im **Partner Center** (<https://partner.microsoft.com>) mit einem Geschäftskonto des Betreibers
   das **Microsoft AI Cloud Partner Program** (früher MPN) beitreten: Firmenangaben, Adresse,
   Kontakt; Microsoft prüft die Firma (E-Mail-Bestätigung, ggf. Unterlagen). Kostenlos.
2. Die E-Mail-Domain des Partner-Center-Kontos muss zur **verifizierten Herausgeberdomäne** aus
   Schritt 5 passen.
3. Nach der Freigabe die **Partner One ID** (MPN-ID, Ebene «PartnerGlobal» oder «PartnerLocation»)
   notieren.
4. In der App-Registrierung → **Branding & Eigenschaften** → **Herausgeberverifizierung** →
   **MPN-ID zum Überprüfen des Herausgebers hinzufügen** → ID eintragen → **Überprüfen und speichern**.
   Die ausführende Person braucht MFA, die Rolle Anwendungsadministrator im Tenant und im Partner
   Center «Kontoadministrator» oder «MPN-Administrator».
5. Ergebnis: blaues Häkchen «Verifiziert» im Consent-Dialog.

#### Schritt 8 - Einträge in `.env` (je Umgebung)

```dotenv
# Microsoft (Entra-App aus den Schritten 1-3)
CLOUD_IMPORT_MS_CLIENT_ID=<Anwendungs-ID>
CLOUD_IMPORT_MS_CLIENT_SECRET=<Wert des geheimen Clientschlüssels>
CLOUD_IMPORT_MS_CLIENT_SECRET_EXPIRES=<JJJJ-MM-TT>
# Optional (Standardwerte):
CLOUD_IMPORT_MS_AUTHORITY=common
CLOUD_IMPORT_MS_DOWNLOAD_MODE=auto
CLOUD_IMPORT_REDIRECT_BASE_URL=          # leer = https://TRAEFIK_DOMAIN
CLOUD_IMPORT_ENABLED=true
# CLOUD_IMPORT_TOKEN_KEY erzeugt deploy.sh selbst - nicht eintragen
```

Danach `scripts/deploy.sh`. Das Client-Secret landet als Secret-Datei nur bei backend und job-worker
(`docker-compose.release.yml`).

`CLOUD_IMPORT_MS_DOWNLOAD_MODE`: `auto` lädt bis 31.3.2027 über die vorauthentifizierte URL
(«tempauth») und schickt das Token bei einer Ablehnung bzw. ab dem 1.4.2027 immer an SharePoint mit
(Microsoft schafft tempauth für OneDrive for Business/SharePoint ab). `bearer` erzwingt das sofort,
`tempauth` nie (nur zur Fehlersuche).

#### Schritt 9 - Netz (ausgehend)

backend und job-worker brauchen HTTPS (443) zu: `login.microsoftonline.com`, `graph.microsoft.com`,
`*.sharepoint.com`, `*.1drv.com` (z. B. `public.dm.files.1drv.com`), `*.livefilestore.com`. hocX
verbindet sich zu keinem anderen Host (Allowlist im Code).

#### Schritt 10 - Abnahme mit echten Konten

1. Privates Konto (outlook.com/hotmail.com): Import aus «OneDrive» und «Für mich freigegeben».
2. Geschäftskonto eines Test-Tenants mit Standard-Consent-Richtlinie: erwarteter Hinweis «Freigabe
   durch die IT nötig» → im Wizard Domain eingeben → Admin-Consent-Link als Tenant-Admin öffnen →
   Rückkehr mit «Freigabe erteilt» → erneut anmelden.
3. SharePoint-Bibliothek: im Baum «SharePoint» aufklappen → zweite Zustimmung (`Sites.Read.All`) →
   Bibliothek wählen → importieren.
4. Prüfung **Cloud-Import** in /admin/system grün, Ablaufdatum des Secrets sichtbar.
5. Verbindung trennen bzw. Import beenden → in Entra unter **Unternehmensanwendungen** des Test-Tenants
   bleibt die App (Zustimmung); Tokens sind in hocX gelöscht.

#### Zugriff entziehen (für Vereine)

- Privat: <https://account.live.com/consent/Manage> → hocX Datei-Import → Entfernen.
- Geschäftlich: <https://myapps.microsoft.com> → App → Berechtigungen widerrufen, bzw. die IT entfernt
  die Unternehmensanwendung.

### 27.2 Google (Drive, Google Fotos)

**Ziel:** ein Google-Cloud-Projekt mit OAuth-Client vom Typ «Webanwendung», nur die Scopes
`drive.file` (Google Drive, nur im Picker gewählte Dateien) und `photospicker.mediaitems.readonly`
(Google Fotos über die Photos Picker API), ein Browser-API-Key für den Google Picker. **Kein**
`drive.readonly` (Entscheid E-3 a) - damit entfällt die jährliche Sicherheitsprüfung (CASA). Ganze
Ordner importieren Vereine über Google Takeout (ZIP).

**Empfehlung zu Umgebungen:** Produktion bekommt ein **eigenes** Projekt. Test-Host und hocx-dev teilen
sich ein zweites Projekt, das im Status «Testen» bleibt (nur eingetragene Testnutzer, keine
Verifizierung nötig).

#### Voraussetzungen

1. Ein Google-Konto des Betreibers mit 2-Faktor-Anmeldung (am besten ein eigenes Betreiberkonto bzw.
   Google Workspace des Betreibers, nicht ein privates Konto einer Person).
2. Für Produktion: die Betreiber-Domain (Website) in der **Google Search Console** als Inhaber bestätigt
   (<https://search.google.com/search-console>, DNS-TXT-Eintrag). Google prüft bei der Verifizierung,
   dass Startseite und Datenschutzerklärung auf dieser Domain liegen.
3. Die Datenschutzerklärung der Plattform enthält einen Abschnitt zu Google-Daten: welche Daten hocX
   liest (nur gewählte Dateien/Fotos, Kontokennung), wozu (einmaliger Import), wie lange (Tokens bis
   Importende, widerrufen) und den Satz zur Einhaltung der «Google API Services User Data Policy,
   including the Limited Use requirements». Ohne diesen Abschnitt lehnt Google die Verifizierung ab.

#### Schritt 1 - Projekt anlegen

1. <https://console.cloud.google.com> → oben **Projekt auswählen** → **Neues Projekt**.
2. Name z. B. `hocX Datei-Import Produktion` (bzw. `… Test`), Organisation/Ordner nach Bedarf → **Erstellen**.
3. Im Dashboard unter **Projektinfo** die **Projektnummer** (nur Ziffern) notieren - das ist
   `CLOUD_IMPORT_GOOGLE_APP_ID`. (Nicht die Projekt-ID mit Buchstaben.)

#### Schritt 2 - APIs aktivieren

**APIs und Dienste → Bibliothek**, jeweils suchen und **Aktivieren**:

- **Google Drive API**
- **Google Picker API**
- **Photos Picker API** (nur für Google Fotos)

Keine weiteren APIs (insbesondere nicht die «Photos Library API»).

#### Schritt 3 - Zustimmungsbildschirm (Google Auth Platform)

**APIs und Dienste → OAuth-Zustimmungsbildschirm** (heisst inzwischen **Google Auth Platform**):

1. **Branding:** App-Name `hocX`, Support-E-Mail des Betreibers, optional Logo (ein Logo löst eine
   zusätzliche Prüfung aus), **Startseite**, **Datenschutzerklärung** und **Nutzungsbedingungen** der
   Plattform (alle auf der bestätigten Domain), **Autorisierte Domains**: die Betreiber-Domain und die
   Domain von `TRAEFIK_DOMAIN` (ohne Subdomain, z. B. `hocx.ch`), Entwickler-Kontakt-E-Mail.
2. **Zielgruppe:** Nutzertyp **Extern**. Veröffentlichungsstatus zuerst **Testen**. Unter
   **Testnutzer** die Google-Konten eintragen, die vor der Verifizierung testen dürfen (höchstens 100).
3. **Datenzugriff → Bereiche hinzufügen oder entfernen:** genau diese vier eintragen (unten «Bereiche
   manuell hinzufügen», je eine Zeile):
   ```
   openid
   https://www.googleapis.com/auth/userinfo.email
   https://www.googleapis.com/auth/drive.file
   https://www.googleapis.com/auth/photospicker.mediaitems.readonly
   ```
   `drive.file` und die beiden Anmelde-Scopes stuft Google als **nicht sensibel** ein. Zeigt die
   Konsole `photospicker.mediaitems.readonly` als **sensibel** an, braucht die Veröffentlichung für
   Google Fotos die Verifizierung sensibler Scopes (Schritt 7, ohne CASA). Nichts weiter hinzufügen.

#### Schritt 4 - OAuth-Client (Webanwendung)

1. **Google Auth Platform → Clients → Client erstellen**, Anwendungstyp **Webanwendung**, Name z. B.
   `hocX Produktion`.
2. **Autorisierte JavaScript-Quellen:** leer lassen (hocX holt die Tokens serverseitig).
3. **Autorisierte Weiterleitungs-URIs** - je Umgebung beide (zentrale Domain, keine Vereinsdomain):
   ```
   https://<TRAEFIK_DOMAIN>/api/cloud-import/oauth/google_drive/callback
   https://<TRAEFIK_DOMAIN>/api/cloud-import/oauth/google_photos/callback
   ```
   Beispiel Test-Host und hocx-dev im gemeinsamen Testprojekt: je zwei URIs mit der jeweiligen Domain.
4. **Erstellen** → **Client-ID** und **Clientschlüssel** sofort kopieren (der Schlüssel wird nur jetzt
   vollständig angezeigt). Google-Clientschlüssel laufen nicht von selbst ab; wer einen neuen anlegt
   (Rotation), trägt ihn ein, deployt und löscht danach den alten in der Konsole.

#### Schritt 5 - API-Key für den Google Picker

Der Picker läuft im Browser und braucht einen öffentlichen API-Key. Er ist kein Geheimnis, muss aber
eingeschränkt werden, damit niemand ihn auf fremden Seiten oder für andere APIs nutzt.

1. **APIs und Dienste → Anmeldedaten → Anmeldedaten erstellen → API-Schlüssel**.
2. Schlüssel bearbeiten, Name `hocX Picker`.
3. **Anwendungseinschränkungen:** **Websites** (HTTP-Verweis-URLs), je Umgebung:
   ```
   https://<TRAEFIK_DOMAIN>/*
   https://*.<TRAEFIK_DOMAIN>/*
   ```
   plus jede **eigene App-Domain** eines Vereins (`https://intern.verein.ch/*`), die den Import nutzt -
   sonst lehnt Google den Picker auf dieser Domain ab.
4. **API-Einschränkungen:** **Schlüssel einschränken** → nur **Google Picker API** → **Speichern**.
5. Den Schlüssel als `CLOUD_IMPORT_GOOGLE_API_KEY` notieren.

#### Schritt 6 - Testmodus (Dev und Test-Host)

- Im Status **Testen** funktionieren nur die eingetragenen Testnutzer; Google zeigt einen Hinweis «App
  nicht überprüft», den man mit **Weiter** bestätigt.
- Autorisierungen im Testmodus verfallen nach **7 Tagen**. Ein Import, der länger läuft, wartet dann auf
  eine neue Anmeldung (hocX schickt eine Mail, «Neu anmelden» im Assistenten setzt fort).
- Das Testprojekt bleibt dauerhaft im Testmodus; nur das Produktionsprojekt wird veröffentlicht.

#### Schritt 7 - Veröffentlichen und Basis-Verifizierung (Produktion)

1. **Google Auth Platform → Zielgruppe → App veröffentlichen** («In Produktion»).
2. Für die nicht sensiblen Scopes verlangt Google eine **Markenverifizierung** (Branding): Domain in der
   Search Console bestätigt, Startseite erklärt hocX und verlinkt die Datenschutzerklärung, App-Name und
   Logo passen zur Startseite. Unter **Branding → Überprüfungsstatus** die Prüfung anstossen; Dauer
   meist wenige Werktage. Rückfragen kommen per E-Mail an den Entwickler-Kontakt.
3. Falls `photospicker.mediaitems.readonly` als sensibel gilt: in **Datenzugriff** je Scope begründen
   («Vereine übernehmen von der Person ausgewählte Fotos einmalig in ihre Vereinsablage»), ein kurzes
   Demo-Video (nicht gelistet auf YouTube: Anmeldung, Zustimmungsdialog mit sichtbarer Client-ID,
   Auswahl in Google Fotos, Import in hocX) verlinken. Keine Sicherheitsprüfung durch ein Labor (CASA
   gilt nur für eingeschränkte Scopes wie `drive.readonly`).
4. Bis die Verifizierung durch ist, sehen Nutzer den Warnhinweis und es gilt die Grenze von 100 neuen
   Nutzern; der Import funktioniert trotzdem.

#### Schritt 8 - Einträge in `.env` (je Umgebung)

```
# Google (Projekt aus den Schritten 1-5)
CLOUD_IMPORT_GOOGLE_CLIENT_ID=<Client-ID>.apps.googleusercontent.com
CLOUD_IMPORT_GOOGLE_CLIENT_SECRET=<Clientschlüssel>
CLOUD_IMPORT_GOOGLE_API_KEY=<API-Schlüssel aus Schritt 5>
CLOUD_IMPORT_GOOGLE_APP_ID=<Projektnummer aus Schritt 1>
# Optional: nur setzen, wenn der Schlüssel ablaufen soll (Monitoring warnt 30 Tage vorher)
# CLOUD_IMPORT_GOOGLE_CLIENT_SECRET_EXPIRES=JJJJ-MM-TT
```

- Google Drive erscheint nur mit allen vier Werten (ohne API-Key/App-ID kein Picker). Google Fotos
  braucht nur Client-ID und Clientschlüssel.
- `scripts/deploy.sh` prüft die Werte (Client-ID nur mit Secret, API-Key und App-ID nur gemeinsam) und
  legt das Secret als Datei für backend und job-worker ab (`cloud_import_google_client_secret`).
- `CLOUD_IMPORT_TOKEN_KEY` erzeugt deploy.sh selbst - nicht eintragen.

#### Schritt 9 - Netz (ausgehend)

- backend und job-worker: `oauth2.googleapis.com`, `www.googleapis.com`, `docs.google.com` (grosse
  Exporte), `photospicker.googleapis.com`, `lh*.googleusercontent.com` und Umleitungen auf
  `*.googleusercontent.com`. hocX verbindet sich zu keinem anderen Host (Allowlist im Code).
- Browser der Vereine: `accounts.google.com` (Anmeldung), `apis.google.com` und `docs.google.com` (nur
  auf der Picker-Seite, eigene CSP), `photos.google.com` (neues Fenster).

#### Schritt 10 - Abnahme mit echten Konten

1. Google Drive: anmelden (Testnutzer), **In Google Drive auswählen** → je ein Google-Dokument, eine
   Tabelle, eine Präsentation, ein JPG und ein PDF wählen → Import. Erwartet: `.docx`, `.xlsx`, `.pptx`,
   Bild in der Galerie, PDF in den Dokumenten.
2. Ein Google-Dokument mit vielen Bildern (Export > 10 MB) wählen: Import über die Exportlinks oder
   «zu gross» im Bericht, kein Hängen.
3. Bei der Anmeldung das Häkchen für die Dateien abwählen: Wizard meldet «Zugriff nicht erlaubt» und
   bietet «Neu anmelden».
4. Google Fotos: **In Google Fotos auswählen** → im neuen Fenster drei Fotos und ein Video wählen →
   **Fertig** → Wizard listet von selbst auf → Import; das Video steht als «nicht unterstützt» im Bericht.
5. Picker auf einer Vereins-Subdomain und (falls vorhanden) auf einer eigenen App-Domain öffnen
   (Referrer-Einschränkung des API-Keys prüfen).
6. Nach dem Import unter <https://myaccount.google.com/connections> prüfen: hocX hat keinen Zugriff mehr
   (Token widerrufen).

#### Zugriff entziehen (für Vereine)

<https://myaccount.google.com/connections> → hocX → **Alle Verbindungen löschen**. In hocX löscht
**Verbindung trennen** den Zugang sofort und widerruft ihn bei Google.
