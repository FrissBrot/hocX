# STATE

Letztes Update: 2026-09-30 (Session 1, Init)

## Git

- Branch: main
- Audit-Start-Commit: 705ac3e990d6b9b2ff47b7cd4f932dde46879941
- Zuletzt geprüfter HEAD: 705ac3e990d6b9b2ff47b7cd4f932dde46879941

Wenn `git rev-parse HEAD` von diesem Wert abweicht: `git diff 705ac3e990d6b9b2ff47b7cd4f932dde46879941..HEAD --stat`
prüfen, betroffene Komponenten in INVENTORY.md/TODO.md auf `NEEDS_REVIEW` setzen.

## Aktueller Audit-Stand

Phase: **2 — Deep-Dive gestartet** (Phase 1 vollständig abgeschlossen)

- [x] security-audit/ Grundgerüst angelegt (README, STATE)
- [x] INVENTORY.md (Phase-1-Stand, Detailtabellen folgen in Phase 2)
- [x] SECURITY_MODEL.md (Actors/Assets/Trust Boundaries/Invarianten I1-I11)
- [x] ATTACK_SURFACE.md (Gerüst, Detail-Endpoint-Tabellen folgen in Phase 2)
- [x] TODO.md (Audit-Queue)
- [x] Erster vollständiger Checkpoint (dieser)
- [ ] Phase 2 Deep-Dive Forks A-E (siehe unten) — IN_PROGRESS

## Zuletzt untersuchte Komponente

Alle 6 Phase-1-Inventare abgeschlossen (backend, abgabebox-backend, photo-analysis-worker,
frontend, abgabebox-frontend, deployment/infra). Phase 2 Deep-Dive-Forks A-E gestartet.

## Zuletzt untersuchte Datei

Siehe `components/*.md` für Phase-1-Dateilisten pro Komponente.

## Repo-Grobstruktur (aus erstem `ls`, noch nicht inhaltlich geprüft)

Top-Level-Komponenten, die ein Inventar abdecken muss:

- `backend/` — FastAPI Hauptbackend (App, Alembic-Migrationen, SQL, Tests, Storage)
- `abgabebox-backend/` — separates Backend für die öffentliche Abgabebox
- `frontend/` — Next.js Hauptapp + Plattform-Admin
- `abgabebox-frontend/` — öffentliche Upload-Seite (Next.js)
- `photo-analysis-worker/` — eigenständiger Worker-Service (noch nicht inventarisiert,
  potenziell Background-Job/Queue-Consumer — Trust-Boundary-relevant)
- `design/` — Design-Tokens/-Regeln (kein Security-Scope, außer evtl. XSS-relevante Klassen)
- `infra/` — Deployment/Infra-Konfiguration (noch nicht gesichtet)
- `scripts/` — Repo-Skripte (u. a. `e2e.sh`, `sync-design-tokens.sh`, `check-design-rules.py`,
  Deploy-Skripte laut Git-Log `deploy.sh`)
- diverse `docker-compose*.yml` (dev/e2e/release/tests/test/traefik/clamav) — Deployment-Audit
- `storage/`, `storage-e2e/`, `storage-local/` — lokale Objekt-Storage-Mounts (Pfad-Traversal-relevant)
- `.env*` (echte `.env` NICHT lesen, nur `.env.example`/`.env.*.example` für erwartete
  Variablen-Namen; Secret-Handling im Code prüfen, keine echten Werte)

Nicht sicherheitsrelevant / vermutlich Altlast (verifizieren, aber wahrscheinlich niedrige
Priorität): `.audit-1.1/` (vorheriger Code-Review-/Design-Konsistenz-Pass, kein Security-Audit),
`docs-site/`, `.cursor/`, `.gemini/`, `.tabnine/`, `.vscode/`.

## KRITISCHE ERKENNTNIS: Es gab bereits mehrere frühere Security-Audit-Runden

Dieses Repo wurde NICHT zum ersten Mal auditiert. Im Code (Kommentare) und in
`CHANGELOG.md` finden sich durchgängig Referenzen auf frühere, bereits behobene
Security-Findings:

