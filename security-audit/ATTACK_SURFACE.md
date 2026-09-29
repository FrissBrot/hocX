# ATTACK_SURFACE

Stand: nach Phase 1 (Inventar). Vollständige Endpoint-Tabelle (Method/Route/Auth/Role/Tenant/
Feature/Input/Resource) wird modulweise in Phase 2 befüllt, sobald die jeweilige Routendatei
im Detail gelesen wird — hier zunächst der Überblick nach Modul mit Trust-Level.

## abgabebox-backend (vollständig, `routes/public.py`) — komplett öffentlich, hostile environment

| Method | Route | Auth | Tenant-Scoping | Bemerkung |
|---|---|---|---|---|
| GET | `/api/public/{link_token}/assignments` | Link-Token (Format+DB) | über Link → Tenant | 404 bei unbekanntem Token |
| GET | `/api/public/{link_token}/assignments/{slug}` | Link-Token | über Link+Slug | 404/403 (Feature) getrennt |
| GET | `/api/public/{link_token}/assignments/{slug}/elements` | Link-Token | über Link+Slug | |
| POST | `/{link_token}/assignments/{slug}/elements/{ref}/captcha-verify` | Link-Token | über Link+Slug | FriendlyCaptcha → Session-Token |
| POST | `/{link_token}/assignments/{slug}/elements/{ref}/upload` | Link-Token + Captcha-Session-Token | über Link+Slug | Upload-Pipeline, siehe `components/abgabebox-backend.md` |
| GET | `/api/health` | keiner | n/a | kein DB-Zugriff |

## backend/app/api/routes — nach Modul, Detail-Tabelle folgt in Phase 2

| Modul | Trust-Level | Rollen/Feature (Hypothese, Phase 1) | Review-Status |
|---|---|---|---|
| `auth.py` | unauthenticated → authenticated | Login/Logout/Session | NEEDS_REVIEW (Detail) |
| `admin_auth.py` | unauthenticated → Platform-Admin | separates Auth-System | NEEDS_REVIEW (Detail) |
| `admin.py` (960 Zeilen) | Platform-Admin only | globale Verwaltung (Tenants, Domains, Error-Log, Pläne, Storage-Pakete) | NEEDS_REVIEW (noch nicht gelesen — hohe Priorität) |
| `tenants.py`, `users.py` | Tenant-User | Rolle admin für User-Verwaltung (Hypothese) | NEEDS_REVIEW |
| `events.py` | Tenant-User | `require_writer`/`require_reader` (Hypothese) | NEEDS_REVIEW |
| `protocols.py`, `protocol_elements.py`, `table_snapshots.py`, `document_templates.py`, `templates.py`, `cycle_configs.py`, `tag_config.py`, `todos.py` | Tenant-User | gemischt, transitiv tenant-gescopte Entities (I3-Risiko) | NEEDS_REVIEW (hohe Priorität wegen I3) |
| `collaboration_ws.py` | Tenant-User (WS) | eigener Origin-Check + Session-Token | NEEDS_REVIEW (Origin-Bypass) |
| `finance.py`, `fines.py` | Tenant-User | `require_finance_read/write`, `require_all_fines_read` | NEEDS_REVIEW |
| `participants.py`, `lists.py` | Tenant-User | gemischt | NEEDS_REVIEW |
| `files.py` (1197 Zeilen), `storage.py`, `word_import.py` (1160 Zeilen), `gallery_upload_route.py` | Tenant-User (Upload) | Upload/Parser-Pfade, hohe Priorität (Sections 12/14) | NEEDS_REVIEW (hohe Priorität) |
| `share_links.py`, `public_share.py`, `submission_assignments.py` | siehe Detailtabelle unten | Grenzfläche zu Abgabebox | REVIEWED (Fork F, `findings-draft/fork-f-public-endpoints.md`) |
| `statistics.py`, `exports.py` | Tenant-User | Cross-Tenant-Leak-Historie (Section "bereits gefunden": PDF-Export) | NEEDS_REVIEW (Regression prüfen) |

## frontend — Seiten (kein eigenständiger Angriffsvektor, aber Autorisierungs-Konsistenz prüfen)

