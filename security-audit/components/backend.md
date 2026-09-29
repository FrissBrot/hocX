# Komponente: backend/ (FastAPI-Hauptbackend)

## Phase 2 Fork C (Uploads/Injection/XSS) — Ergebnis

`files.py`, `word_import.py`, `gallery_upload_route.py`, `scanner.py` sowie gezielte
Injection/SSRF-Greps geprüft. Kein neues bestätigtes Finding — alle Phase-1-Verdachtsmomente
in diesem Bereich widerlegt (gallery_upload_route korrekt registriert, kein blockierender
scanner-Call auf dem Request-Pfad, Tenant-Scoping in files.py konsistent über
access_service, ZIP-Handling zip-bomb-gehärtet, Injection-Grep clean). Details/Evidence:
`security-audit/findings-draft/fork-c-uploads-xss.md`.

Status: REVIEWED_WITH_FINDINGS (0 neue Findings, mehrere Verdachtsmomente als False-Positive
verifiziert und dokumentiert)

## 1. Struktur-Überblick (`backend/app`)

```
app/
  main.py                 FastAPI-App, Middleware, CORS, globale Exception-Handler, Router-Wiring,
                          Lifespan (Startup-Seeds + 10 Background-Loops als asyncio.create_task)
  gallery_upload_route.py  eigenständige Route/Handler für Massen-Bild-Upload (separat von files.py?)
  upload_admission.py     ASGI-Middleware, admittiert/limitiert Gallery-Upload-Requests vor Auth
  scanner.py              vermutlich ClamAV-Anbindung (noch nicht gelesen)
  api/routes/             30 Routen-Module, siehe Abschnitt 4
  core/                   Auth/Security (security.py, admin_security.py, totp.py, webauthn.py),
                          DB-Session (db.py), Config (config.py), Rate-Limiting (rate_limit.py),
                          Redis-Client, zentrales Error-Logging (error_log.py), Background-Loop-
                          Skeleton (background_loops.py), Crypto-Helper (secret_crypto.py, base64url.py, cbor.py)
  models/entities.py      ein einziges großes SQLAlchemy-Models-Modul (alle Entities)
  repositories/           17 Repository-Module (DB-Zugriff pro Entity), u. a. access_repository.py
                          (zentrale Tenant/Ownership-Auflösung für transitiv gescopte Entities)
  services/                ~65 Service-Module: Business-Logik, u. a. Tenant-Verwaltung/-Clone/-Export/
                          -Import/-Trust, Storage/Quota, Uploads/Word-Import, Domains/Traefik,
                          Photo-Analyse, Finance/Fines, Collaboration, Public-Share/Submission-Links
  schemas/                Pydantic-Schemas (Request/Response), nicht einzeln inventarisiert
```

## 2. Auth-Mechanismus

- Datei: `backend/app/core/security.py`.
- Passwort-Hashing: PBKDF2-HMAC-SHA256, 600k Iterationen, eigenes Format (`hash_password`/`verify_password`),
  konstante Zeit via `hmac.compare_digest`. Es existiert extra ein `DUMMY_PASSWORD_HASH`
  (security.py:59-64), damit `verify_password` auch bei unbekannter E-Mail durchläuft — explizit
  als Fix eines früheren Timing-/Account-Enumeration-Audit-Findings kommentiert (2026-08-25).
- Session-Token: kein JWT-Standard, sondern selbstgebautes signiertes Format
  `base64url(payload).base64url(hmac_sha256(payload, auth_secret))` (`_sign_payload`,
  `create_session_token`, `parse_session_token`, Zeilen 82-138). Payload: `user_id`, `mfa`, `iat`, `exp`.
  Kein Algorithmus-Feld im Token (kein "alg"-Confusion-Vektor wie bei echtem JWT), Secret kommt aus
  `settings.auth_secret`. Cookie: `httponly`, `secure=settings.auth_secure_cookies`, `samesite=lax`.
- `get_optional_current_user` (Zeilen 182-204): liest Cookie → `parse_session_token` → lädt `AppUser`
  aus DB → prüft `is_active` → prüft `session_revoke_at` gegen Token-`iat` (Server-seitiger Revoke-
  Mechanismus, kein Redis/Blacklist nötig) → baut `CurrentUser` inkl. Rolle **aus der DB** (nicht aus
  dem Token) → erzwingt MFA für Rolle `admin`, falls Faktor vorhanden/erforderlich.
