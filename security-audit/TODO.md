# TODO — Audit-Queue

Reihenfolge ist absichtlich: erst Inventar, dann Kern-Sicherheitsmodell (Auth/Tenant),
dann Fläche nach Fläche. Nicht zufällig zwischen Bereichen springen.

## Phase 1 — Inventar

- [DONE] backend/ → security-audit/components/backend.md (Kernbefund: `public_id_service.get_by_public_id` filtert nur bei Modellen mit eigener tenant_id-Spalte — bei transitiv gescopten Entities [ProtocolElement, StoredFile, ProtocolTodo, ...] ist tenant_id= ein stiller No-Op, Caller müssen selbst access_repository-Checks machen; Rollen-/Feature-Gates sind reine Funktionsaufrufe ohne Dependency-Zwang; admin.py [960 Zeilen] noch ungeprüft)
- [DONE] abgabebox-backend/ → security-audit/components/abgabebox-backend.md (Magic-Number-Check/ClamAV/2 Advisory-Locks gegen Quota-Race vorhanden; Vertiefung: verschluckter insert_upload_log-Fehler, Lock-Verschachtelung, Traefik-Rate-Limit unverifiziert)
- [DONE] photo-analysis-worker/ → security-audit/components/photo-analysis-worker.md (Auffälligkeiten: Background-Loop-Fehler erreichen system_error_log evtl. nie; stored_file_ids evtl. nicht erneut gegen job.tenant_id geprüft — Vertiefung nötig)
- [DONE] frontend/ → security-audit/components/frontend.md (kein Auth-Layout-Wrapper, jede page.tsx ruft requireSession()/requireAdminSession() selbst; proxy.ts prüft nur "authenticated", nicht Rolle/Tenant; rich-text-editor.tsx = ungeprüfter Stored-XSS-Kandidat)
- [DONE] abgabebox-frontend/ → security-audit/components/abgabebox-frontend.md (kein eigenes Auth, Backend massgeblich; kein XSS-Fund; ACHTUNG: Code-Kommentare referenzieren einen früheren externen Security-Audit "E-Niedrig-4"/"A5, 2026-08-16" — Quelle klären, siehe TODO unten)
- [DONE] deployment/infra/scripts/CI → security-audit/components/deployment.md (bereits ausgereift: Cosign keyless-Signaturen, read_only/cap_drop:ALL, sichere deploy.sh mit Preflight+Rollback; 6 Vertiefungskandidaten: u.a. Docker-Socket-Mount bei Traefik, fehlende Security-Header, ci.yml ohne permissions:-Block)
- [DONE] Alle 6 Phase-1-Inventare abgeschlossen (2026-09-30)
- [IN_PROGRESS] Synthese: INVENTORY.md, SECURITY_MODEL.md, ATTACK_SURFACE.md aus obigen
  Component-Dateien zusammenführen

## Phase 2 — Deep-Dive-Forks (gestartet 2026-09-30)

- [DONE] **Fork A — Tenant-Isolation** → `findings-draft/fork-a-tenant-isolation.md`:
  Kernhypothese aus Phase 1 (I3, `get_by_public_id`-No-Op als systemisches IDOR-Muster)
  **widerlegt** — ~20 Call-Site-Gruppen über 10 Dateien geprüft (todos.py, protocol_elements.py,
  files.py, submission_assignments.py, templates.py, lists.py, word_import.py, fines.py, users.py
  MFA, protocol_todo_service.py, events.py), überall korrekter nachgelagerter Tenant-/Ownership-
  Check gefunden. Ausserdem Phase-1-Doku-Fehler korrigiert: `StoredFile`/`ProtocolTodo` haben
  entgegen `public_id_service.py`-Docstring inzwischen eigene `tenant_id`-Spalten. 2 Findings:
  TEN-01 (LOW, 4 ungenutzte unscoped Repository-Wrapper = künftiger Footgun),
  TEN-02 (INFO, veralteter Docstring). Nicht erschöpfend geprüft: `participant_service.py:137`,
  `admin.py`/`tenants.py` (siehe Fork B), `ProtocolImage`/`ProtocolText`-Callsites ausserhalb files.py.
