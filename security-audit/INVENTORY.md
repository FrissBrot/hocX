# INVENTORY

Quelle: Phase-1-Inventar-Forks, siehe Details in `components/*.md`. Diese Datei ist die
verdichtete Übersicht mit Review-Status pro Bereich.

## Komponenten

| Komponente | Beschreibung | Status |
|---|---|---|
| `backend/` | FastAPI-Hauptbackend: ~30 Routenmodule, ~65 Services, 17 Repositories, Auth/Security, 10 Background-Loops, WebSocket-Kollaboration | REVIEWED (Inventar) |
| `abgabebox-backend/` | Eigenständiges FastAPI-Backend für öffentliche Uploads, restricted DB-Rolle `hocx_abgabebox` | REVIEWED (Inventar) |
| `photo-analysis-worker/` | Eigenständiger Polling-Worker (Gesichtsqualität), restricted DB-Rolle `hocx_photo_worker`, kein Netzwerk zur Laufzeit | REVIEWED (Inventar) |
| `frontend/` | Next.js Hauptapp (pro Tenant) + Plattform-Admin (`/admin`) | REVIEWED (Inventar) |
| `abgabebox-frontend/` | Next.js, rein öffentlich, token-basiertes Routing, kein eigenes Auth | REVIEWED (Inventar) |
| Deployment/Infra/Scripts/CI | `docker-compose*.yml`, `infra/`, `scripts/`, `.github/workflows/` | REVIEWED (Inventar) |
| `design/` | Design-Tokens/-Regeln | NOT_STARTED (kein Security-Scope erwartet, nur Blick auf CSP-relevante Inline-Styles falls XSS-Pass das verlangt) |
| `docs-site/` | MkDocs/nginx, öffentlich, nicht sensibel | NOT_STARTED (niedrige Priorität) |
| `.audit-1.1/` | Früherer Code-Review-/Design-Konsistenz-Pass (KEIN Security-Audit) | NICHT IM SCOPE (nur Referenz) |

## Backend (`backend/app`) — Detailstruktur

- **Auth/Security**: `core/security.py` (Session-Token, Passwort-Hashing, Rollen-Dependencies),
  `core/admin_security.py`/`api/routes/admin_auth.py` (separates Platform-Admin-System),
  `core/totp.py`, `core/webauthn.py`
- **Tenant-/Ownership-Auflösung**: `services/public_id_service.py` (zentral, aber No-Op für
  Modelle ohne eigene `tenant_id`-Spalte), `repositories/access_repository.py` (noch nicht
  gelesen — Phase 2)
- **Routen** (30 Module): Auth, Platform-Admin (`admin.py`, 960 Zeilen), Tenants, Users, Events,
  Protokolle (`protocols.py`, `protocol_elements.py`, `table_snapshots.py`, `document_templates.py`,
  `templates.py`, `cycle_configs.py`, `tag_config.py`, `todos.py`), Collaboration-WS, Finance/Fines,
  Participants/Lists, Files/Storage/Word-Import/Gallery-Upload, Public-Share/Submission-Assignments,
  Statistics/Exports
- **Background-Loops** (10, alle advisory-locked): Domain-Health, Abgabebox-Rescan, Upload-Pipeline-
  Rescan, Export-Cleanup, Log-Cleanup, Cycle-Snapshot, Photo-Analysis-Auto-Queue, Photo-Quality-
  Backfill, Photo-Album-Sync, Gallery-Upload-Ingest
- **Migrationen**: 41 Alembic-Dateien (`0000`–`0096`), neueste betreffen Tenant-Features, Plan-
  Pricing, Custom-Domain-Enforcement, Storage-Pakete/-Quota
- **Tests**: 110 Python-Testdateien (Abdeckung noch nicht inhaltlich bewertet)

## abgabebox-backend — Detailstruktur

- Ein Routenmodul (`routes/public.py`, 5 Endpunkte), Upload-Pipeline mit Magic-Number-Check,
  ClamAV, 2 Advisory-Locks (Quota-Race-Schutz), Quarantäne-Cleanup-Loop, eigenes Captcha-System.
- 14 Testdateien, viele als Regressionstests für frühere Audit-Findings erkennbar.

## photo-analysis-worker — Detailstruktur

- Kein HTTP/WS, reiner DB-Polling-Loop. Fehlerbehandlung erreicht `system_error_log` nicht
  (Kandidat für Finding). Tenant-Scoping von `fetch_files` hängt vollständig vom Backend-Aufrufer ab.

## frontend — Detailstruktur

- Kein gemeinsames Auth-Layout: jede `page.tsx` ruft `requireSession()`/`requireAdminSession()`
  selbst auf. `proxy.ts` prüft nur `authenticated`, keine Rolle/Tenant. Kaum XSS-Fläche
  (2 harmlose `dangerouslySetInnerHTML`, 0 `.innerHTML`), aber `rich-text-editor.tsx` ungeprüft.
- Platform-Admin-Bereich (`app/admin/**`) mit eigenem Login/Session, `admin-error-log.tsx`.

## abgabebox-frontend — Detailstruktur

- Rein token-basiertes Routing, keine eigene Autorisierungsentscheidung, kein XSS-Fund.

## Deployment/Infra/Scripts/CI — Detailstruktur

- Release-Compose bereits stark gehärtet (`read_only`, `cap_drop:ALL`, `secrets:`-Dateien,
  Cosign-Signaturen für Images UND Deploy-Code). `deploy.sh` (749 Zeilen) mit Preflight-Checks.
  CI: `secret-scan.yml` (Gitleaks), `build-test-images.yml` (Cosign), `release.yml`
  (Environment-Schutz), `ci.yml` (8 Jobs, kein `permissions:`-Block).

## Automatisch generiert / Third-Party (Audit-Zeit sparen)

- `frontend/node_modules`, `**/coverage`, `**/test-results`, `**/playwright-report`,
  `frontend/tsconfig.tsbuildinfo` — generiert, nicht auditieren.
- `photo-analysis-worker`-ONNX-Modell (per SHA-256 gepinnt) — Third-Party-Binärdatei, nicht
  Quellcode-auditierbar, Pinning selbst ist der relevante Kontrollpunkt (bereits geprüft).

## Offene Inventar-Lücken (vor Abschluss zu schliessen)

- `infra/traefik/traefik.yml`, `infra/traefik/dynamic/`, `infra/clamav/clamd.conf` — nur
  referenziert, nicht inhaltlich gelesen.
- `scripts/lib/*.sh`, `scripts/backup_db.sh`, `scripts/cleanup_storage.sh`,
  `scripts/verify_release.sh`, `scripts/record_tested_candidate.sh` — nicht gelesen.
- `backend/app/repositories/access_repository.py` — zentral für Tenant-Isolation, noch nicht
  gelesen (höchste Priorität Phase 2).
- `backend/app/api/routes/admin.py` (960 Zeilen), `core/admin_security.py` — Platform-Admin-
  System komplett ungeprüft.
- `frontend/components/ui/rich-text-editor.tsx` — Stored-XSS-Kandidat.
- `backend/app/services/file_service.py` — Job-Erzeugung für photo-analysis-worker (Tenant-Scoping).
- `backend/app/core/background_loops.py` — Fehlerketten-Verifikation aller 10 Loops.