- Rolle wird **serverseitig pro Request neu aus der DB** bestimmt (`build_current_user`, Zeilen
  141-165: `Tenant`/`Role` per `user.tenant_id`/`user.role_id` aus DB, nicht aus dem Client/Token) —
  gutes Zeichen gegen "stale/client-supplied role"-Probleme.
- Rollen: `admin`, `writer`, `reader`, `kassier` (siehe `main.py:ensure_roles`, Zeilen 33-49). Kein
  globaler "superadmin" in diesem Modell — globale Admin-Funktionen laufen über ein **separates**
  System: `PlatformAdmin`-Model + `admin_auth.py`/`admin_security.py` (Platform-Admin-Panel), nicht
  über `AppUser`/`Role`. Muss getrennt auditiert werden (eigene Session-Cookies? eigenes Secret?
  eigene MFA? — noch nicht geprüft, siehe TODO).
- Zentrale Rollen-Dependencies: `require_reader`/`require_writer`/`require_admin`/`require_finance_read`/
  `require_finance_write`/`require_abgabebox_read`/`require_abgabebox_write`/`require_all_fines_read`
  (security.py:213-277) — alle nehmen ein bereits aufgelöstes `CurrentUser` (kein eigenes `Depends`,
  werden explizit in jeder Route aufgerufen: `require_writer(user)` etc.). **Das bedeutet: die
  Durchsetzung hängt davon ab, dass jede Route den richtigen `require_*`-Call tatsächlich aufruft —
  es gibt keinen FastAPI-Dependency-Zwang, der eine vergessene Rollenprüfung strukturell verhindert.**
  Wichtiger Merkposten für die Authorization-Phase (Abschnitt 8 des Audit-Auftrags).
- Feature-Gating: `require_feature(user, code)` prüft `code in user.current_tenant_features`
  (`frozenset`, deny-by-default, aus `tenant_feature`-Tabelle geladen in `build_current_user`).
  Kombiniert mit Rolle in `require_finance_read/write`, `require_abgabebox_read/write` — orthogonale
  Prüfung, beide müssen einzeln aufgerufen werden (gleiches "kein Dependency-Zwang"-Risiko wie oben).

## 3. Tenant-Handling

- `CurrentUser.current_tenant_id` kommt aus `AppUser.tenant_id` in der DB (1 User = exakt 1 Tenant,
  siehe Kommentar Zeile 35-36: "historical from when a session could switch between tenants" — kein
  Tenant-Header/-Query-Param vom Client, der vertraut werden müsste).
- **Keine zentrale Tenant-Scoping-Dependency/Middleware.** Jede Route muss `tenant_id=user.current_tenant_id`
  selbst an Service/Repository durchreichen (siehe `events.py` als Beispielmuster). Tenant-Isolation ist
  also Konvention, nicht strukturell erzwungen.
- Zentraler Lookup-Helfer für client-gelieferte UUIDs: `app/services/public_id_service.py`.
  **Wichtige Erkenntnis (potenziell hohe Priorität für Authorization/Tenant-Isolation-Phase):**
  `get_by_public_id(db, model, public_id, tenant_id=...)` filtert nur dann nach Tenant, wenn das
  Model selbst eine `tenant_id`-Spalte hat (`hasattr(model, "tenant_id")`). Für **transitiv**
  tenant-gescopte Entities (Docstring nennt explizit: `ProtocolElement`, `ProtocolElementBlock`,
  `ProtocolTodo`, `StoredFile`, ...) ist `tenant_id=` dort ein **stiller No-Op** — der Docstring
  verlangt ausdrücklich, dass Caller zusätzlich `app.repositories.access_repository`-Lookups
  (`tenant_id_for_protocol`, `protocol_id_for_block`, `tenant_id_for_stored_file`, ...) aufrufen.
  Das ist ein **systemisches Risikomuster**: jede Route, die `get_by_public_id`/`resolve_internal_id`
  für eine transitiv gescopte Entity aufruft, OHNE zusätzlich den passenden `access_repository`-Check,
  hat eine potenzielle IDOR-Lücke (fremder Tenant kann fremde `ProtocolElement`/`StoredFile`/`ProtocolTodo`
  per bekannter/erratener UUID lesen/ändern). **Muss in Phase "Tenant-Isolation" (Abschnitt 9) für JEDEN
  Aufrufer von `get_by_public_id`/`resolve_internal_id`/`resolve_internal_ids` mit einem Modell ohne
  eigene `tenant_id`-Spalte einzeln verifiziert werden.** `access_repository.py` selbst noch nicht gelesen.