Alle Seiten unter `app/*` (ausser `login`, `admin/login`, `share/[token]`) rufen
`requireSession()`/`requireAdminSession()` — siehe `components/frontend.md` für vollständige
Liste. `app/__list-preview` noch ungeklärt (Zweck/Erreichbarkeit).

## Öffentliche/unauthentifizierte Einstiegspunkte (Gesamtübersicht, hohe Priorität)

1. `abgabebox-frontend` + `abgabebox-backend` — vollständig öffentlich (siehe oben).
2. `frontend/app/share/[token]` + `backend/app/api/routes/share_links.py`/`public_share.py` —
   noch nicht im Detail geprüft (Phase 2, hohe Priorität).
3. `backend/app/api/routes/auth.py` — Login/Passwort-Reset/Invite (falls vorhanden) — Phase 2.
4. `admin_auth.py` — Platform-Admin-Login — Phase 2.
5. `GET /api/health` (beide Backends) — kein Secret-Leak erwartet, kurz gegenprüfen.

## share_links.py / public_share.py / submission_assignments.py — Detailtabelle (Fork F)

`share_links.py` und `submission_assignments.py` sind **authentifiziert** (Tenant-User,
`get_current_user` + Rollen-Guard); nur `public_share.py` ist echt unauthentifiziert (Token IST
die Auth). `submission_assignments.py` verwaltet die Abgabebox-Integration serverseitig, ist
selbst keine Public-Grenze.

| Method | Route | Auth | Role | Tenant | Feature | Input | Resource |
|---|---|---|---|---|---|---|---|
| POST | `/share-links` | Session-Cookie | `require_writer` | eigener (album/file_ids geprüft) | — | name, file_ids\|album_id, expires_at | `ShareLink` |
| GET | `/share-links` | Session-Cookie | `require_writer` | eigener | — | — | `ShareLink[]` |
| DELETE | `/share-links/{id}` | Session-Cookie | `require_writer` | eigener (`link.tenant_id`-Check) | — | — | `ShareLink` |
| GET | `/public/share/{token}` | **Token = Auth** | — | über Token | — | `token` | Freigegebene Dateiliste (Metadaten) |
| GET | `/public/share/{token}/files/{file_id}/thumbnail` | Token + Mitgliedschaft in Link | — | über Token | — | `token`, `file_id` | Thumbnail (nur `scan_status=clean`) |
| GET | `/public/share/{token}/files/{file_id}/download` | Token + Mitgliedschaft in Link | — | über Token | — | `token`, `file_id` | Datei-Download |
| GET | `/public/share/{token}/download` | Token | — | über Token | — | `token` | Alle Dateien (Einzel oder ZIP) |
| GET/POST/PATCH/DELETE | `/submission-links*`, `/submission-assignments*` | Session-Cookie | `require_abgabebox_read/write` | eigener | `abgabebox` (implizit über Rolle/Route) | diverse | `SubmissionLink`/`SubmissionAssignment` |
| GET | `/submission-uploads/{upload_id}/files/{file_id}/{content\|thumbnail\|metadata}` | Session-Cookie | `require_abgabebox_read` | eigener (nachgelagerter `assignment.tenant_id`-Check) | — | `upload_id`, `file_id` | `StoredFile` (Abgabebox-Upload) |
| PATCH | `/submission-uploads/{upload_id}/files/{file_id}/tags` | Session-Cookie | `require_abgabebox_write` | eigener (dito) | — | `upload_id`, `file_id`, tags | `StoredFile.tags` |
| GET | `/clamav/status` | Session-Cookie | `require_abgabebox_read` | **keiner** (geteilte Infra, siehe PUB-01) | — | — | ClamAV-Status/-Version |
| GET | `/submission-assignments/{id}/download-zip` | Session-Cookie | `require_abgabebox_read` | eigener | — | `assignment_id` | ZIP aller sauberen Uploads |

## Noch zu befüllen (Phase 2, pro Modul)

Vollständige `| Method | Route | Auth | Role | Tenant | Feature | Input | Resource |`-Tabellen
für jedes NEEDS_REVIEW-Modul oben, sobald die jeweilige Datei im Detail gelesen wird.
