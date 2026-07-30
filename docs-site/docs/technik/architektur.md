# Architektur

!!! tip "Visueller Überblick"
    Für ein Diagramm aller Container/Services/Daten und ihrer Interaktionen siehe
    [Big Picture](big-picture.md). Diese Seite hier beschreibt Stack und Prinzipien in
    Textform.

## Stack

- **Backend**: FastAPI + SQLAlchemy 2.x + Python 3.13, Migrationen via Alembic
- **Frontend**: Next.js (App Router) + TypeScript, strict
- **Datenbank**: PostgreSQL 16
- **Cache/State**: Redis 7 – ausschliesslich ephemerer State für Live-Kollaboration im
  Protokoll-Editor (Presence, Feld-/Zellensperren), kein persistentes Volume
- **PDF-Export**: XeLaTeX/pdflatex per Subprozess
- **Reverse Proxy / TLS**: Traefik v3, automatische Let's-Encrypt-Zertifikate
- **Infra**: Docker Compose

## Services (Docker Compose)

| Service | Zweck |
|---|---|
| `traefik` | Reverse Proxy, TLS-Terminierung, Routing nach Host/Pfad |
| `db` | PostgreSQL, nur an `127.0.0.1` gebunden |
| `redis` | Live-Kollaborations-State |
| `backend` | FastAPI-Hauptanwendung (`/api`, `/docs`, `/openapi.json`) |
| `frontend` | Next.js-Hauptanwendung (Kunden-UI + Admin-Panel unter `/admin`) |
| `abgabebox-backend` / `abgabebox-frontend` | Öffentliche Abgabebox, eigene Codebase |
| `clamav` | Virenscan für Uploads |
| `docs` | Diese Dokumentation (statischer MkDocs-Build hinter nginx) |

## Multi-Tenancy

hocX ist Multi-Tenant: fast jede Tabelle trägt eine `tenant_id`. Ein normaler Benutzer
sieht ausschliesslich Daten der Vereine, in denen er Mitglied ist. Mandantenübergreifende
Verwaltung existiert ausschliesslich im separaten [Platform-Admin-Panel](admin-panel.md).

## Snapshot-Prinzip

Protokolle sind unveränderliche Kopien ihrer Vorlage zum Erstellungszeitpunkt.
Änderungen an einer Vorlage wirken sich nie auf bereits erstellte Protokolle aus. Eine
kontrollierte Ausnahme ist das "live bis Status *abgeschlossen*"-Muster (z. B. bei aus
Listen verknüpften Tabellenzeilen oder "Verantwortlich"-Namen): dort wird nur ein
ID-Pointer gesnapshottet, Lesen/Schreiben läuft bis zum Abschluss live über die
referenzierte Ressource, und beim Abschliessen wird der zuletzt gültige Wert
endgültig eingefroren.

## Abgabebox

Die Abgabebox ist bewusst als **eigenständige Anwendung** mit eigenem
Backend/Frontend/Compose-Service umgesetzt, nicht als Teil der Hauptanwendung:

- Eigene Subdomain, komplett unauthentifiziert erreichbar.
- Datenbankzugriff über eine **restricted Postgres-Rolle**
  (`hocx_abgabebox`): REVOKE-ALL-Baseline, danach explizites Allowlisting nur für die
  wenigen benötigten Insert-Operationen, kein `SELECT` auf sensible Spalten.
- Eigenes Storage-Verzeichnis, getrennt vom regulären Upload-Storage.
- Hochgeladene Dateien werden über ClamAV gescannt.

Diese Trennung ist die eigentliche Sicherheitsgrenze – nicht Applikationslogik –, damit
ein Fehler in der öffentlich erreichbaren Abgabebox nicht automatisch Zugriff auf die
Hauptdatenbank bedeutet.

## Platform-Admin-Panel

Siehe eigene Seite: [Platform-Admin-Panel](admin-panel.md).