- Beispielmuster (korrekt, `events.py`): Route ruft `public_id_service.get_by_public_id(db, Event, event_id,
  tenant_id=user.current_tenant_id)` — `Event` hat eigene `tenant_id`-Spalte, also wirksam gescoped.
- `EventRepository.get(db, event_id)` (ohne tenant_id) existiert als ungescopter Zugriffspfad —
  nur sicher, wenn ausschließlich intern mit bereits tenant-geprüften ids aufgerufen; alle Call-Sites
  müssen in der Authorization-Phase verifiziert werden.

## 4. Routen-Module (`backend/app/api/routes/*.py`), grob gruppiert

- **Auth (App-User):** `auth.py` (175 Zeilen)
- **Auth (Platform-Admin):** `admin_auth.py` (94 Zeilen) — separates Login/Session-System für Platform-Admins
- **Platform-Admin-Panel (global, nicht tenant-gescoped):** `admin.py` (960 Zeilen, größte Routendatei
  nach word_import/files — Tenant-Verwaltung, Domains, Error-Log, Pläne/Pricing, Storage-Pakete etc.
  vermutlich hier gebündelt; noch nicht im Detail gelesen)
- **Tenant-Selbstverwaltung:** `tenants.py`
- **User-Verwaltung (pro Tenant):** `users.py`
- **Termine/Kalender:** `events.py`
- **Protokolle:** `protocols.py`, `protocol_elements.py`, `table_snapshots.py`, `document_templates.py`,
  `templates.py`, `cycle_configs.py`, `tag_config.py`, `todos.py`
- **Kollaboration (Realtime):** `collaboration_ws.py` (WebSocket)
- **Finanzen/Bußgelder:** `finance.py`, `fines.py`
- **Teilnehmer/Listen:** `participants.py`, `lists.py`
- **Dateien/Uploads/Storage:** `files.py` (1197 Zeilen, größte Routendatei), `storage.py`,
  `word_import.py` (1160 Zeilen), `gallery_upload_route.py` (Top-Level, nicht unter routes/)
- **Freigaben/Public-Zugriff (Hauptbackend-seitig):** `share_links.py`, `public_share.py`,
  `submission_assignments.py` — Grenzfläche zur Abgabebox/öffentlichen Nutzern, hohe Priorität für
  Public-Endpoint-Audit (Abschnitt 21)
- **Statistiken/Exports:** `statistics.py`, `exports.py`

## 5. Background-Prozesse (`main.py` Lifespan, alle als `asyncio.create_task`)

10 Loops, alle über `run_advisory_locked_loop` (aus `core/background_loops.py`, noch nicht im Detail
gelesen) mit Postgres-Advisory-Lock geschützt (Multi-Worker-sicher, "every worker but advisory-locked"):

1. `domain_health_check_loop` — periodischer Health-Check aktiver Custom-Domains
2. `abgabebox_rescan_loop` — Rescan hängengebliebener Abgabebox-Uploads (ClamAV war down)
3. `upload_pipeline_rescan_loop` — dito für interne Upload-Pfade (Protokollbild/Gallery/Word-Import)
4. `export_cleanup_loop` — Alters-Cleanup generierter Export-Dateien
5. `log_cleanup_loop` — Retention-Cleanup für `audit_log`/`system_error_log`
6. `cycle_snapshot_loop` — tägliche Zyklus-Snapshot-Erstellung
7. `photo_analysis_auto_queue_loop` — Auto-Queue für Foto-Qualitätsanalyse, nur in Low-Traffic-Fenster
   + bei niedriger Host-Last (`_host_load_is_low`, `os.getloadavg()`)
8. `photo_quality_backfill_loop` — Nachträgliche Schärfe/Belichtung-Scores
9. `photo_album_sync_loop` — Abgabebox-Uploads in Alben einsortieren
10. `gallery_upload_ingest_loop` — Queue-Worker für Massen-Bild-Upload (Scan/Thumbnail/StoredFile),
    alle 5s

