# hocX

hocX ist eine mandantenfähige Webanwendung für die Planung, Durchführung und
Dokumentation von Sitzungen. Sie verbindet Vorlagen, kollaborative Protokolle,
Aufgaben, Teilnehmende, Finanzen und Exporte in einer gemeinsamen Arbeitsumgebung.

Das Monorepo enthält zusätzlich eine öffentliche **Abgabebox** für Datei-Uploads,
eine separate Plattform-Administration und eine mit MkDocs gebaute Dokumentationsseite.

## Funktionsumfang

- Mandanten, Benutzer und mandantenspezifische Rollen
- Sitzungsplanung, Veranstaltungen und Teilnehmendenverwaltung
- konfigurierbare Protokoll- und Dokumentvorlagen
- kollaborative Protokollbearbeitung mit Autosave, Präsenz und Konfliktbehandlung
- Aufgaben, strukturierte Listen, Finanzen, Bussen und Statistiken
- Word-, PDF- und ZIP-Import sowie PDF-/Dokumentexport
- öffentliche Abgabebox mit optionalem Virenscan und CAPTCHA
- lokale Anmeldung, MFA und getrennte Plattform-Admin-Sitzungen
- vollständiger Mandantenexport und -import für Transfers und Backups
- mandantenspezifisches Branding und eigene Domains

## Technik

| Bereich | Technologie |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript |
| Backend | FastAPI, SQLAlchemy 2, Alembic |
| Daten | PostgreSQL 16, Redis, lokaler oder gemounteter Dateispeicher |
| Betrieb | Docker Compose, Traefik, optional ClamAV |
| Tests | Pytest, Vitest, Smoke- und Release-Checks |

## Repository-Struktur

```text
frontend/              Hauptanwendung und Plattform-Admin-UI
backend/               API, Geschäftslogik und Alembic-Migrationen
abgabebox-frontend/    öffentliche Upload-Oberfläche
abgabebox-backend/     eingeschränkte API der Abgabebox
docs-site/             MkDocs-Dokumentation
infra/traefik/         statische und dynamische Traefik-Konfiguration
scripts/               Entwicklung, Deployment, Backups und Verifikation
storage/               lokale Uploads, Exporte und Dokumentvorlagen
```

## Lokale Entwicklung

Voraussetzungen:

- Docker Engine
- Docker Compose v2
- freie Ports `3000`, `3001`, `8000` und `8001`

Konfiguration anlegen und den Entwicklungs-Stack starten:

```bash
cp .env.example .env
./scripts/dev.sh
```

`scripts/dev.sh` baut und startet die Container, führt die Datenbankmigrationen aus
und prüft die erreichbaren Dienste. Nach dem Start sind verfügbar:

| Dienst | Adresse |
|---|---|
| hocX | <http://localhost:3000> |
| API und OpenAPI | <http://localhost:8000> |
| Abgabebox | <http://localhost:3001> |
| Abgabebox-API | <http://localhost:8001> |

Der gleiche Stack kann ohne Wrapper gestartet werden:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Optionale Profile:

```bash
./scripts/dev.sh up --profile docs   # Dokumentation auf localhost:3002
./scripts/dev.sh up --profile scan   # ClamAV für echte Upload-Scans
./scripts/dev.sh up --profile edge   # lokaler Traefik-Edge-Stack
```

Stack anhalten oder inklusive Container und Netzwerk entfernen:

```bash
./scripts/dev.sh stop
./scripts/dev.sh down
```

## Lokale Testkonten

Eine frisch migrierte Entwicklungsdatenbank enthält folgende Mandantenkonten:

| E-Mail | Passwort | Rolle |
|---|---|---|
| `admin@hocx.local` | `ChangeMe123!` | Admin |
| `writer@hocx.local` | `ChangeMe123!` | Bearbeitung |
| `reader@hocx.local` | `ChangeMe123!` | Lesen |

