# Komponente: frontend/ (Next.js Hauptapp + Plattform-Admin)

## Phase 2 Fork C (Uploads/Injection/XSS) — Ergebnis

`rich-text-editor.tsx` vollständig geprüft: Tiptap/ProseMirror mit reduziertem Schema +
`Markdown.configure({ html: false })` — kein Stored-XSS-Vektor gefunden (Verdacht aus Phase 1
widerlegt). Details: `security-audit/findings-draft/fork-c-uploads-xss.md` (Finding C-06).

Status: REVIEWED_WITH_FINDINGS (0 neue Findings, XSS-Verdacht als False-Positive verifiziert)

Files reviewed: frontend/proxy.ts, frontend/lib/api/{server,client,admin-server}.ts,
frontend/components/ui/app-shell.tsx (Auszug), frontend/app/layout.tsx, Verzeichnisstruktur
`frontend/app`, Verzeichnisstruktur `frontend/e2e`.

## 1. Struktur-Überblick (`frontend/app`, Next.js App Router)

- Haupt-App (pro Tenant, unter Login): `cycles`, `elements`, `events`, `files`, `finances`,
  `fines`, `lists`, `participants`, `photos`, `protocols` (+ `protocols/[id]`),
  `shared-links`, `statistics`, `submission-assignments`, `templates` (+ `[id]`), `todos`,
  `tools/import` (+ `[id]`), `tools/word-import`, `users`, `settings`,
  `tenant-settings` (+ `abo`, `domains`), `page.tsx` (Dashboard `/`).
- Plattform-Admin (eigener Auth-Realm): `admin/` mit `admins`, `domains`, `error-logs`,
  `login`, `plans`, `security`, `sso`, `tenants`, `upload-pipeline`, `users`, `admin/page.tsx`.
- Öffentlich/Auth: `login/`, `share/[token]` (öffentlicher Freigabe-Link, kein Login).
- `app/api/` existiert als Verzeichnis, ist aber **leer** — keine Next.js Route Handlers;
  alle Backend-Calls gehen direkt an das separate FastAPI-Backend (`INTERNAL_API_URL` /
  `NEXT_PUBLIC_API_URL`).
- `__list-preview/` — nicht inhaltlich geprüft, vermutlich Vorschau-/Debug-Feature (in
  Attack-Surface-Phase klären ob produktiv erreichbar).

## 2. Auth im Frontend

- **Kein zentrales `middleware.ts`** mehr — umbenannt zu **`proxy.ts`** (Next.js
  Middleware-Konvention), Grund laut Kommentar: Vermeidung eines Login-Redirect-Loops durch
  Next.js Router-Cache. `proxy.ts` prüft bei praktisch jedem Request (Matcher schließt nur
  `api/`, `_next/static`, `_next/image`, `favicon.ico`, `robots.txt`, `sitemap.xml` aus) via
  Server-seitigem Fetch gegen `/api/auth/session` bzw. `/api/admin/auth/session`
  (unterschieden nach `pathname.startsWith("/admin")`, nach Rewrite für `TRAEFIK_ADMIN_DOMAIN`)
  nur das Flag `authenticated`. Bei `false` → Redirect zu `/login` bzw. `/admin/login`. Bei
  `null` (Backend nicht sicher erreichbar) wird **nicht** umgeleitet, sondern die Seite normal
  gerendert — die tiefere Prüfung passiert dann serverseitig in der Page selbst.
- **Serverseitige Page-Guards**: `requireSession()` (`lib/api/server.ts`) und
  `requireAdminSession()` (`lib/api/admin-server.ts`) rufen jeweils `/api/auth/session` bzw.
  `/api/admin/auth/session` mit dem weitergereichten Cookie auf und werfen bei
  Backend-Unerreichbarkeit einen Error (→ `error.tsx`-Boundary, kein Redirect), bei
  `authenticated === false` einen `redirect()`. **Kein gemeinsames Layout** übernimmt das
  automatisch — jede einzelne `page.tsx` unter einer geschützten Route ruft
  `requireSession()`/`requireAdminSession()` selbst auf (siehe Liste unten). Das ist die
  eigentliche Auth-Prüfung; `proxy.ts` ist nur Defense-in-Depth gegen den Redirect-Loop.
