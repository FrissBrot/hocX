# SECURITY_MODEL

Rekonstruiert aus Code (nicht aus Dokumentation), Stand nach Phase 1.

## Actors

- **Unauthenticated user** — kennt höchstens einen öffentlichen Link (`share/[token]`,
  Abgabebox-`linkToken`).
- **Abgabebox-Uploader** — hat einen `submission_link.token`, keine Identität, kein Account.
  Kann Captcha-Session-Token zusätzlich besitzen.
- **Tenant-User** — eingeloggt via `backend`-Session-Cookie, Rolle `reader`/`writer`/`kassier`/
  `admin` **innerhalb genau eines Tenants** (1 User = 1 Tenant, kein Tenant-Wechsel pro Session).
- **Tenant-Admin** (Rolle `admin` in `Role`-Tabelle) — höchste Rolle *innerhalb* eines Tenants,
  MFA-Pflicht (falls Faktor vorhanden/erforderlich).
- **Platform-Admin** — komplett getrenntes Auth-System (`PlatformAdmin`-Model,
  `admin_auth.py`/`admin_security.py`), eigenes Session-Cookie/Secret (`ADMIN_AUTH_SECRET`),
  eigene Domain (`admin.<TRAEFIK_ADMIN_DOMAIN>`, nur über `adminsecure`-Entrypoint/OpenZiti
  erreichbar laut Traefik-Config). Kein "Superadmin" über Tenant-Rollen erreichbar.
- **Background-Worker** — `backend`-Lifespan-Tasks (10 Loops, volle `hocx_app`-DB-Rolle),
  `photo-analysis-worker` (separater Prozess, restricted `hocx_photo_worker`-Rolle, kein
  Netzwerk), `abgabebox-backend`-Quarantäne-Loop (restricted `hocx_abgabebox`-Rolle).
- **Interner Service** — `abgabebox-backend`/`photo-analysis-worker` sprechen dieselbe
  Postgres-Instanz mit jeweils eigener, spaltenweise eingeschränkter DB-Rolle an
  (kein Schema-weiter Zugriff — Defense-in-Depth gegen kompromittierten Container).

## Assets

- Tenant-Daten (Teilnehmende, Termine, Protokolle, Todos, Listen, Finanzen/Bußgelder)
- Dateien (`StoredFile`, Fotos, Dokumentvorlagen, Exporte/PDFs)
- Abgabebox-Uploads (von Dritten ohne Account eingereicht)
- Zugangsdaten (Passwort-Hashes, Session-Secrets, TOTP-Seeds/WebAuthn-Credentials)
- Tokens (Session-Token, Public-Share-Token, Submission-Link-Token, Captcha-Session-Token,
  Invite/Reset-Tokens — genaue Fundstellen: Phase 2)
- Custom-Domains (Tenant-eigene Domains, Traefik-Dynamic-Config)
- Storage-Kontingent/Pläne/Pricing (Business-Logic-Asset: Umgehung = finanzieller Schaden)
- `system_error_log` (kann selbst sensible Stack-Traces/Kontext enthalten — global, nicht
  tenant-gescoped, siehe Vertiefungskandidat zu `admin-error-log.tsx`)
- Signierte Deploy-Artefakte (Cosign-Identität, `deploy-code.manifest`)

## Trust Boundaries

```
Browser (Tenant-User)     → frontend (Next.js SSR)      → backend (FastAPI)      → Postgres (hocx_app)
Browser (Platform-Admin)  → frontend /admin (Next.js)   → backend (FastAPI, separates Admin-Auth) → Postgres
Browser (anonym)          → abgabebox-frontend (Next.js)→ abgabebox-backend      → Postgres (hocx_abgabebox, restricted)
backend Background-Loops (10x, in-process)                                       → Postgres (hocx_app)
photo-analysis-worker (separater Container, kein Netzwerk)                       → Postgres (hocx_photo_worker, restricted)
                                                                                  → gemeinsamer Storage-Mount (nur lesen/schreiben face_quality_score-Pfad)
Traefik (TLS-Terminierung, Rate-Limits, Routing)  → alle obigen Services
CI (GitHub Actions) → GHCR (Images, Cosign-signiert) → deploy.sh auf Host → Docker Compose
```

