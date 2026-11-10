# Deployment / Infra / Scripts / CI — Inventar

Status: **REVIEWED_WITH_FINDINGS** (Phase 1 Inventar + Phase 2 Vertiefung abgeschlossen, siehe unten)

Scope dieser Datei: nur Deployment/Infra/Scripts/CI, NICHT die Backend-/Frontend-
Anwendungslogik (separate Audits). `.env` (echte Werte) wurde nicht gelesen — nur
`.env.prod.example` (Struktur/Variablennamen).

## 1. Container-Topologie

Zwei parallele Compose-Layer:

- **Dev/lokal**: `docker-compose.yml` (Basis, dev-getunte Werte, `backend`/`abgabebox-backend`
  laufen mit `--reload` als root `user: "0:0"`) + `docker-compose.dev.yml` (Overrides: Ports
  auf `127.0.0.1`, `AUTH_SECURE_COOKIES=false`, `TRAEFIK_DOMAIN=""`, Traefik/ClamAV/Docs hinter
  `profiles`).
- **Test/Prod (echtes Deployment via `deploy.sh`)**: `docker-compose.release.yml` (Basis) +
  `docker-compose.clamav.yml` + `docker-compose.traefik.yml` (+ `docker-compose.test.yml`,
  aktuell leer, nur für Test-Host). **`docker-compose.yml` (dev) wird bei echten Deployments
  NIE eingebunden** — mehrfach in Kommentaren als historische Fehlerquelle dokumentiert
  (Hardening fehlte zuerst in den Release-Pendants).

Services: `traefik`, `db` (Postgres 16), `redis`, `backend` (FastAPI Haupt-App),
`photo-analysis-worker` (Polling-Worker, kein HTTP, Phase-3-Gesichtsqualitäts-Scoring),
`frontend` (Next.js Haupt-App + Plattform-Admin unter `/admin`), `abgabebox-backend`
(öffentliche Upload-API, kein Login), `abgabebox-frontend`, `clamav`, `docs` (MkDocs/nginx).