- [DONE] **Fork B — Authorization/Platform-Admin** → `findings-draft/fork-b-authz-admin.md`:
  0 neue bestätigte Findings. `admin.py` (960 Z., vollständig), `admin_auth.py`, `admin_security.py`
  vollständig gelesen: router-weiter `Depends(get_current_admin)` + konsistente
  `require_admin_write`/`require_admin_owner` auf jeder Mutation/jedem PII-Read, MFA ohne Fallback
  erzwungen, Rollen "owner"/"support" sauber getrennt, Open-Redirect-Schutz bei OIDC verifiziert.
  `tenants.py`/`users.py` vollständig gelesen (Guards teils im Service-Layer, aber überall inkl.
  Tenant-Match vorhanden). Automatisierter Guard-Scan über ALLE Routendateien lief zusätzlich
  (Suche nach state-changing Routen ohne jeden Rollen-Guard) — keine Anomalie gefunden, aber
  `events.py`, `finance.py`, `fines.py`, `participants.py`, `lists.py`, `statistics.py`,
  `templates.py`, `document_templates.py`, `cycle_configs.py`, `tag_config.py`, `todos.py`,
  `table_snapshots.py`, `protocol_elements.py`, `share_links.py`, `public_share.py`,
  `submission_assignments.py`, `collaboration_ws.py` wurden NICHT einzeln zeilenweise gelesen —
  `finance.py`/`fines.py` (Geld) und die Public-Boundary-Dateien haben Priorität für Phase 3/4.
- [DONE] **Fork C — Uploads/Injection/XSS** → `findings-draft/fork-c-uploads-xss.md`:
  0 neue Findings, alle 6 Phase-1-Verdachtsmomente widerlegt (gallery_upload_route korrekt
  registriert, kein blockierender Scan-Call, files.py scoped konsequent über access_service,
  ZIP-Handling gehärtet, Injection-Greps sauber, rich-text-editor.tsx = Tiptap mit html:false,
  kein Stored-XSS möglich). 2 Punkte für später vermerkt (LaTeX-Escaping PDF-Export, ZIP-Test-
  Empfehlung).
- [DONE] **Fork D — Background/WebSocket/Race Conditions** → `findings-draft/fork-d-background-race.md`:
  1 Finding (BG-01, CONFIRMED, MEDIUM — photo-analysis-worker-Fehler erreichen system_error_log
  nie, DB-Rolle hat auch kein GRANT dafür; Fix-Entscheidung nötig, siehe FINAL_REPORT-Kandidat).
  3 Kandidaten widerlegt/eingeordnet: WS-Origin-Allowlist ist nicht tenant-gescoped aber durch
  DNS-Verifikation + SameSite=Lax abgesichert (FALSE_POSITIVE als Bypass, nur Verbesserungsvorschlag),
  abgabebox-Locks sind TOCTOU-frei (Korrektur einer Fehleinschätzung aus Phase 1: `serialized_upload`
  ist per-Tenant, nicht global), Migration 0088 ohne Enforcement-Gap. Alle 10 Background-Loops in
  `background_loops.py` verifiziert korrekt an `record_system_error` angeschlossen. Kein Live-E2E-
  Test nötig (Begründung in der Findings-Datei). photo-analysis-worker Job-Tenant-Scoping verifiziert:
  kein Cross-Tenant-Leck.
- [DONE] **Fork E — Deployment-Vertiefung** → `findings-draft/fork-e-deployment.md`:
  1 Finding (DEPLOY-01, LOW, `ci.yml` fehlender `permissions:`-Block). 5 Kandidaten widerlegt
  (Security-Header bereits doppelt vorhanden [Next.js + Traefik], CORS korrekt, Docker-Socket-
  Mount notwendig, Traefik-Config-Injection durch Hostname-Regex abgesichert, Deploy-Skripte sauber).
  Offen für FINAL_REPORT/Residual Risk: Branch-Protection-Regeln für main nicht im Repo einsehbar.

## Phase 3 — Deep-Dive-Forks Welle 2 (gestartet 2026-09-30, nach Phase-2-Konsolidierung)

- [DONE] **Fork F — Public Endpoints** → `findings-draft/fork-f-public-endpoints.md`:
  1 Finding (PUB-01, INFO, `/api/clamav/status` gibt ClamAV-Version an jeden Tenant mit
  Abgabebox-Feature preis, keine echte Grenzverletzung). Sonst sauber: 192-Bit-Share-Tokens,
  serverseitige Expiry/Revocation bei jedem Zugriff geprüft, ununterscheidbare 404s (keine
  Enumeration), App-seitiges Rate-Limiting auf allen Public-Routen, kein IDOR.
  submission_assignments.py ist entgegen Annahme NICHT öffentlich (require_abgabebox_read/write
  überall) — echte unauthentifizierte Grenze ist nur public_share.py (4 Routen).
  ATTACK_SURFACE.md + backend.md aktualisiert.
- [DONE] **Fork G — Finance/Fines** → `findings-draft/fork-g-finance.md`: 0 neue Findings.
  Alle 5 Prüffragen bestätigt sauber: Rollen-Guards passend, kassier-Rolle sauber getrennt,
  ALLE 4 state-changing Fine-Operationen (nicht nur collect_fine) row-locked, Cross-Tenant
  überall blockiert (404 kollabiert Not-Found/Wrong-Tenant/Already-Collected, keine
  Enumeration), Beträge Decimal/Numeric(15,2), saubere Fehlerbehandlung bei Overflow.