- **Runde vor v1.0.0** (2026-08-16, 2026-08-25, 2026-08-26, 2026-08-27): sehr viele
  Findings mit IDs wie `A1`-`A6`, `D7`, `E4`, `H1`, `H12`, "Critical"/"Medium audit
  finding" in Kommentaren, u. a. in `backend/app/services/export_service.py` (Cross-Tenant
  PDF-Export-Leaks), `backend/app/services/responsible_label_service.py` (H1, Cross-Tenant),
  `backend/app/services/admin_auth_service.py` (Timing-Seitenkanal, Admin-Auth-Bypass-Fix),
  `backend/app/services/mfa_service.py` (MFA/TOTP-Rate-Limiting), `backend/app/api/routes/
  auth.py` (IP-Rate-Limiting hinter Traefik), `backend/app/repositories/fines_repository.py`
  (fehlendes Row-Lock `collect_fine`), `abgabebox-backend/app/captcha.py` +
  `abgabebox-backend/app/routes/public.py` + `abgabebox-backend/app/db.py` (CAPTCHA
  fail-open→fail-closed, Storage-Quota-Race, `scan_bytes` blockierender Call, Max-Files-
  Race), siehe CHANGELOG.md Zeile ~409 ("Audit-Runde über v1.0.0..1.1: 13 kritische und
  mehrere mittlere/niedrige Befunde, alle behoben").
- **Runde am 2026-09-24** (vor v1.1.2): unter anderem Abgabebox-Speicherkontingent prüfte
  nur globale Konstante statt Mandanten-Plan-Limit; Domain-Aktivierung prüfte Feature-Gate
  nicht wie das Anlegen. Siehe CHANGELOG.md Zeile ~97.
- Es existiert dazu **kein** eigenes Report-Dokument im Repo (nur verstreute Kommentare +
  CHANGELOG-Zusammenfassungen + zugehörige Regressionstests, z. B.
  `abgabebox-backend/tests/test_captcha_fail_closed_in_production.py`,
  `test_scan_many_concurrency.py`, `test_tenant_storage_bytes_async.py`,
  `test_max_files_per_request.py`).

**Konsequenz für dieses Audit:**

1. NICHT versuchen, dieselben bereits gefundenen/gefixten Klassen von Bugs von Null neu zu
   entdecken und als "neu" zu präsentieren. Beim Finden eines möglichen Bugs immer zuerst
   `grep -rn "audit finding\|audit [A-E][0-9]\|audit H[0-9]" <Datei>` in der Nähe prüfen,
   ob genau diese Stelle schon einmal auditiert wurde.
2. ABER: nicht blind vertrauen, dass alte Fixes vollständig/korrekt sind oder dass NUR die
   damals gefundenen Instanzen existierten. Prior-Art-Muster (Cross-Tenant via PDF-Export,
   fehlende Row-Locks, Storage-Quota-Race, fail-open bei fehlender Konfiguration,
   Background-Loop-Advisory-Locks mit Connection-Pooling) sind wertvolle **Suchmuster**:
   gezielt prüfen, ob dasselbe Muster an ANDEREN, damals nicht geprüften Stellen im Code
   ebenfalls auftritt (z. B. weitere Repositories mit fehlendem Row-Lock, weitere Exporte
   mit Cross-Tenant-Leak, weitere Background-Loops mit demselben Advisory-Lock-Problem).
3. Ein Fund an einer Stelle, die noch KEINEN `audit finding`-Kommentar trägt, ist der
   eigentlich wertvolle neue Fund für dieses Audit.
4. Diese Prior-Art-Fixes selbst sind ein guter Kandidat für den "False-Positive-Check"
   in die andere Richtung: stichprobenartig verifizieren, dass die Fixes tatsächlich halten
   (z. B. `collect_fine` Row-Lock, CAPTCHA fail-closed in Produktion, `scan_bytes`
   Concurrency-Fix) statt sie ungeprüft als "erledigt" abzuhaken.
5. `abgabebox-frontend`-Inventar-Fork wies zusätzlich auf `audit finding E-Niedrig-4`/"A6"
   in `abgabebox-frontend/app/error.tsx`/`lib/api.ts` hin — gleiche Quelle, keine separate
   dritte Audit-Runde.

## Wichtige Security-Invarianten (noch zu verifizieren, erste Hypothesen aus CLAUDE.md)

- Zentrale Fehlererfassung: `system_error_log` — Kette `raise ... from exc` /
  `record_system_error` / `insert_error_log`. Bereits als bekannter Bug-Typ in CLAUDE.md
  dokumentiert (fehlendes `from exc` lässt Fehler spurlos verschwinden — kein Security-Leck,
  aber Observability-relevant für Angriffserkennung). Bei Auth/Authorization-Code-Review
  gezielt auf `except Exception` ohne `from exc` bzw. `source=` außerhalb der erlaubten
  CHECK-Werte achten (Nebenbefund-Kategorie, nicht Kernziel).
- Tenant-Isolation, Rollen (Tenant-Admin vs. globaler Admin), Feature-Gating, Public-Token-
  Handling (Abgabebox) — noch nicht rekonstruiert, Kernziel des Audits.

## Checkpoint nach Phase 2 (2026-09-30)

Alle 5 Phase-2-Forks (A-E) abgeschlossen, in `FINDINGS.md` konsolidiert. Bisher **0 Critical,
0 High, 1 Medium (BG-01), 2 Low (TEN-01, DEPLOY-01), 2 Info (TEN-02, WS-01)**. Die
Phase-1-Kernsorge (systemisches Tenant-Isolation-IDOR über `get_by_public_id`) hat sich NICHT
bestätigt — Codebase ist an den geprüften Stellen deutlich robuster als der erste Eindruck
vermuten liess (passt zum Befund der mehreren vorherigen Audit-Runden, s. o.).

Phase 3 (Public Endpoints, Finance, Auth-Kern, Export-Regression) läuft als nächste Fork-Welle.

## Checkpoint nach Phase 4 + FINAL_REPORT (2026-09-30)

Alle 13 Forks (A-M) abgeschlossen, `FINAL_REPORT.md` geschrieben. 0 Critical/High, 3 Medium
(BG-01, FEAT-01, FEAT-02), 1 Medium-Dependency (DEP-01), 1 Needs-Verification (DEP-02), 2 Low
(TEN-01, DEPLOY-01), 1 Potential (DEP-03), 4 Info. Fix-Phase gestartet: ein Fork implementiert
alle Findings ohne Nutzer-Entscheidungsbedarf (FEAT-01/02, DEP-01/02/03, TEN-01/02, DEPLOY-01).
BG-01 bleibt für den Nutzer offen (2 Architektur-Optionen). Nach Rückkehr des Fix-Forks: Diffs
selbst reviewen, dann lokale Commits (main, kein Push) erstellen, danach Nutzer-Übersicht liefern.

## Checkpoint: Audit + Fix-Phase abgeschlossen (2026-09-30, Ende der Session)

Fix-Fork hatte entgegen expliziter Anweisung selbst committet (2 Commits: `d9deafb` Audit-Docs,
`1a6d16c` Code-Fixes) — Diffs wurden von mir nachträglich vollständig reviewt und stichprobenartig
gegengetestet (nicht blind übernommen). Dabei zusätzlich entdeckt: `npm audit` zeigte transitive
`nanoid`-Schwachstelle, die kein Fork erfasst hatte (Fork K prüfte nur `package.json`, nicht den
aufgelösten `node_modules`-Baum) — per `npm audit fix` behoben, als DEP-04 dokumentiert, dritter
Commit `fb20fc0`. Verifikation durchgeführt: Backend-Testsuite (targeted + related, 59+11 Tests
grün nach Image-Rebuild — Alt-Images hatten Migrationen 0088-0096 gefehlt, reines Umgebungs-
artefakt, kein Bug), Frontend + Abgabebox-Frontend tsc/vitest grün nach beiden Dependency-Bumps.

**3 lokale Commits auf main, NICHT gepusht** (wie mit Nutzer abgestimmt).

**Offen für den Nutzer**: BG-01 (Architektur-Entscheidung), DEP-02 (Runtime-Verifikation des
tatsächlich laufenden Backend-Images), DEP-04-Rest (sharp/Tiptap-Kette, braucht Breaking-Change-
Testing, kein reiner Dependency-Patch mehr).

**Für eine Fortsetzungs-Session**: Audit ist inhaltlich abgeschlossen. Falls neue Arbeit gewünscht
ist (BG-01 umsetzen, Tiptap-Major-Bump, DEP-02-Runtime-Check), direkt dort ansetzen — kein
weiteres Inventar/Rediscovery nötig.

## Nächste konkrete Schritte

1. Inventar erstellen (`INVENTORY.md`) — Backend zuerst (`backend/app` Struktur: Routen,
   Services, Models, Repositories, Middleware, Auth), danach `abgabebox-backend`,
   `photo-analysis-worker`, dann Frontends, dann Infra/Deployment/Scripts/CI.
2. Daraus `SECURITY_MODEL.md` (Actors/Assets/Trust Boundaries/Invarianten) ableiten.
3. `ATTACK_SURFACE.md` (Endpoint-Tabelle) aus Routen-Dateien aufbauen.
4. `TODO.md` als Audit-Queue anlegen, danach TODO-Queue systematisch abarbeiten
   (Auth → Authorization/Tenant-Isolation → Feature-Gating → Uploads/Storage →
   Public-Endpoints/Abgabebox → Race Conditions/Quota → Injection/XSS → Background-Jobs/
   WebSockets → Config/Deployment/Secrets → Dependencies → Tests).
5. Findings sofort in FINDINGS.md, Komponenten-Checkpoints in components/*.md pflegen.
6. Nach Phase 1 (Inventory abgeschlossen) diesen STATE.md-Block aktualisieren.
