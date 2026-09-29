# Fork E — Deployment-Vertiefung: Findings-Entwurf

Bearbeitet: Security-Response-Header, CORS-Realität, `ci.yml`-Permissions, Traefik-Docker-
Socket, `traefik_config_service.py`-Injection, restliche `scripts/lib/*.sh` + Deploy-Skripte.

## Bestätigte Findings

### [DEPLOY-01] [LOW] `ci.yml` deklariert keinen workflow-weiten `permissions:`-Block

Status: CONFIRMED
CWE: CWE-276 (Incorrect Default Permissions)

Betroffene Dateien: `.github/workflows/ci.yml`

Betroffene Funktionen: n/a (Workflow-Konfiguration, alle 8 Jobs)

### Security Invariant

CI-Workflows sollen nach dem Least-Privilege-Prinzip nur die GitHub-Token-Rechte erhalten,
die sie tatsächlich brauchen — analog zu `release.yml` (Zeile 24, workflow-weit) und
`build-test-images.yml` (Zeile 6), die beide explizit `permissions:` setzen.

### Beschreibung

`.github/workflows/ci.yml` hat weder auf Workflow- noch auf Job-Ebene einen `permissions:`-
Block. Damit gelten die Repository-Default-Berechtigungen für `GITHUB_TOKEN` (Einstellung
"Settings → Actions → Workflow permissions", vom Code aus nicht einsehbar) statt eines
expliziten, im Code nachvollziehbaren Minimalsatzes.

### Root Cause

Der Workflow ist über Zeit gewachsen (8 Jobs), ohne dass beim Hinzufügen ein
`permissions:`-Block nachgezogen wurde, während die beiden anderen (später/bewusster
geschriebenen) Workflows ihn von Anfang an haben.

### Preconditions

Kein aktiver Angreifer nötig für den Fund selbst; relevant würde es, falls (a) die
Repository-Default-Einstellung großzügiger als `read` ist, UND (b) ein PR (auch von einem
Fork) diesen Workflow auslöst. Trigger ist `pull_request`/`push`, beide auf `branches: [main]`,
**nicht** `pull_request_target` — GitHub vergibt `GITHUB_TOKEN` für `pull_request`-Läufe aus
Forks standardmässig ohnehin nur Read-Rechte, unabhängig von der Repo-Einstellung. Das
begrenzt die reale Ausnutzbarkeit stark; für `push`-Läufe (nur nach Merge auf `main`, kein
Fremdcode-Trigger) gilt die Repo-Einstellung ungefiltert, ist aber kein Angriffspfad, weil nur
Committer mit Schreibzugriff auf `main` einen `push`-Lauf auslösen.

### Attack Path

Kein konkreter Exploit-Pfad verifiziert (siehe False-Positive-Check unten) — reines
Defense-in-Depth-Gap, kein bestätigter Bypass einer Kernregel.

### Proof of Concept

Entfällt (kein aktiver Exploit).

### Impact

Falls die Repo-Default-Einstellung `read/write` ist (nicht verifizierbar aus dem Repo-Inhalt)
UND ein zukünftiger Job in `ci.yml` versehentlich eine schreibende Aktion bekommt (z. B. ein
PR-Kommentar-Bot), hätte dieser automatisch weitreichendere Rechte als nötig, ohne dass das im
Code sichtbar wäre. Aktuell nutzt kein Job in `ci.yml` Schreibrechte (verifiziert: kein
`actions/github-script` mit Write-Aktion, kein `gh pr comment`, `secret-scan`-Job nutzt
`GITHUB_TOKEN` nur lesend für `gitleaks-action`).

### Existing Mitigations

- Trigger ist `pull_request` (nicht `pull_request_target`) → Fork-PRs bekommen von GitHub
  selbst nur Read-Token, unabhängig von Repo-Settings.
- Kein Job verwendet aktuell Schreib-Aktionen.
- Branch-Protection auf `main` (Repo-Einstellung, hier nicht einsehbar) würde zusätzlich
  greifen, bevor ein manipulierter CI-Lauf Schaden anrichten könnte.

### Why Existing Checks Are Insufficient

Die Mitigations verhindern eine aktuelle Ausnutzung, sind aber implizit (GitHub-Plattform-
Default, Repo-Settings) statt im Code nachvollziehbar/erzwungen. Ein zukünftiger Job-Zusatz
(`push`-Trigger-Kontext oder ein neuer, schreibender Schritt) würde sich stillschweigend auf
die Default-Rechte statt auf ein explizites Minimum verlassen.