Kommentare verweisen bereits auf zwei frühere Audit-Fixes in diesem Bereich: fehlendes
`to_thread`/Exception-Isolation in `photo_analysis_auto_queue_loop` (2026-09-17) und ein Lock-ID-
Copy-Paste-Bug in `cycle_snapshot_loop` (2026-09-10, ein Loop hat den anderen "ausgehungert").
Diese Loops sind laut CLAUDE.md außerhalb des HTTP-Zyklus — jeder `except Exception`, der nicht
re-raised, braucht eigenes `record_system_error(...)`. Muss pro Loop/`background_loops.py` selbst
verifiziert werden (TODO).

Zusätzlich beim Start: `ensure_no_production_demo_data()` (Zeilen 75-107) — Fail-Closed-Guard, der den
Start in Produktion blockiert, falls bekannte Demo-Accounts/-Tenants existieren. Guter Fail-Closed-Fund,
aber Liste ist hart codiert (`demo_emails`, `demo_tenants`) — falls neue Demo-Daten anders benannt
würden, greift der Guard nicht (kein Finding, nur Beobachtung).

## 6. WebSockets (`collaboration_ws.py`)

- Eigene Token-Auth-Funktion `_authenticate(token)` (Zeilen 52-75): parst denselben Session-Token wie
  HTTP, baut `CurrentUser`, spiegelt exakt dieselbe MFA-Erzwingung wie `get_optional_current_user`
  (Kommentar verweist auf einen Audit-Fix 2026-08-25, der eine Lücke schloss: Session ohne aktiven
  MFA-Faktor durfte vollen WS-Zugriff behalten). Wo genau der Token für die WS-Verbindung herkommt
  (Query-Param? Subprotocol? Cookie?) noch nicht gelesen (`protocol_collaboration`-Funktionssignatur
  nimmt nur `websocket`, `protocol_id` — Token-Extraktion muss im Funktionskörper liegen, TODO).
- Tenant-Scoping: `_load_and_authorize` nutzt `public_id_service.resolve_internal_id(db, Protocol,
  protocol_public_id, tenant_id=user.current_tenant_id)` — korrekt gescoped, da `Protocol` eine
  eigene `tenant_id`-Spalte hat.
- Origin-Check: `_origin_allowed`/`_static_allowed_origins`/`_active_app_domain_origins` — eigene
  Origin-Allowlist-Logik inkl. Custom-Domains aus DB; Kommentar erwähnt einen bereits behobenen Bug
  (Custom-Domain-Origin wurde fälschlich abgelehnt, siehe Git-Log "Custom-Domain-Origin ... fixen").
  Muss in der Auth-Phase auf Bypass-Möglichkeiten geprüft werden (z. B. `null`-Origin, fehlender
  Origin-Header, Subdomain-Wildcard-Fehler).
- Fehlerbehandlung: `_record_ws_error` ruft explizit `record_system_error(..., source="backend")` —
  korrekt gemäß CLAUDE.md-Konvention für Code außerhalb des HTTP-Zyklus.

## 7. Migrationen

- 41 Alembic-Migrationsdateien (`backend/alembic/versions`, `0000`–`0096`, nicht lückenlos
  durchnummeriert — Namensmuster suggeriert Batches). Neueste (0083–0096) betreffen: Photo-Capture-
  Event-Link, Tenant-Feature-Flags, Plan-Pricing, Custom-Domain-Enforcement, Storage-Pakete,
  Storage-Quota-Entfernung ("remove_manual_storage_quota" — interessant für Storage/Quota-Phase, TODO:
  prüfen ob Downgrade-Pfad/Zwischenzustand sauber ist), Plan-Catalog-Details, Abgabebox-Quota-Grant,
  Custom-Domain-Description, Upload-Capacity, Share-Link, Photo-Album-Tenant-Share, Tenant-Trust,
  Album-Item-Share-Pending. Migrationen mit Berechtigungs-/Tenant-Bezug (`tenant_feature`,
  `custom_domain_enforcement`, `tenant_trust`, `photo_album_tenant_share`) sind Kandidaten für
  Migrations-Audit (Abschnitt 19: unsichere Defaults, fehlende Constraints, Fail-Open).

## 8. Tests (`backend/tests`)