Wichtig: **Kein zentrales API-Gateway, das Tenant-Scoping erzwingt.** Tenant-Isolation ist
Konvention in jeder Route/jedem Service (`tenant_id=user.current_tenant_id` muss manuell
durchgereicht werden), nicht strukturell durch Middleware/Dependency erzwungen. Ebenso keine
FastAPI-`Depends`-Kette für Rollen-/Feature-Checks — `require_writer(user)` etc. sind normale
Funktionsaufrufe, die eine Route vergessen kann, ohne dass das auffällt.

## Security-Invarianten (Hypothesen aus Code, Verifikation läuft in Phase 2/3)

| # | Invariante | Wo durchgesetzt (Stand Phase 1) | Bekannte Schwachstelle im Mechanismus selbst |
|---|---|---|---|
| I1 | Rolle wird serverseitig neu aus DB bestimmt, nie aus Client/Token übernommen | `build_current_user` (`security.py:141-165`) | keine bekannt |
| I2 | Tenant-Isolation bei Modellen mit eigener `tenant_id`-Spalte | `public_id_service.get_by_public_id(..., tenant_id=...)` | wirksam NUR wenn Modell `tenant_id`-Spalte hat |
| I3 | Tenant-Isolation bei transitiv gescopten Modellen (`ProtocolElement`, `StoredFile`, `ProtocolTodo`, ...) | soll über `access_repository.py`-Checks erfolgen | **stiller No-Op in `get_by_public_id`, wenn Caller den zusätzlichen Check vergisst** — Kernrisiko, Phase 2 |
| I4 | Rollen-/Feature-Gate pro Route | `require_writer`/`require_admin`/`require_feature(...)`-Aufruf in der Route | kein struktureller Zwang, jede Route kann den Aufruf vergessen |
| I5 | Platform-Admin getrennt von Tenant-Rollen | separates Model/Auth-System, eigener Traefik-Entrypoint (`adminsecure`) | Detailprüfung `admin.py`/`admin_security.py` steht aus |
| I6 | Abgabebox: Tenant-Scoping über Link-Token | jede Query in `abgabebox-backend/repository.py` filtert nach `tenant_id` aus aufgelöstem Link | kein Bypass gefunden (Phase 1) |
| I7 | Storage-Quota race-frei | 2 verschachtelte Advisory-Locks (`serialized_upload`, `tenant_upload_lock`) | Verschachtelung selbst noch nicht auf TOCTOU verifiziert (Phase 2) |
| I8 | Background-Fehler landen in `system_error_log` | `record_system_error`/`insert_error_log` mit festem `source` | **mind. 1 bekannte Lücke: `photo-analysis-worker` ruft kein Äquivalent auf** |
| I9 | CAPTCHA fail-closed in Produktion | `captcha_enabled()`-Gate, laut Kommentaren mehrfach bereits gefixt | Bypass-Bedingung bei fehlendem Sitekey noch nicht erneut verifiziert (Phase 2) |
| I10 | Public-Token sind nicht erratbar | `secrets.token_urlsafe(24)` für Submission-Link | rechnerisch stark; Rate-Limiting/Lockout liegt extern in Traefik-Labels, nicht im App-Code selbst |
| I11 | Client-Feature-Flags/-Rollen sind nie alleinige Entscheidungsgrundlage | Frontend prüft nur `authenticated`, Backend prüft Rolle/Feature erneut | gilt strukturell nur, wenn I4 für JEDE Route hält — siehe I4 |

## Bereits bekannte, laut Code/CHANGELOG behobene historische Findings (nicht neu "entdecken")

Siehe `STATE.md`, Abschnitt "KRITISCHE ERKENNTNIS" für die vollständige Liste mit
Fundstellen (Cross-Tenant-PDF-Export, fehlendes Row-Lock bei `collect_fine`, CAPTCHA
fail-open, Storage-Quota-Race, Admin-Auth-Timing-Seitenkanal, MFA-Lockout-Schutz, u. a.).
Diese Muster dienen als Suchvorlage für strukturell ähnliche, aber noch nicht gefixte Stellen.