### Recommended Fix

Workflow-weiten Block ergänzen:
```yaml
permissions:
  contents: read
```
direkt nach `on:` in `.github/workflows/ci.yml`, analog zu `release.yml`/`build-test-images.yml`.
Kein Job in diesem Workflow braucht mehr als `contents: read`.

### Regression Test

Kein automatisierter Test sinnvoll (Policy-Konfiguration); stattdessen: Code-Review-Checkliste/
Kommentar in `ci.yml`, dass ein neuer Job mit Schreibbedarf den `permissions:`-Block
job-spezifisch erweitern muss statt den Workflow-Default zu nutzen.

### Evidence

- `.github/workflows/ci.yml:1-9` (kein `permissions:` zwischen `name:` und `jobs:`)
- Gegenprobe: `.github/workflows/release.yml:24`, `.github/workflows/build-test-images.yml:6`
  (beide setzen `permissions:` explizit)

---

## Geprüft, kein Fund (False-Positive-Check bereits angewendet)

- **Security-Response-Header (HSTS/CSP/X-Frame-Options/X-Content-Type-Options)**: bereits
  umfassend gesetzt, mehrfach redundant — `frontend/next.config.mjs` UND
  `abgabebox-frontend/next.config.mjs` setzen beide eine durchdachte CSP (inkl. dokumentierter
  Begründung für jedes `'unsafe-inline'`/Ausnahme) + HSTS/X-Frame-Options/X-Content-Type-Options
  für alle Routen (`source: "/(.*)"`), UND `infra/traefik/traefik.yml` wendet zusätzlich
  `security-headers@file` auf beide öffentlichen Entrypoints an (`websecure`, `adminsecure`) —
  selbst bereits Ergebnis eines früheren Audit-Fixes (Kommentar: "Audit finding (Low),
  2026-08-27"). Kein Handlungsbedarf. Cross-Reference für den XSS-Fork (rich-text-editor.tsx):
  falls dort ein Stored-XSS bestätigt wird, ist `script-src 'unsafe-inline'` in der CSP zu
  beachten — die aktuelle CSP würde ein per Stored-XSS eingeschleustes `<script>`-Tag NICHT
  blocken, da Inline-Skripte erlaubt sind (aus anderem, dokumentiertem Grund). CSP ist hier
  also keine wirksame zweite Verteidigungslinie gegen Stored-XSS, nur gegen extern geladene
  Skripte/Bilder/Frames.
- **CORS `allow_headers` enthält `"Authorization"` ohne erkennbaren Bearer-Token-Consumer**:
  verifiziert per Grep über `backend/app/core/security.py`, `backend/app/main.py`,
  `backend/app/api/routes/auth.py` — kein Code liest je einen `Authorization`-Header aus. Reines
  totes CORS-Config-Detail (harmlos: `allow_headers` in einer CORS-Preflight-Response erlaubt nur,
  dass ein Browser diesen Header *senden darf*; da nichts ihn server-seitig auswertet, hat ein
  Angreifer dadurch keinen zusätzlichen Zugriff). Kein Security-Finding, nur ein
  Aufräum-Hinweis (INFO): Eintrag könnte entfernt werden, wenn kein Bearer-Token-Pfad geplant ist.
- **CORS-Origin-Liste im Hauptbackend erfasst keine Tenant-Custom-Domains**: verifiziert als
  unkritisch — `browserApiFetch()`/`browserApiUpload()` im Frontend nutzen ausschliesslich
  relative Pfade (`publicApiUrl = ""`), die über Next.js' serverseitigen `rewrites()`
  (`/api/:path*` → `INTERNAL_API_URL`) proxied werden. Der Browser sieht daher nie eine
  Cross-Origin-Anfrage zum Backend (auch nicht bei einer Tenant-Custom-Domain, weil auch dort
  Frontend+Backend über denselben Traefik-Host/dieselbe Next.js-Instanz laufen) — die gelistete
  `allow_origins`-Liste (`localhost:3000`, `127.0.0.1:3000`, `TRAEFIK_DOMAIN`) dient nur direkten
  Dev-/Tooling-Zugriffen auf das Backend ohne den Next.js-Proxy dazwischen. `allow_credentials=True`
  mit einer festen (nicht Wildcard-)Origin-Liste ist die korrekte, CSRF-sichere Kombination.
  Kein Finding.
- **Traefik-`docker.sock`-Mount (read-only)**: bestätigt weiterhin nötig — der `docker`-Provider
  routet die Kern-Services (`backend`, `frontend`, `abgabebox-*`, ...) über Labels; der
  `file`-Provider (`infra/traefik/dynamic/`) deckt ausschliesslich die dynamisch generierten
  Tenant-Custom-Domain-Router ab (`tenant-domains.yml`, von `traefik_config_service.py`
  geschrieben). Eine rein dateibasierte Konfiguration würde bedeuten, für jeden Kern-Service eine
  vollständige Router/Service-Definition manuell zu pflegen (Ports, TLS, Middlewares) statt sie aus
  Docker-Labels abzuleiten — kein einfacher risikofreier Umbau, daher weiterhin akzeptiertes
  Restrisiko (Traefik selbst läuft mit `cap_drop: ALL`, Mount ist `:ro`, Traefik-Dashboard ist
  bereits deaktiviert — eigener früherer Audit-Fix "F-Niedrig-1"). Kein neues Finding, nur
  bestätigt.
- **`traefik_config_service.py` / `tenant-domains.yml`-Injection über Custom-Domain-Freitext**:
  aktiv geprüft und **widerlegt**: `TenantService.create_domain()`
  (`backend/app/services/tenant_service.py:218-260`) validiert jede eingereichte Domain gegen
  `domain_verification_service.is_valid_domain_format()`
  (`backend/app/services/domain_verification_service.py:7-18`,
  Regex `^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$`, max. 253 Zeichen) — erlaubt
  ausschliesslich Kleinbuchstaben/Ziffern/Bindestrich/Punkt, keine Backticks, Leerzeichen,
  Klammern oder Anführungszeichen. Damit ist ein Ausbruch aus dem generierten Traefik-Rule-String
  (`Host(\`{domain}\`)`, f-String in `traefik_config_service.py:20` u. a.) nicht möglich, auch
  nicht über YAML-Sonderzeichen (der String wird zusätzlich über `yaml.safe_dump` geschrieben,
  keine manuelle YAML-String-Konkatenation). Zusätzliche Hürde: eine Domain wird erst nach
  bestandener DNS-Challenge (`verify_domain`) aktiv und damit erst dann in `regenerate()`
  aufgenommen. Kein Finding.
- **`scripts/lib/cosign.sh`, `scripts/lib/github.sh`, `scripts/lib/env.sh`,
  `scripts/lib/env_migrate.sh`, `scripts/backup_db.sh`, `scripts/cleanup_storage.sh`,
  `scripts/verify_release.sh`, `scripts/record_tested_candidate.sh`**: vollständig
  gelesen/gegrept. Konsistent hohes Niveau: `set -euo pipefail`, durchgängiges Quoting,
  `mktemp` + `trap ... EXIT`/`RETURN` statt vorhersagbarer Temp-Pfade, explizite
  Symlink-Ablehnung bei sensiblen Token-Dateien (`github.sh`), `chmod 600/700` auf
  Secret-/Token-Verzeichnisse, Regex-Validierung von extern kommenden Werten
  (`HOCX_VERSION`-Tag-Format in `record_tested_candidate.sh`), gepinnte Checksums für
  heruntergeladene Binaries (`cosign.sh`, SHA-256 pro Architektur). Keine `eval`, keine
  ungequoteten gefährlichen Expansionen, kein Command-Injection-Vektor gefunden. Kein Finding.

## Aktualisierung für `security-audit/components/deployment.md`

Abschnitt 8 (Auffälligkeiten) kann wie folgt aktualisiert werden: Punkte 1 (Docker-Socket), 2
(Security-Header), 5 (Traefik-Dynamic-Injection) sind geprüft und **kein Fund** (siehe oben);
Punkt 3 (`ci.yml`-Permissions) ist jetzt **DEPLOY-01 (LOW, CONFIRMED)**; Punkt 6 (`scripts/lib/*.sh`
etc.) ist geprüft, kein Fund. Punkt 4 (Branch-Protection für `main`) bleibt offen — aus dem
Repo-Inhalt nicht einsehbar (GitHub-Repo-Settings), gehört in `FINAL_REPORT.md` unter
"Residual Risk / benötigt Runtime-/Settings-Einsicht, nicht durch Code-Audit beantwortbar".