- 110 Python-Testdateien insgesamt (inkl. `tests/fixtures`). Noch keine inhaltliche Sichtung, welche
  Bereiche abgedeckt sind (TODO für Testabdeckungs-Analyse/`TEST_RECOMMENDATIONS.md`, Abschnitt 26).

## 9. Auffälligkeiten für Vertiefung (Merkposten, KEINE bestätigten Findings)

- **Hohe Priorität:** `public_id_service.get_by_public_id`/`resolve_internal_id`/`resolve_internal_ids`
  für Modelle ohne eigene `tenant_id`-Spalte (`ProtocolElement`, `ProtocolElementBlock`, `ProtocolTodo`,
  `StoredFile`, ggf. weitere) sind stille No-Ops bzgl. Tenant-Filter — jede Route, die so ein Modell
  auflöst, muss zusätzlich einen `access_repository`-Check haben. Jeden Call-Site systematisch prüfen.
- Rollen-/Feature-Checks (`require_writer`, `require_admin`, `require_feature`, ...) sind reine
  Funktionsaufrufe ohne FastAPI-`Depends`-Zwang — eine neue/geänderte Route kann den Aufruf vergessen,
  ohne dass Type-Checker/Router das verhindern. Für jede Route in Abschnitt 4 in der Authorization-
  Phase verifizieren, dass die *richtige* `require_*`-Funktion tatsächlich aufgerufen wird (nicht nur
  irgendeine).
- `admin.py` (960 Zeilen) und `admin_auth.py`/`admin_security.py` — separates Platform-Admin-System,
  noch komplett ungeprüft (eigenes Session-/Cookie-Schema? Eigene Rate-Limits? Trennung zu
  Tenant-Auth wasserdicht?).
- `files.py` (1197) und `word_import.py` (1160) — größte Routendateien, Upload-/Parser-Pfade,
  hohe Priorität für Abschnitt 14 (File Uploads) und 12 (Injection/Parser-Exploits).
- `gallery_upload_route.py` liegt außerhalb von `api/routes/` und wird in `main.py` gar nicht über
  `app.include_router(...)` sichtbar eingebunden (nicht in der Router-Liste in main.py:446-472) —
  klären, wie/wo diese Route tatsächlich registriert wird (evtl. in `files.router` inkludiert, oder
  über `UploadAdmissionMiddleware`-Pfad `/api/files/gallery-uploads` separat verdrahtet). TODO.
- `EventRepository.get(db, event_id)` und vermutlich analoge `.get(id)`-Methoden in anderen
  Repositories ohne `tenant_id`-Parameter — für jede Repository-Datei prüfen, ob ungescopte Getter
  existieren und ob sie ausschließlich mit bereits geprüften internen ids aufgerufen werden.
- `ensure_no_production_demo_data()` — hart codierte Demo-Identitäten-Liste, kein generisches Muster.
- Migration `0088_remove_manual_storage_quota` — prüfen, ob während/nach dieser Migration ein
  Zwischenzustand existierte, in dem Quota-Enforcement fehlte oder inkonsistent war.
- `_static_allowed_origins`/`_active_app_domain_origins` (collaboration_ws.py) — eigene Origin-
  Allowlist-Logik für WebSocket-CORS-Äquivalent, auf Bypässe prüfen (Abschnitt 7, CORS).
- CORS in `main.py:393-403`: `allow_headers` enthält `"Authorization"`, obwohl der einzige erkennbare
  Auth-Mechanismus ein Cookie ist (kein sichtbarer `Authorization`-Header-Verbrauch in `security.py`)
  — evtl. totes/unnötiges Header-Allow, kein Bug per se, aber in Auth-Phase verifizieren, ob
  irgendwo doch ein Bearer-Token-Pfad existiert, der separat geprüft werden muss.

Status: REVIEWED_WITH_FINDINGS (Tenant-Isolation vertieft, siehe findings-draft/fork-a-tenant-isolation.md — 2x LOW/INFO, Kernhypothese I3 widerlegt/entwarnt)

## Phase 3 Fork H — Auth-Kernaudit (Abschnitt 7)