Diese Zugangsdaten sind ausschließlich für die lokale Entwicklung bestimmt. Der erste
Plattform-Admin wird aus `INITIAL_ADMIN_EMAIL` und `INITIAL_ADMIN_PASSWORD` in `.env`
angelegt, solange die Plattform-Admin-Tabelle noch leer ist.

Die Demo-Daten werden nur durch den lokalen Compose-Override mit dem expliziten Alembic-
Schalter `-x seed_demo=true` angelegt. Normale Migrationen und der Release-/Produktionspfad
legen weder Demo-Mandanten noch `@hocx.local`-Konten an. Beim Upgrade älterer Installationen
deaktiviert Migration `0074_demo_account_lockout` noch vorhandene bekannte Demo-Konten.

## Konfiguration

Alle dokumentierten Variablen stehen in [`.env.example`](.env.example). Für lokale
Entwicklung funktionieren die Beispielwerte; vor einem extern erreichbaren Deployment
müssen insbesondere Passwörter, Session-Secrets, Domains, ACME-Kontakt und der auf die
DNS-Zone beschränkte Cloudflare-Token ersetzt werden.

Persistente Anwendungsdateien liegen standardmäßig in `./storage`. Mit
`HOCX_STORAGE_PATH` kann stattdessen ein Host-Pfad oder Cloud-Volume eingebunden werden,
ohne die Compose-Dateien zu ändern.

## Datenbank und Migrationen

Beim Start des Backends wird automatisch `alembic upgrade head` ausgeführt. Manuelle
Kontrolle und Migration im laufenden Entwicklungs-Stack:

```bash
docker compose -p hocx-dev exec backend alembic current
docker compose -p hocx-dev exec backend alembic upgrade head
```

Protokolle speichern Schnappschüsse ihrer Vorlagen. Spätere Änderungen an einer Vorlage
verändern daher keine bereits angelegten Protokolle oder deren Exporte.

## Tests

Der einheitliche Test-Runner baut bei Bedarf eigene Python-Test-Images. Die Python-Tests
verwenden eine flüchtige PostgreSQL-Instanz und niemals die Entwicklungsdatenbank. Der
Browserlauf startet ebenfalls einen vollständig separaten Stack unter dem Projektnamen
`hocx-e2e`, verwendet eigene Ports und löscht anschließend Datenbank-Volume sowie
E2E-Dateispeicher. Für die beiden Vitest-Befehle muss der Entwicklungs-Stack laufen:

```bash
# Gesamte Testsuite
./scripts/test.sh all

# Einzelne Bereiche
./scripts/test.sh backend
./scripts/test.sh abgabebox-backend
./scripts/test.sh frontend
./scripts/test.sh abgabebox-frontend
./scripts/test.sh e2e
```

Die Browser-Suite verwendet Playwright und prüft aktuell Anmeldung, Ablehnung falscher
Zugangsdaten, den Schutz angemeldeter Seiten, die zentrale Workspace- und
Admin-Navigation sowie das Erstellen von Todos und Terminen. Für Todo-Exporte werden
sowohl der Markdown-Inhalt als auch eine erzeugte und abrufbare PDF-Datei kontrolliert.
Zusätzlich werden vollständige Erstellen-/Ändern-/Lesen-/Löschen-Abläufe für Teilnehmer,
Listen und Einträge, Benutzer, Vorlagenkopien, Protokolle und Termine geprüft. Writer- und
Reader-Rechte sowie die Trennung zweier Mandanten werden mit getrennten Sitzungen
kontrolliert. Der Abgabebox-Test veröffentlicht einen Auftrag, lädt über die öffentliche
Oberfläche eine echte Testdatei hoch und kontrolliert den Eingang im Hauptsystem.
Temporäre Datensätze werden nach jedem Test gelöscht. Screenshots, Videos, Traces und
Dienstlogs werden bei Fehlern unter `frontend/test-results/` abgelegt.

```bash
./scripts/test.sh e2e
```

Der isolierte Stack kann zur Fehlersuche auch getrennt gesteuert werden:

```bash
./scripts/e2e.sh up
./scripts/e2e.sh test
./scripts/e2e.sh down
```

Standardmässig läuft Playwright lokal in einem passenden Browser-Container. Wenn Chromium
bereits auf dem Host installiert ist, spart `E2E_USE_HOST_PLAYWRIGHT=1 ./scripts/e2e.sh all`
mehrere Gigabyte Docker-Speicher. Die CI verwendet diese platzsparende Variante.

Einzelne Tests können weiterhin direkt gestartet werden:

```bash
docker compose -p hocx-dev exec frontend npm test -- lib/offline-store.test.ts
docker compose -p hocx-dev exec abgabebox-frontend npm test

# Status und Logs des Entwicklungs-Stacks
docker compose -p hocx-dev ps
docker compose -p hocx-dev logs --tail=100 backend frontend
```

Die CI läuft bei Pull Requests gegen `main` und bei Pushes auf `main`. Sie testet beide
Backends, beide Frontends, Datenbankmigrationen, Builds, Deployment-Skripte und die
Playwright-Browser-Suite. Bei fehlgeschlagenen Browser-Tests werden Diagnose-Artefakte
hochgeladen. Release-Kandidaten werden als signierte Images gebaut, zuerst in der
Testumgebung verifiziert und anschließend ohne erneuten Build zu unveränderten
Release-Images promotet.

## Rollen und Sicherheitsgrenzen

Anwendungsrollen gelten immer innerhalb eines Mandanten:

- `admin`: vollständige Verwaltung im ausgewählten Mandanten
- `writer`: Arbeit im Protokollbereich ohne strukturelle Administration
- `reader`: Lesezugriff und PDF-Export
- `kassier`: Lesezugriff plus Verwaltung von Finanzen und Bussen

Die Plattform-Administration unter `/admin` verwendet eigene Konten, Sitzungen und
Cookies. Im Traefik-Deployment ist sie nicht über die öffentliche Hauptdomain erreichbar,
sondern nur über einen an `127.0.0.1` gebundenen Admin-EntryPoint, der für einen privaten
OpenZiti-Zugang vorgesehen ist. Die Abgabebox besitzt ebenfalls ein separates Backend
mit eingeschränkter Datenbankrolle.

## Deployment und Betrieb

Test und Produktion verwenden gepinnte Images aus GHCR, getrennte Compose-Overlays,
Cosign-Signaturprüfung, automatische Datenbank-Backups, Smoke-Checks und einen
Digest-basierten Rollback. Die vollständigen Abläufe für Provisionierung, Candidate-Build,
Test, Promotion, Produktion, Rollback und Restore stehen im [RUNBOOK](RUNBOOK.md).

Wichtige Skripte:

| Skript | Zweck |
|---|---|
| `scripts/dev.sh` | lokalen Entwicklungs-Stack verwalten |
| `scripts/deploy.sh` | Test- oder Produktionsrelease ausrollen |
| `scripts/verify_release.sh` | Deployment und Migrationen verifizieren |
| `scripts/backup_db.sh` | PostgreSQL-Backup erstellen |
| `scripts/cleanup_storage.sh` | nicht mehr benötigte Dateien bereinigen |

Für ein öffentliches Deployment müssen die DNS-Einträge vor dem ersten Start auf den
Server zeigen, damit Traefik die Let's-Encrypt-Zertifikate ohne fehlgeschlagene
Autorisierungen beziehen kann.

## Lizenz

Copyright © 2026 hocX Project. All rights reserved.

Dieses Projekt ist proprietäre Software. Nutzung, Vervielfältigung, Veränderung oder
Weitergabe ist nur mit vorheriger schriftlicher Genehmigung des Rechteinhabers erlaubt.
Weitere Einzelheiten stehen in der [LICENSE](LICENSE). Eingebundene Komponenten von
Drittanbietern unterliegen weiterhin ihren jeweiligen Lizenzen.