**Release-Compose ist bereits stark gehärtet** (Kommentare referenzieren frühere Audit-Findings
I1/I2/M28/A2/H11 — d. h. hier gab es schon mindestens einen früheren informellen Security-Pass,
nicht Teil dieses `security-audit/`-Verzeichnisses):
- `read_only: true`, `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, `init: true`
  auf allen App-Containern (Ausnahme unten).
- `mem_limit`/`cpus` auf jedem Service (Ceiling gegen Host-weite Resource-Exhaustion).
- `tmpfs`-Mounts mit `noexec,nosuid,nodev` für `/tmp` etc.
- Secrets ausschließlich über Compose-`secrets:` (`file:`-basiert, `/run/secrets/*`), nie über
  `environment:` mit Klartextwert — Release-Backend/Abgabebox-Backend/DB lesen `*_FILE`-Pfade.
- Postgres: `POSTGRES_PASSWORD_FILE` statt Klartext-Env.

**Nicht `read_only`/`cap_drop`**: `db` (Postgres-Image braucht Schreibzugriff, `secrets:`
  dennoch genutzt) und `traefik` in `docker-compose.yml` (dev-Variante, aber dev-Traefik läuft
  nur profile-gated, nicht direkt am Internet). Die tatsächliche Internet-exponierte
  `docker-compose.traefik.yml`-Variante hat volles Hardening (`cap_drop: ALL` +
  `cap_add: [NET_BIND_SERVICE]` gezielt für privilegierte Ports, `security_opt`,
  `read_only: true`, eigenes `traefik_tmp`-Volume statt tmpfs wegen Body-Buffering).

**Traefik-Docker-Socket-Mount**: `/var/run/docker.sock:/var/run/docker.sock:ro` in beiden
Traefik-Varianten — Docker-Socket-Zugriff (auch read-only) ist grundsätzlich äquivalent zu
Root-auf-Host, da darüber beliebige privilegierte Container gestartet werden könnten. Traefik
selbst läuft mit `cap_drop: ALL`, aber der Docker-Provider braucht diesen Mount für Service-
Discovery. **Für Vertiefung vormerken** (Kategorie: Blast-Radius bei Traefik-RCE, nicht direkt
ausnutzbar ohne vorherige Kompromittierung von Traefik selbst).

## 2. Traefik / Reverse-Proxy

- TLS: zwei Certresolver — `letsencrypt` (HTTP-01, öffentlich) und `letsencryptdns`
  (DNS-01 via Cloudflare-Token, für den privaten Admin-Endpoint/OpenZiti).
- Getrennte Entrypoints: `websecure` (öffentlich, `TRAEFIK_DOMAIN`/`TRAEFIK_ABGABEBOX_DOMAIN`/
  `TRAEFIK_DOCS_DOMAIN`) vs. `adminsecure` (nur `127.0.0.1:${TRAEFIK_ADMIN_PORT:-8443}`,
  gedacht für einen OpenZiti-Host-Tunnel — Plattform-Admin-API/-Frontend sind damit laut
  Compose-Konfiguration nie direkt am öffentlichen Internet).
- Rate-Limiting pro Route via Traefik-Labels (nicht nur im Backend): Login (10/min), Admin-
  Login (10/min, eigener Router), MFA-TOTP-Verify (20/min), `tenant-by-domain` (30/min),
  Wortimport (20/min + 150 MB Body-Limit), Tenant-Import (2050 MB Body-Limit, kein Rate-Limit
  – wirkt aber nur auf `adminsecure`), Abgabebox-Upload (30/min + 2 gleichzeitige Requests +
  ~151 MB Body-Limit), Abgabebox-Public-GET (30–60/min, gegen Enumeration von Mandanten-
  Slugs/Elementen).
- Kommentare zeigen bewusste Historie: mehrere dieser Limits wurden nach konkreten Findings
  ergänzt (fehlendes Rate-Limit auf Admin-Login, fehlendes Body-Limit bei Abgabebox-Upload
  führte zu ungeprüftem Vollpuffern im Speicher vor App-Level-Check).
- Keine expliziten Security-Response-Header (HSTS, CSP, X-Frame-Options, X-Content-Type-
  Options) in den Traefik-Labels sichtbar — **für Vertiefung vormerken**: prüfen, ob diese
  auf App-Ebene (Next.js `next.config.mjs` / FastAPI-Middleware) gesetzt werden; wenn nicht,
  potenzieller Medium/Low-Finding (Defense-in-Depth, kein direkter Bypass einer Kernregel).
- `infra/traefik/traefik.yml` (statische Config) und `infra/traefik/dynamic/` (von
  `traefik_config_service.py` generierte Mandanten-Custom-Domain-Router) selbst noch nicht
  gelesen — **TODO**, gehört eher zum Backend-Audit (Custom-Domain-Feature), hier nur als
  Cross-Reference vermerkt.

## 3. CORS / Trusted Hosts (Deployment-Ebene)

- `ABGABEBOX_CORS_ORIGIN: https://${TRAEFIK_ABGABEBOX_DOMAIN}` — pro Deployment auf eine feste
  Domain gesetzt, kein Wildcard `*` in Compose sichtbar. Tatsächliche CORS-Middleware-Logik
  (ob das auch angewendet wird, ob Credentials erlaubt sind) ist Backend-Code, nicht Teil
  dieser Datei — **an Backend-Audit übergeben**.
- Kein analoges `HOCX_CORS_ORIGIN`/`*_CORS_ORIGIN` für das Haupt-Backend in den Compose-Dateien
  sichtbar — vermutlich weil Haupt-Frontend/Backend über denselben Traefik-Host bzw. Next.js-
  Proxy laufen (`INTERNAL_API_URL`) und daher kein cross-origin Browser-Request nötig ist.
  **Zu verifizieren im Backend-Audit** (`app/main.py` CORS-Middleware-Konfiguration).

## 4. Environment-Variablen (aus `.env.prod.example`, keine echten Werte)

Sicherheitsrelevante erwartete Variablen: `POSTGRES_PASSWORD`, `DATABASE_URL` (Superuser-Rolle,
nur für Alembic), `APP_DB_PASSWORD`/`APP_DATABASE_URL` (least-privilege Runtime-Rolle,
`hocx_app`, siehe Migration `0070_restrict_app_db_role`), `AUTH_SECRET`, `ADMIN_AUTH_SECRET`,
`INITIAL_ADMIN_PASSWORD`, `ABGABEBOX_DB_PASSWORD`/`ABGABEBOX_DATABASE_URL`,
`PHOTO_WORKER_DB_PASSWORD`/`_DATABASE_URL`, `CF_DNS_API_TOKEN`, `FRIENDLY_CAPTCHA_API_KEY`,
`ABGABEBOX_CAPTCHA_SESSION_SECRET`. Die Beispieldatei selbst enthält nur Platzhalter
(`change-me-to-a-random-32-plus-char-value` usw.), keine echten Secrets. `HOCX_SIGNING_IDENTITY_REGEXP`
bindet Image-Vertrauen an eine konkrete GitHub-Actions-Workflow-Identität (Cosign keyless).

Keine unsicher wirkenden **hartkodierten** Defaults in den Compose-Dateien selbst für
Produktions-Secrets — `deploy.sh`s `run_preflight()` (siehe unten) verweigert zusätzlich aktiv
bekannte Platzhalter/kurze Secrets (`< 20` Zeichen) und Dev-/Beispieldomains beim echten Deploy.

Test-/Tools-Compose (`docker-compose.tests.yml`) enthält bewusst schwache, öffentlich bekannte
Test-Credentials (`hocx_test`/`hocx_test`, `test-auth-secret-...`) — nur für den isolierten
CI-Test-Stack (`tmpfs`-DB, kein Persistenz-Volume), kein Bezug zu Prod. Als Ausnahme
dokumentiert in `.gitleaks.toml`'s Allowlist (`ChangeMe123!`, `POSTGRES_PASSWORD:\s*ci`).

## 5. CI/CD (`.github/workflows/`)

- `secret-scan.yml`: Gitleaks gegen vollen Repo-Verlauf (`fetch-depth: 0`) bei jedem Push/PR
  auf `main`/`version-1.1`, nutzt `.gitleaks.toml` (siehe Abschnitt 7).
- `build-test-images.yml` (`workflow_dispatch`, `permissions: contents:read, packages:write,
  id-token:write`): baut alle 6 Service-Images, pusht nach GHCR, signiert **jedes Image per
  Cosign keyless** (OIDC, `cosign sign --yes "$IMAGE@$DIGEST"` — Signatur an unveränderlichen
  Digest gebunden, nicht an den Tag). Signiert zusätzlich ein `deploy-code.manifest`
  (SHA-256 über `.github/workflows/*.yml`, `docker-compose*.yml`, `scripts/**`,
  `infra/traefik/**`) als Blob — das ist die Grundlage für `update_deploy_code.sh`s
  Signaturprüfung vor jedem Deploy-Code-Update auf einem Host.
- `release.yml` (`workflow_dispatch` mit manuellem `confirm_production: "DEPLOY"`-Textfeld):
  promotet nur Images, für die ein erfolgreicher Test-Host-Nachweis existiert
  (`gh api .../deployments?environment=test`, Statuscheck `success`), validiert Tag-Formate
  strikt per Regex, verwendet `environment: name: production` (GitHub-Environment-Schutz,
  z. B. Required Reviewers — abhängig von Repo-Einstellungen, hier nicht einsehbar), verschiebt
  nie einen bereits existierenden Git-Tag auf einen anderen Commit.
  `permissions: contents:read, packages:write, deployments:write` im `verify-tested-candidate`/
  `promote`-Job, `publish-release`-Job bekommt zusätzlich `contents: write` nur für sich selbst
  (least privilege pro Job).
- `ci.yml` (462 Zeilen, nur `pull_request`-Trigger laut Kopf, **kein** `pull_request_target` —
  damit läuft PR-Code nie mit Schreibrechten/Secrets eines privilegierten Kontexts; Standard-
  GITHUB_TOKEN-Rechte für `pull_request` sind ohnehin read-only per GitHub-Default für
  Fork-PRs). Enthält 8 Jobs (Typecheck/Tests je Komponente, siehe `runs-on`-Zeilen) plus einen
  eigenen PR-Diff-Secret-Scan-Job (Zeile ~440–462, nutzt `secrets.GITHUB_TOKEN` nur zum Holen
  des Diffs, nicht für privilegierte Aktionen). Kein `permissions:`-Block auf Workflow-Ebene
  gefunden (Default-Rechte gelten) — **für Vertiefung vormerken**, ob das für diese Jobs
  angemessen ist oder ein `permissions: contents: read` explizit gesetzt werden sollte
  (Defense-in-Depth, kein akutes Risiko bei reinem `pull_request`-Trigger).

## 6. Deploy-Skripte

**`scripts/deploy.sh`** (zentral, 749 Zeilen) — bemerkenswert ausgereift:
- Verweigert Ausführung als root; verlangt dedizierten `hocx-deploy`-User.
- `flock` gegen parallele Deployments; `umask 077` für alles Neuerzeugte.
- Secrets werden bei Ersteinrichtung mit `openssl rand -hex 32` erzeugt, nie vom Nutzer
  eingegeben; `.env` wird mit `install`/`mv` atomar geschrieben (kein Zwischenzustand lesbar).
- **`run_preflight()`** verweigert aktiv: bekannte Platzhalter-/Dev-Passwörter, Secrets
  `< 20` Zeichen, `.local`-Admin-E-Mails in Release-Umgebungen, Dev-/Beispieldomains
  (`localhost`, `*.local`, `*.example.com`), `AUTH_SECURE_COOKIES != true`.
- **`verify_release_images()`**: pullt Images ausschließlich per Tag, verifiziert danach den
  lokal aufgelösten Digest per `cosign verify` gegen die exakte GitHub-Actions-Workflow-
  Identität (Regex) + OIDC-Issuer — Tag-Spoofing/Registry-Kompromittierung ohne gültige
  Workflow-Identität würde hier scheitern. Anschliessend `create_release_manifest()`, das
  Compose danach ausschliesslich per Digest (`HOCX_*_IMAGE`) startet, nicht mehr per Tag.
- Automatisches DB-Backup vor jeder Migration (`pg_dump | gzip`), automatischer App-Rollback
  bei fehlgeschlagenen Smoke-Checks (DB-Migration selbst wird **nicht** zurückgerollt —
  dokumentiertes Verhalten, kein Bug).
- `prepare_runtime_permissions()`/`prepare_thumbnail_dir()`: lehnen Symlinks in Runtime-Pfaden
  explizit ab (Schutz gegen Path-Traversal/Privilege-Escalation über präparierte Storage-Mounts),
  härten Gruppenrechte (`chgrp 5001`, `chmod g+rwX,o-rwx`, `g+s`) statt world-writable/-readable.

**`scripts/provision_deploy_user.sh`** (root-only, einmalig): legt `hocx-deploy`-User an,
bindet einen Host dauerhaft an `test`/`prod` (`/etc/hocx/environment`, `chmod 444`, keine
automatische Umstellung erlaubt), verweigert Symlinks in Storage-Verzeichnissen, setzt
`letsencrypt`-Verzeichnis bewusst auf `root:root` (Traefik braucht das trotz `cap_drop:ALL`,
da es selbst als root läuft aber ohne `CAP_DAC_OVERRIDE`). Enthält einen dokumentierten
Restrisiko-Hinweis: „Die docker-Gruppe besitzt bei klassischem Docker Root-Level-Rechte"
(bekannt/akzeptiert, kein verstecktes Finding).

**`scripts/update_deploy_code.sh`**: einziger Weg, den Deploy-Code auf einem Host zu
aktualisieren; erzwingt `origin`-URL-Allowlist (`FrissBrot/hocX`), nur `main`-Branch,
Fast-Forward-only, **und verifiziert den neuen Commit per Cosign-Signatur gegen das von
`build-test-images.yml` erzeugte `deploy-code.manifest`/`.bundle`**, bevor gemerged wird
(`sha256sum --check` gegen einen frisch aus `git archive` extrahierten Tree) — verhindert,
dass ein Host stillschweigend unsignierten/unautorisierten Skript-/Compose-Code übernimmt,
selbst wenn `origin` selbst kompromittiert wäre (Signatur ist an die Workflow-Identität
gebunden, nicht an den Git-Remote).

Nicht gelesen (niedrigere Priorität laut Auftrag, aber vorhanden): `scripts/backup_db.sh`,
`scripts/cleanup_storage.sh`, `scripts/verify_release.sh`, `scripts/record_tested_candidate.sh`,
`scripts/lib/*.sh` (u. a. `env.sh`, `env_migrate.sh`, `cosign.sh`, `github.sh` — von den oben
gelesenen Skripten per `source` eingebunden, aber Inhalt nicht verifiziert). **TODO für
Vertiefungsphase.**

## 7. Gitleaks / Secret-Scanning

Aktiv an zwei Stellen: lokaler Pre-Commit-Hook (`.githooks/pre-commit`, opt-in per
`git config core.hooksPath .githooks`, fällt ohne installiertes `gitleaks` auf einen
minimalen grep-Fallback zurück, der nur die beiden hartkodierten Domain-Patterns prüft, keine
generischen Secrets) und CI (`secret-scan.yml`, immer aktiv, voller History-Scan). Das
Fallback-Verhalten des Pre-Commit-Hooks ohne installiertes `gitleaks` ist strukturell
lückenhaft (kein genereller Secret-Scan lokal), aber durch die verpflichtende CI-Prüfung
abgesichert — **kein eigenständiges Finding**, da die zweite Ebene (CI) nicht umgangen werden
kann, bevor ein PR mergebar ist (vorausgesetzt Branch-Protection erzwingt den CI-Check —
selbst nicht einsehbar, **für Vertiefung vormerken**).

## Phase 2 — Vertiefung abgeschlossen (siehe `findings-draft/fork-e-deployment.md`)

Ergebnis: 1 bestätigtes Finding (**DEPLOY-01, LOW** — `ci.yml` ohne `permissions:`-Block),
5 der 6 Kandidaten unten geprüft und widerlegt/bestätigt harmlos (Security-Header bereits
umfassend gesetzt auf 2 Ebenen; CORS korrekt und harmlos trotz totem `Authorization`-Header-
Eintrag; Docker-Socket-Mount weiterhin notwendig und akzeptiert; Traefik-Dynamic-Config gegen
Injection durch strikte Domain-Regex abgesichert; restliche Deploy-Skripte durchgängig sauber).
Offen: Branch-Protection-Regeln für `main` (GitHub-Repo-Settings, nicht aus Code einsehbar) →
`FINAL_REPORT.md`, Residual Risk.

Status: **REVIEWED_WITH_FINDINGS**

## 8. Auffälligkeiten für Vertiefung (noch keine Findings, nur Kandidaten) — historisch, siehe oben für Ergebnis

1. Traefik hat `docker.sock` read-only gemountet — Blast-Radius-Frage bei Traefik-RCE
   (Kandidat: LOW/INFO, Defense-in-Depth, kein direkter Angriffspfad ohne vorherige
   Traefik-Kompromittierung).
2. Keine sichtbaren Security-Response-Header (HSTS/CSP/X-Frame-Options) auf Traefik-Ebene —
   prüfen, ob Next.js/FastAPI das setzen (Backend-/Frontend-Audit).
3. `ci.yml` ohne expliziten `permissions:`-Block auf Workflow-Ebene (Default-Rechte) —
   Defense-in-Depth-Kandidat, kein akuter Bypass ersichtlich.
4. Branch-Protection-Regeln für `main` (erzwingt CI/Secret-Scan wirklich vor Merge?) sind aus
   dem Repo-Inhalt selbst nicht einsehbar — GitHub-Repo-Settings, außerhalb des Code-Audits,
   aber relevant für "kann jemand die Ketten oben umgehen, indem er direkt auf main pusht".
5. `infra/traefik/dynamic`-Mechanismus (Custom-Domain-Router, backend-generiert) noch nicht
   inhaltlich geprüft — Cross-Reference zum Backend-Audit (`traefik_config_service.py`):
   Tenant-Isolation bei selbst-generierter Reverse-Proxy-Konfiguration ist ein klassischer
   Ort für SSRF-/Header-Injection-artige Fehler.
6. `scripts/lib/*.sh` und restliche `scripts/*.sh` (Punkt 6 oben) noch nicht gelesen.

## Verbleibende Arbeit für diese Komponente

- Vertiefungspass gegen die 6 oben genannten Kandidaten (Abschnitt 8).
- `infra/traefik/traefik.yml`, `infra/clamav/clamd.conf` inhaltlich lesen.
- `scripts/lib/*.sh`, `backup_db.sh`, `cleanup_storage.sh`, `verify_release.sh`,
  `record_tested_candidate.sh` lesen.
- `docs-site/` (Dockerfile/nginx-Config) — geringe Priorität, öffentlich zugängliche, aber
  nicht sensible Dokumentation.