`auth.py`, `core/security.py`, `core/rate_limit.py`, `mfa_service.py`, `domain_bridge_service.py`,
Session-Revocation-Pfade in `user_service.py` vollständig gelesen. **Kein neues Finding.**
Redis-backed, account-scoped Lockouts (15 Min. Fenster) zusätzlich zu Traefik-IP-Limits;
host-only Session-Cookie (kein `domain=`); Rolle wird bei jedem Request frisch aus der DB
geladen (kein Token-Claim, Rollenänderung braucht daher keine Revocation); MFA-Faktor-Löschung
bei Admins erzwingt automatisch Reauth beim nächsten Request (`_requires_mfa` + `has_mfa_factor`-
Check in `get_optional_current_user`); Passwort-Reset-Flow existiert bewusst nicht (dokumentierte
Design-Entscheidung, keine Mail-Infrastruktur); `/bridge`-Token ist single-use/60s-TTL/256-Bit,
theoretisches Login-CSRF-Muster nur als INFO vermerkt (kein Datenzugriff-Impact). Details in
`findings-draft/fork-h-auth-core.md`. Damit auch die in Abschnitt "Auffälligkeiten" oben offene
CORS-`Authorization`-Header-Frage indirekt bestätigt (kein Bearer-Token-Consumer in `security.py`
gefunden) — deckt sich mit Fork E's Befund (toter CORS-Header-Eintrag, kein Fund).

Status: REVIEWED_WITH_FINDINGS (unverändert — Fork H fügt keine neuen Findings hinzu, nur
Abschnitt 7 vollständig als geprüft bestätigt)

Fork B (Authorization/Platform-Admin, Abschnitt 8) abgeschlossen, siehe
`findings-draft/fork-b-authz-admin.md` — 0 neue bestätigte Findings. `admin.py`/
`admin_security.py`/`admin_auth.py` vollständig gelesen: router-weiter `Depends(get_current_admin)`
+ konsistente `require_admin_write`/`require_admin_owner` auf jeder Mutation/jedem PII-Read,
MFA-Erzwingung ohne Fallback verifiziert. `tenants.py`/`users.py` vollständig gelesen, Guards
teils im Service-Layer (`user_service.py`, `tenant_service.py`, `mfa_service.py`) statt in der
Route selbst, aber überall inkl. Tenant-Match vorhanden (verifiziert, nicht nur vermutet). Noch
nicht einzeln zeilenweise gelesen (nur automatisiert auf fehlende Guards gescannt, keine Anomalie
gefunden): `events.py`, `finance.py`, `fines.py`, `participants.py`, `lists.py`, `statistics.py`,
`templates.py`, `document_templates.py`, `cycle_configs.py`, `tag_config.py`, `todos.py`,
`table_snapshots.py`, `protocol_elements.py`, `share_links.py`, `public_share.py`,
`submission_assignments.py`, `collaboration_ws.py` — `finance.py`/`fines.py` (Geld) und die
Public-Boundary-Dateien (`share_links.py`/`public_share.py`/`submission_assignments.py`) haben
Priorität für eine weitere manuelle Vertiefungsrunde in Phase 3/4.

Fork G (Finanzen/Bußgelder, Abschnitte 8+20) abgeschlossen, siehe
`findings-draft/fork-g-finance.md` — 0 neue Findings. `finance.py` (10 Routen), `fines.py`
(7 Routen), `finance_repository.py`, `fines_repository.py` vollständig gelesen: Rollen-Guards
(`require_finance_read/write`, `require_all_fines_read`) konsistent und passend zur
Sensitivität, `kassier`-Rolle sauber von `writer` getrennt (kein Escalation-Pfad), alle 4
State-ändernden Fine-Operationen (`create_fine` via Protocol-Row-Lock, `delete_fine`/
`collect_fine`/`reopen_fine` via eigenes Row-Lock) race-frei verifiziert, Cross-Tenant-Check
via `protocol.tenant_id`/`FinanceAccount.tenant_id` überall vorhanden und liefert
ununterscheidbare 404s (kein Enumerations-Orakel), Geldbeträge durchgängig `Decimal`/
`Numeric(15,2)`, `PositiveFineAmount` (`gt=0`) für Bußgelder korrekt vs. vorzeichenoffene
Transaktionsbeträge. Bestätigt mehrere frühere Audit-Fixes (2026-08-12/08-16/08-25) als
weiterhin korrekt, keine Regression.