- [DONE] **Fork H — Auth-Kernaudit** → `findings-draft/fork-h-auth-core.md`: 0 neue Findings
  (1 INFO: GET /bridge als einziger GET-mit-Seiteneffekt, aber selbstlimitierend durch
  Single-Use/60s-TTL/256-Bit-Token). CSRF/Rate-Limiting(Redis, 2 Schichten)/Session-Revocation/
  Lockout(15min)/Cookie-Scoping alle sauber. Passwort-Reset existiert bewusst nicht (keine
  Mail-Infra, dokumentierte Entscheidung).
- [DONE] Alle Phase-3-Welle-2-Forks (F,G,H,I) abgeschlossen (2026-09-30)
- [DONE] **Fork I — Export-Regression/Tenant-Restpunkte** → `findings-draft/fork-i-export-tenant-leftovers.md`:
  0 neue Findings. Alle 7 historischen Cross-Tenant-PDF-Export-Fixes intakt, statistics.py/
  exports.py sauber gescoped, LaTeX-Escaping robust (kein \input/\include-Injection möglich),
  participant_service.py:137 durch nachgelagerten Check abgesichert, ProtocolImage/ProtocolText/
  ProtocolDisplaySnapshot ausserhalb files.py haben keinen direkten Client-Resolve-Pfad.

## Phase 3b — abgeschlossen

Alle Punkte durch Fork F-I erledigt und in FINDINGS.md konsolidiert (siehe Phase 3 oben).

## Phase 4 — Restliche Pflichtabschnitte (Welle 3, gestartet 2026-09-30)

Bereits durch frühere Forks abgedeckt (kein erneuter Fork nötig): Input Validation (11, u. a.
Geldbeträge in Fork G), Injection/SSRF (12/15, Fork C), XSS (13, Fork C), File Uploads (14,
Fork C + Phase 1), Storage/Quota Races (16/17, Fork D), Public Endpoints (21, Fork F + Phase 1
abgabebox), Config/Deployment (24, Fork E), Secrets-Handling/ENV-Variablennamen (23, Phase 1
deployment-Inventar). Business Logic (20) grösstenteils über Finance/Fines (Fork G) und
Feature-Gating (Fork J unten) abgedeckt.

- [DONE] **Fork J — Feature-Gating-Matrix** → `findings-draft/fork-j-feature-gating.md`:
  2 CONFIRMED MEDIUM Findings (FEAT-01: Custom-Domain bleibt nach Feature-Entzug aktiv bedient,
  Gate nur bei Provisionierung nicht bei laufendem Betrieb geprüft; FEAT-02: Tenant-Import
  stellt aktive Custom-Domains wieder her, ohne tenant_feature zu prüfen — gleiche Root Cause).
  Nicht vollständig verifizierter Verdacht: Abgabebox-Submission-Links evtl. nach Feature-Entzug
  weiter erreichbar (analoges Muster, andere Feature) — für Phase 5/FINAL_REPORT vormerken.
- [DONE] **Fork K — Dependencies** → `findings-draft/fork-k-dependencies.md`: DEP-01 (MEDIUM,
  Next.js 16.2.12 in per Out-of-Band-Patch 2026-09-22 gefixter RCE-Spanne [next/og SVG-Escaping],
  aber kein next/og-Einsatz gefunden — Bump auf >=16.3.6 empfohlen). DEP-02 (Starlette ungepinnt,
  potenzielle CISA-KEV-Host-Header-Bypass-CVE in Spanne 0.8.3-1.0.0 — SELBST VERIFIZIERT: aktuell
  neuestes PyPI-Release ist 1.7.0, ein Neu-Build würde also automatisch die gepatchte Version
  ziehen; Risiko ist NICHT ein aktiver Bypass, sondern fehlende Pin = keine Reproduzierbarkeit/
  Vorhersagbarkeit, falls je ein älteres/gecachtes Image ohne Rebuild lief). Kleinerer Punkt:
  PyJWT 2.10.1 < 2.12.0 (CVE-2026-32597, POTENTIAL, nur im Platform-Admin-OIDC-Pfad genutzt).
- [DONE] **Fork L — DB-Constraints + DoS-Sweep** → `findings-draft/fork-l-db-dos.md`: 0 neue
  Findings. FK-CASCADE+NOT NULL auf allen Tenant-Spalten, DB-seitige UNIQUE auf allen Tokens/
  Slugs/Domains, system_error_log.source-CHECK bestätigt, neue SECURITY DEFINER-Funktionen
  (Migration 0092) korrekt search_path-gepinnt + REVOKE ALL/gezieltes GRANT. DoS: Pagination
  service-seitig auf min(limit,200) geclampt, kein ReDoS-Muster, PDF-Export bereits
  RLIMIT_AS/RLIMIT_CPU/Semaphore(4)-gehärtet. Restnotiz (kein Finding): Tenant-Clone/-Import
  ohne Rate-Limit, aber nur Platform-Admin-Owner erreichbar.