- **Nur `authenticated`, keine Rolle/Tenant** wird von `proxy.ts` geprüft. Rollen-/
  Tenant-Autorisierung (z. B. "ist dieser User Tenant-Admin", "gehört diese Resource zum
  aktuellen Tenant") passiert ausschließlich in den Backend-API-Calls, die die jeweilige
  Page dann lädt — im Frontend selbst nicht sichtbar geprüft. **Verdachtsmoment (nicht
  bestätigt)**: ob wirklich JEDE Seite unter `frontend/app/*` `requireSession()`/
  `requireAdminSession()` aufruft, wurde nur per `grep` auf Aufrufer verifiziert (Liste
  unten deckt alle sichtbaren geschützten Verzeichnisse ab, keine fehlt offensichtlich) —
  aber ob eine neu hinzukommende Page das vergisst, ist strukturell nicht erzwungen (kein
  gemeinsames `layout.tsx` mit Guard). Für Vertiefung vormerken.
- Session-Cookie selbst wird nicht im Frontend geparst/validiert, nur transparent
  weitergereicht (`cookieHeader()` in `server.ts`, `credentials: "include"` im Client-Fetch).
  Erzeugung/Validierung liegt vollständig im Backend (`backend/app/core/security.py`,
  siehe dort `issue_session_cookie`/`parse_session_token` — Teil des Backend-Audits).

Aufrufer von `requireSession()`/`requireAdminSession()` (grep, `frontend/app/**/page.tsx`):
admin/{admins,domains,error-logs,page,plans,security,sso,tenants,upload-pipeline,users},
cycles, elements, events, files, finances, fines, lists, page (Dashboard), participants,
photos, protocols (+ `[id]`), settings, shared-links, statistics, submission-assignments,
templates (+ `[id]`), tenant-settings (+ abo, domains), todos, tools/import (+ `[id]`),
tools/word-import, users. Nicht in der Liste (erwartungsgemäß öffentlich): `login`,
`admin/login`, `share/[token]`.

## 3. API-Client

- `frontend/lib/api/client.ts`: zwei getrennte Pfade.
  - `backendFetch()` — **serverseitig** (Server Components), Ziel `INTERNAL_API_URL` (internes
    Docker-Netz), reicht Cookie manuell über `headers` durch (`backendFetchWithSession()` in
    `server.ts`). Bei Nicht-OK-Response → `null` (kein Werfen), Aufrufer muss das behandeln.
  - `browserApiFetch()`/`browserApiUpload()` — **clientseitig**, immer relative Pfade
    (`publicApiUrl = ""`), `credentials: "include"` sorgt dafür, dass das Cookie
    same-origin (Hauptdomain oder Tenant-Custom-Domain) automatisch mitgeschickt wird, ohne
    dass der Client Domain/Tenant selbst bestimmen muss. Timeout 15s, ein Retry bei echtem
    Netzwerkfehler.
  - Fehler-Mapping (`errorFromResponse`) übersetzt HTTP-Status in `ApiError.kind`
    (`auth` bei 401/403, `conflict` bei 409, `backend` bei 5xx, sonst `validation`) —
    zeigt, dass Frontend-Code HTTP-Fehler grundsätzlich einzeln behandeln muss, nicht
    automatisch "vertraut".
  - Bewusst **nicht** mit `abgabebox-frontend/lib/api.ts` geteilt (Kommentar referenziert
    "audit finding E-Niedrig-4" — vermutlich aus einem früheren, nicht in diesem Verzeichnis
    dokumentierten Audit; für Vertiefung: dieses Finding wiederfinden/verifizieren, ob es in
    diesem Audit erneut auftaucht).
- Kein zentraler API-Client mit automatischem Tenant-Header — Tenant-Kontext wird serverseitig
  aus der Session (Cookie) abgeleitet, nicht clientseitig als Parameter mitgeschickt (gute
  Voraussetzung gegen simples Tenant-Spoofing über einen Header/Body-Parameter — im
  Backend-Audit verifizieren, dass wirklich nirgends ein `tenant_id` aus dem Request-Body
  ungeprüft übernommen wird).

## 4. Platform-Admin-Bereich

- Routen: `frontend/app/admin/**` (siehe oben), eigene Login-Seite `admin/login`, eigene
  Session-Route `/api/admin/auth/session`, eigener Guard `requireAdminSession()`.
- `admin-error-log.tsx` (`frontend/components/admin/admin-error-log.tsx`) ist die UI für
  `system_error_log` (siehe CLAUDE.md-Abschnitt "Zentrale Fehlererfassung") — verwendet unter
  `app/admin/error-logs/page.tsx`; enthält vermutlich `SOURCE_LABELS` (laut CLAUDE.md) — Inhalt
  noch nicht gelesen, für Auth/Authz-Pass vormerken (dort nur Anzeige, keine Aktionen erwartet).
  Gehört zum Backend-Fehlererfassungs-Kettenmechanismus, nicht primär ein Frontend-Security-Topic.
- Kein separates gemeinsames Layout mit Rollenprüfung — jede `admin/*/page.tsx` ruft
  `requireAdminSession()` selbst auf (s. Liste oben). Ob `requireAdminSession()` selbst
  zwischen "globaler Admin" und ggf. abgestuften Admin-Rollen unterscheidet, ist
  Backend-Thema (`AdminSessionInfo`/`AdminSelfRead` in `backend/app/schemas/admin.py`) —
  noch nicht geprüft.
- Domain-Trennung: `TRAEFIK_ADMIN_DOMAIN` lässt `admin.<domain>` das komplette Admin-Panel an
  der Wurzel servieren (Pfad-Rewrite in `proxy.ts`, siehe Kommentar "audit finding,
  2026-09-02" — wieder ein Verweis auf einen früheren, hier nicht vorliegenden Audit-Fund;
  für Vertiefung: prüfen ob dieser referenzierte Fund vollständig behoben ist oder Reste hat).

## 5. XSS-relevante Stellen

- `dangerouslySetInnerHTML`: **nur 2 Treffer**, beide in `frontend/app/layout.tsx`
  (Zeilen 43 und 49): (a) `window.__HOCX_CONFIG__` — JSON aus rein serverseitigen Env-Werten
  (`TRAEFIK_DOMAIN`, `HOCX_VERSION`), kein User-Input, `<` wird escaped; (b) Theme-Init-Script
  (liest nur `localStorage`, kein dynamischer String aus User-/Server-Daten). Kein
  offensichtliches Stored/Reflected-XSS-Einfallstor über `dangerouslySetInnerHTML`.
- `.innerHTML`: **0 Treffer** in `frontend/` (außerhalb `node_modules`).
- `rich-text-editor.tsx` (`frontend/components/ui/rich-text-editor.tsx`) — Rich-Text-Eingabe
  (vermutlich für Protokolle/Todos), **noch nicht gelesen**. Rich-Text-Editoren sind ein
  klassischer Stored-XSS-Kandidat (HTML-Persistierung + spätere Anzeige ohne Sanitizing) —
  hohe Priorität für den XSS-Vertiefungs-Pass: prüfen, wie der Inhalt gespeichert
  (HTML? Markdown? strukturiertes JSON?) und wie er beim Anzeigen wieder gerendert wird
  (eigenes `dangerouslySetInnerHTML` würde grep oben zeigen — falls das Rendering stattdessen
  über eine dedizierte Editor-Bibliothek läuft, die selbst `dangerouslySetInnerHTML` intern
  nutzt, taucht das hier nicht auf; Bibliothek identifizieren und deren Sanitizing prüfen).
- Nutzer-Dateinamen/-Freitexte werden vermutlich an vielen Stellen als React-Kinder gerendert
  (React escaped automatisch) — kein Hinweis auf Ausnahmen gefunden, aber nicht systematisch
  für jede Komponente verifiziert (zu groß für Inventar-Phase).

## 6. Custom-Domain-Handling

- Kein eigenständiges Custom-Domain-Handling im Haupt-Frontend-Code selbst (kein
  `customDomain`/`custom_domain`-Treffer in Komponenten) — laut Grep nur relevant in:
  - `frontend/components/settings/tenant-domains-manager.tsx` (Tenant-Settings-UI zum
    Verwalten eigener Domains — CRUD-UI, Logik/Validierung vermutlich backend-seitig).
  - `frontend/e2e/feature-gating.spec.ts` (Test erwähnt es im Kontext von Feature-Gating,
    nicht Domain-Handling selbst).
- Die eigentliche Custom-Domain-Logik (Origin-Handling, Cross-Domain-Session-Bridge laut
  Git-Log "Protokoll-Kollaboration: Custom-Domain-Origin ... fixen") liegt im **Backend**
  (`backend/app/api/routes/auth.py::bridge`, `backend/app/services/traefik_config_service.py`)
  und in `proxy.ts`/`app-shell.tsx` (`redirectToLogin` nutzt `getRuntimeConfig().mainAppDomain`
  zur Entscheidung, ob auf die Hauptdomain umgeleitet werden muss). Vertiefung gehört primär
  zum Backend-Pass (WebSocket/Collaboration-Komponente laut CLAUDE.md
  `collaboration_ws.py`), Frontend-Seite ist hier nur Konsument.

## 7. Tests

- `frontend/e2e/*.spec.ts` (Playwright, 15 Dateien): u. a.
  `roles-and-tenants.spec.ts` (Rollen/Mandanten — direkt Security-relevant),
  `feature-gating.spec.ts` (Feature-Enforcement — direkt Security-relevant),
  `admin-mfa-lockout.spec.ts` (Auth/Brute-Force — direkt Security-relevant),
  `storage-quota.spec.ts` + `storage-packages.spec.ts` + `storage-usage-consistency.spec.ts`
  (Quota/Storage-Limits — relevant für Race-Condition-Pass),
  `abgabe-links.spec.ts` + `abgabebox-photo-album-sync.spec.ts` (Public-Link-Handling —
  relevant für Public-Endpoint-Pass), Rest (`create-and-export`, `entity-lifecycle`,
  `gallery-upload-cycle-target`, `navigation`, `rich-text-editor`, `word-import*`) eher
  funktional. Diese Tests sind vielversprechende Fundstellen, um bestehende
  Security-Invarianten aus dem Code zu rekonstruieren (Abschnitt "Security Model") — in
  Vertiefungsphase lesen statt raten.
- Vitest (`frontend/vitest.config.ts`, `frontend/lib/api/client.test.ts`,
  `frontend/app/uuid-references.test.tsx`) — `uuid-references.test.tsx` klingt nach einem
  Test, der prüft, dass UUIDs nicht versehentlich als vertrauenswürdig behandelt werden;
  Inhalt noch nicht gelesen, für Tenant-Isolation-Pass vormerken.

## 8. Auffälligkeiten für Vertiefung (Stichpunkte, keine Findings)

- Kein gemeinsames Auth-Layout — jede Page ruft ihren Guard selbst auf; strukturell nicht
  erzwungen, dass eine neue Page das nicht vergisst. Für Authorization-Pass: stichprobenartig
  neuere/kleinere Pages prüfen (z. B. `shared-links`, `submission-assignments`,
  `tools/import/[id]`).
- `proxy.ts` prüft nur `authenticated`, nicht Rolle/Tenant — vollständige Autorisierung liegt
  beim Backend; im Authorization-Pass verifizieren, dass wirklich jeder Datenendpunkt, den
  diese Pages aufrufen, serverseitig Rolle/Tenant prüft (nicht nur "eingeloggt").
  Kommentar-Referenz auf frühere "audit finding"s (E-Niedrig-4, 2026-09-02) — prüfen, ob
  diese aus `.audit-1.1/` stammen oder aus einem nicht mehr vorliegenden Audit, und ob sie
  wirklich vollständig behoben sind.
- `rich-text-editor.tsx` — welche Bibliothek, wie wird der Inhalt persistiert/gerendert
  (Stored-XSS-Kandidat, hohe Priorität).
- `admin.<domain>`-Rewrite in `proxy.ts` (Pfad- statt reiner Hostname-Routing-Historie) —
  verifizieren, dass kein Pfad mehr existiert, der Admin-UI unter der Kunden-Domain zeigt
  oder umgekehrt Kunden-Daten unter der Admin-Domain.
- `frontend/app/__list-preview` — Zweck unklar, prüfen ob produktiv erreichbar und ob es
  eigene Auth-Prüfung hat.
- `admin-error-log.tsx`/`SOURCE_LABELS` — verifizieren, dass die Anzeige keine sensiblen
  Rohdaten aus anderen Tenants leakt (Error-Log ist global, nicht tenant-gescoped).