Fork F (Public Endpoints, Abschnitt 21) abgeschlossen, siehe
`findings-draft/fork-f-public-endpoints.md` — 1x INFO (PUB-01, ClamAV-Versionsstring ohne
Tenant-Bezug sichtbar, kein Handlungsbedarf), sonst 0 Findings. `share_links.py`,
`public_share.py`, `share_link_service.py`, `submission_assignments.py` vollständig gelesen:
Share-Link-Token 192 Bit (`secrets.token_urlsafe(24)`), Expiry/Revocation serverseitig bei
JEDEM Zugriff geprüft, ununterscheidbare 404s (kein Enumerations-Orakel), App-seitiges
Rate-Limiting auf allen 4 öffentlichen Routen, kein IDOR über `file_id`/`upload_id` (Datei muss
nachweislich zum aufgelösten Link/Upload gehören, danach zusätzlicher Tenant-Check auf
`assignment.tenant_id`), keine Möglichkeit einen Share-Link auf fremde Tenant-Ressourcen zu
erzeugen. `submission_assignments.py` ist NICHT öffentlich (jede Route verlangt
`get_current_user` + `require_abgabebox_read/write`) — die echte öffentliche Grenzfläche liegt
vollständig in `abgabebox-backend` (bereits in Phase 1/Fork D geprüft).

Status: REVIEWED_WITH_FINDINGS (kumulativ über Forks A/B/F/G — 1x MEDIUM woanders [BG-01,
photo-analysis-worker], 2x LOW/INFO [TEN-01/02], 1x INFO [PUB-01]; Finance/Fines,
Platform-Admin und Public-Endpoints ohne Findings mit Sicherheitsimpact). Noch offen für
Phase 3/4: `statistics.py`/`exports.py` (Cross-Tenant-Export-Regression), Auth-Kernaudit
(`auth.py`, CSRF, Rate-Limiting-Vollständigkeit), LaTeX-Escaping im PDF-Export,
`participant_service.py:137`, `ProtocolImage`/`ProtocolText`-Callsites ausserhalb `files.py`.

Fork I (Phase 3: Export-Regression + restliche Tenant-Isolation-Callsites) abgeschlossen, siehe
`findings-draft/fork-i-export-tenant-leftovers.md` — 0 neue Findings. Alle 7 historischen
Cross-Tenant-Export-Fixes in `export_service.py` (2026-08-25) verifiziert intakt;
`statistics.py`/`exports.py` sauber tenant-/rollen-gescoped; LaTeX-Escaping robust (kein
Injection-Vektor über Rich-Text-Inhalt); `participant_service.py:137` korrekt abgesichert;
`ProtocolImage`/`ProtocolText`/`ProtocolDisplaySnapshot` haben ausserhalb `files.py` keinen
direkten Client-Resolve-Pfad (nur bereits tenant-verifizierte interne Joins/Tenant-Admin-Ops).

Fork J (Phase 4: Feature-Gating, Abschnitt 10) abgeschlossen, siehe
`findings-draft/fork-j-feature-gating.md` — **2 neue CONFIRMED MEDIUM-Findings**: FEAT-01
(aktive Custom-Domains bleiben nach Feature-Entzug via `update_tenant_features` unbegrenzt
funktional weiter geroutet — `traefik_config_service.regenerate()`/`domain_health_check_service`
prüfen nur `status='active'`, nie `tenant_feature`) und FEAT-02 (Tenant-Import stellt aktive,
verifizierte Custom-Domains 1:1 wieder her, ohne dass der neue Tenant `custom_domain` je gebucht
hat — `tenant_import_service.py` referenziert `TenantFeature` an keiner Stelle;
`tenant_clone_service.py` dagegen unbetroffen, kopiert keine `TenantDomain`-Zeilen). Nur 3
Feature-Codes existieren system­weit (`finance`, `abgabebox`, `custom_domain`); `finance`/
`abgabebox` selbst ohne Bypass gefunden (Cross-Ref Fork F/G). Verwandter, nicht abschliessend
verifizierter Verdacht: ob nach `abgabebox`-Feature-Entzug bestehende Submission-Assignments
über den alten Link-Token weiter abrufbar bleiben (gleiches Muster) — für Nachfolge-Check
vorgemerkt.

Status: REVIEWED_WITH_FINDINGS (kumulativ: 1x MEDIUM woanders [BG-01], 2x MEDIUM hier [FEAT-01/02],
2x LOW/INFO [TEN-01/02], 2x INFO [PUB-01 + WS-01]).