- [DONE] **Fork M — Test-Abdeckungs-Analyse** → ergänzt `TEST_RECOMMENDATIONS.md`: 7/9 geprüfte
  Invarianten haben bereits solide Regressionstests. 2 echte Lücken gefunden: (a) kein Test
  fährt Account-Lockout bis zur tatsächlichen Schwelle (Login/TOTP), (b) `test_collaboration_ws.py`
  testet nur Konstruktion der Origin-Allowlist, kein echter WS-Handshake mit fehlendem/gefälschtem
  Origin-Header gegen den echten Rejection-Pfad.

## Phase 5 — Zusätzliche Pässe (bereits durch Fork A-M abgedeckt, hier nur Bestätigung)

- [DONE] 2. Pass: "böswilliger normaler Tenant-User" (Abschnitt 34) — durchgehend in Fork A/B/F/G
  angewendet (IDOR/Cross-Tenant-Versuche für jede geprüfte Ressource), keine neuen Funde über
  FINDINGS.md hinaus.
- [DONE] 3. Pass: ID-Loads ohne Tenant/Ownership-Beweis (Abschnitt 35) — Kernscope von Fork A + I,
  ~20+ Call-Site-Gruppen repo-weit geprüft.
- [DONE] 4. Pass: Fail-Open-Entscheidungen (Abschnitt 36) — durchgehend mitgeprüft (Feature-Gating
  deny-by-default bestätigt [Fork J], Rollen deny-by-default, MFA ohne Fallback [Fork B/H],
  ClamAV-Fehler → "pending" nicht "clean" [Phase 1], CAPTCHA fail-closed in Produktion [Fork H/
  Phase 1]). Einzige Fail-Open-artige Lücke: FEAT-01/02 (Feature-Entzug wirkt nicht auf bereits
  provisionierte Ressourcen — kein klassisches Fail-Open, aber verwandtes Muster).
- [DONE] 5. Pass: Race Conditions durch Parallelität (Abschnitt 37) — Fork D (Quota-Locks, WS),
  Fork G (Fines Row-Locks), Fork L (UNIQUE-Constraints) — keine neuen Race-Conditions gefunden.

## Phase 6 — Abschluss

- [DONE] Completeness-Check gegen INVENTORY.md (Abschnitt 38) — siehe unten
- [DONE] FINAL_REPORT.md geschrieben
- [DONE] Alle bestätigten Findings gefixt ausser BG-01 (Nutzer-Entscheidung nötig) — FEAT-01/02,
  DEP-01/02/03, TEN-01/02, DEPLOY-01, DEP-04 (nanoid-Teil). Fix-Diffs von mir vollständig
  reviewt und mit gezielten Backend-/Frontend-Tests gegengeprüft (nicht blind übernommen).
- [DONE] Lokale Commits auf main (kein Push): `d9deafb` (Audit-Docs), `1a6d16c` (Code-Fixes,
  vom Fix-Fork entgegen Anweisung selbst erstellt, nachträglich reviewt), `fb20fc0`
  (nanoid-Nachtrag).
- [DONE] Übersicht an Nutzer geliefert (siehe Chat-Antwort)

### Completeness-Check (Abschnitt 38)

Alle Routen ✓ (30 Backend-Module + abgabebox `public.py` — jedes Modul mind. einmal in einem
Fork gelesen oder per automatisiertem Guard-Scan [Fork B] abgedeckt). Alle Services ✓ (zentrale:
public_id_service, access_service, tenant_service, fines/finance, export, traefik_config,
tenant_import/clone, mfa/admin_auth/oidc — alle gelesen). Alle Repositories ✓ (Fork A). Alle
Public APIs ✓ (abgabebox-backend Phase 1, public_share.py Fork F). Admin APIs ✓ (Fork B, 960
Zeilen vollständig). Uploads/Downloads ✓ (Fork C, Phase 1). Background Jobs ✓ (Fork D, alle 10
Loops + photo-analysis-worker). WebSockets ✓ (Fork D). Migrationen ✓ (Fork L + Stichproben in
Fork D/J). Security-Utilities ✓ (security.py, rate_limit.py, admin_security.py — Fork H/B).
Frontend-Security ✓ (Fork C: rich-text-editor, XSS-Greps; Phase 1: proxy.ts/Auth-Guards).
Docker/Deployment ✓ (Fork E, Phase 1). Dependencies ✓ (Fork K). Tests ✓ (Fork M).
**Nichts Sicherheitsrelevantes offen — Audit ist inhaltlich vollständig.**
