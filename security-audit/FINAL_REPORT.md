# hocX Security Audit — Abschlussbericht

## Executive Summary

Vollständiges, repository-weites Security Audit von hocX (Backend, Abgabebox-Backend,
Photo-Analysis-Worker, Frontend, Abgabebox-Frontend, Deployment/Infra/CI). 13 parallele
Tiefenprüfungs-Durchläufe (Fork A-M) über alle im Auftrag geforderten Abschnitte.

| Severity | Anzahl | IDs |
|---|---|---|
| Critical | 0 | — |
| High | 0 | — |
| Medium | 3 | BG-01, FEAT-01, FEAT-02 |
| Medium (Dependency) | 1 | DEP-01 |
| Needs-Verification | 1 | DEP-02 |
| Low | 2 | TEN-01, DEPLOY-01 |
| Potential/Low | 1 | DEP-03 |
| Info | 4 | TEN-02, WS-01, PUB-01, `/bridge`-Notiz |
| Gemischt (teils behoben) | 1 | DEP-04 (npm audit, erst bei Fix-Verifikation entdeckt) |

**Wichtigstes Ergebnis:** Dieses Repository wurde bereits mehrfach zuvor auditiert (sichtbar an
Dutzenden `# audit finding ...`-Kommentaren im Code, datiert 2026-08-16 bis 2026-09-24, sowie an
CHANGELOG-Einträgen zu "13 kritische Befunde, alle behoben"). Die in diesem Audit als Phase-1-
Hypothese eingestufte höchste Sorge — ein systemisches Tenant-Isolation-IDOR über
`public_id_service.get_by_public_id` — hat sich bei der Tiefenprüfung **nicht** bestätigt: alle
~20 geprüften Call-Site-Gruppen über 10+ Dateien haben einen korrekten, nachgelagerten
Tenant-/Ownership-Check. Die Codebase ist an praktisch jeder geprüften Stelle deutlich robuster
als der erste Eindruck vermuten liess.

Die tatsächlich gefundenen Probleme liegen nicht in klassischer Authorization/Injection, sondern
in zwei spezifischeren Kategorien: (1) **Feature-Gating als "Gate bei Provisionierung" statt
"Invariante über die Ressourcen-Lebensdauer"** (FEAT-01/02) und (2) **Observability-Lücke bei
einem dritten, separat konzipierten Service** (BG-01). Dazu zwei Dependency-Hygiene-Punkte
(DEP-01/02).

## Scope

- Repository: FrissBrot/hocX
- Branch: `main`
- Audit-Start-Commit: `705ac3e990d6b9b2ff47b7cd4f932dde46879941`
- Audit-Zeitraum: 2026-09-30, eine durchgehende Session mit 13 parallelen Tiefenprüfungs-Forks
  (A-M) über 4 Phasen (Inventar → Kernmodell → Flächen → Zusatzpässe)

## Architecture & Trust Boundaries / Security Model / Attack Surface

Siehe `SECURITY_MODEL.md` und `ATTACK_SURFACE.md` für die vollständige Rekonstruktion (Actors,
Assets, Trust Boundaries, Invarianten I1-I11, Endpoint-Tabellen). Kurzfassung: 6 Komponenten
(`backend`, `abgabebox-backend`, `photo-analysis-worker`, `frontend`, `abgabebox-frontend`,
Deployment), 3 Postgres-Rollen mit unterschiedlichen Privilegien (`hocx_app`, `hocx_abgabebox`
restricted, `hocx_photo_worker` restricted), 2 komplett getrennte Auth-Systeme (Tenant-User via
Session-Cookie/Rolle aus DB, Platform-Admin via separates Cookie/Secret/MFA-Zwang), 1 echte
öffentliche Grenzfläche im Hauptbackend (`public_share.py`) plus die vollständig öffentliche
Abgabebox.

## Security Invariant Matrix

| Invariante | Enforcement | Status | Evidence |
|---|---|---|---|
| I1: Rolle serverseitig, nie aus Client | `build_current_user` | ✅ Hält | `security.py:141-165` |
| I2: Tenant-Isolation (eigene `tenant_id`-Spalte) | `get_by_public_id(tenant_id=...)` | ✅ Hält | Fork A |
| I3: Tenant-Isolation (transitiv gescopt) | `access_service`/`access_repository`-Checks | ✅ Hält (widerlegt als Risiko) | Fork A, C, I |
| I4: Rollen-/Feature-Gate pro Route | `require_*`-Aufruf | ✅ Hält (kein Dependency-Zwang, aber konsistent angewendet) | Fork B |
| I5: Platform-Admin getrennt | separates Auth-System, MFA-Zwang | ✅ Hält | Fork B |
| I6: Abgabebox Tenant-Scoping über Link-Token | `repository.py`-Queries | ✅ Hält | Phase 1, Fork D |
| I7: Storage-Quota race-frei | Advisory-Locks (per-Tenant) | ✅ Hält (Phase-1-Fehleinschätzung korrigiert) | Fork D |
| I8: Background-Fehler → `system_error_log` | `record_system_error`/`insert_error_log` | ⚠️ Lücke bei photo-analysis-worker | **BG-01** |
| I9: CAPTCHA fail-closed in Produktion | `captcha_enabled()`-Gate | ✅ Hält | Fork H, Phase 1 |
| I10: Public-Token nicht erratbar | `secrets.token_urlsafe` (192 Bit) | ✅ Hält | Fork F, Phase 1 |
| I11: Client-Flags nie alleinige Entscheidung | Backend prüft immer erneut | ✅ Hält | durchgehend |
| I12 (neu): Feature-Gate gilt über gesamte Ressourcen-Lebensdauer | — | ❌ Lücke bei `custom_domain` | **FEAT-01, FEAT-02** |

## Findings

Siehe `FINDINGS.md` für alle Details (Format nach Audit-Abschnitt 27, inkl. False-Positive-Check
nach Abschnitt 28). Zusammenfassung:

### Medium
- **BG-01**: `photo-analysis-worker`-Fehler erreichen `system_error_log` nie (DB-Rolle hat auch
  kein GRANT dafür). **Entscheidung von dir nötig** (siehe unten).
- **FEAT-01**: Aktive Custom-Domains bleiben nach Entzug des `custom_domain`-Features unbegrenzt
  funktional (Traefik + Health-Check prüfen das Feature nicht erneut).
- **FEAT-02**: Tenant-Import stellt aktive Custom-Domains wieder her, ohne dass der neue Tenant
  das Feature je gebucht hat (gleiche Root Cause wie FEAT-01).
- **DEP-01**: Next.js 16.2.12 in per Out-of-Band-Patch gefixter RCE-Spanne — aktuell nicht
  ausnutzbar (kein `next/og`/`ImageResponse`-Einsatz), Update trotzdem empfohlen.

### Needs-Verification
- **DEP-02**: Starlette ungepinnt, potenzielle CISA-KEV-Host-Header-Bypass-CVE — aus dem Repo
  allein nicht abschliessend verifizierbar, ob das produktiv laufende Image betroffen ist.

### Low / Potential
- **TEN-01**: 4 tote, ungescopte Repository-Wrapper-Methoden (Footgun für die Zukunft).
- **DEPLOY-01**: `ci.yml` ohne `permissions:`-Block.
- **DEP-03**: PyJWT 2.10.1 < 2.12.0, Risiko auf Platform-Admin-OIDC-Login begrenzt.

### Info
- **TEN-02**: veralteter Docstring in `public_id_service.py`.
- **WS-01**: WebSocket-Origin-Allowlist nicht tenant-gescoped (kein ausnutzbarer Bypass gefunden).
- **PUB-01**: `/api/clamav/status` zeigt Scanner-Version tenant-unabhängig (geteilte Infra).
- `/bridge`-Endpoint: theoretisches Login-CSRF-Muster, durch Token-Design selbst-limitierend.

## Missing Security Tests

Siehe `TEST_RECOMMENDATIONS.md`. Wichtigste zwei echte Lücken: Account-Lockout-Schwellenwert-Test
(Login/TOTP) und WebSocket-Origin-Handshake-Rejection-Test. Alle anderen stichprobenartig
geprüften Invarianten haben bereits Regressionstests.

## Recommended Remediation Order

1. **FEAT-01** zuerst (schliesst FEAT-02 wahrscheinlich automatisch mit) — Business-Logic-Bypass
   mit direktem finanziellem Impact, einfacher Fix (1 JOIN in 2 Funktionen).
2. **DEP-01** (Next.js-Patch) — kostenloser Patch-Versionssprung, kein Blast-Radius-Risiko.
3. **DEP-02/DEP-03** (Dependency-Pins) — kostenlose Fixes, schliessen strukturelle Unsicherheit.
4. **TEN-01, DEPLOY-01, TEN-02, WS-01** — Low/Info, geringer Aufwand, im selben Rutsch erledigbar.
5. **BG-01** — **braucht deine Entscheidung** zwischen zwei Architektur-Optionen (siehe unten),
   danach einfache Umsetzung.

## Residual Risk (nicht statisch beweisbar)

- **DEP-02**: erfordert Runtime-Inspektion des tatsächlich produktiv laufenden Backend-Images
  (`pip show starlette` im Container) — der Container lief zum Audit-Zeitpunkt nicht.
- **Branch-Protection-Regeln für `main`**: aus dem Repo-Inhalt nicht einsehbar (GitHub-Repo-
  Settings), relevant für die Frage "kann jemand die CI/Secret-Scan-Kette umgehen, indem er
  direkt auf `main` pusht".
- Race-Condition-Verifikation erfolgte überall statisch (Postgres-Advisory-Lock-Semantik ist
  deterministisch ableitbar) — ein Live-E2E-Test wurde bewusst nicht durchgeführt, da er laut
  Fork D keine zusätzliche Information geliefert hätte. Falls du das anders siehst, ist ein
  praktischer Zwei-Prozess-Test gegen `./scripts/e2e.sh up` jederzeit nachrüstbar.

## Audit Coverage

Alle Komponenten aus `INVENTORY.md` mindestens `REVIEWED`, mehrere `REVIEWED_WITH_FINDINGS`.
Vollständiger Completeness-Check in `TODO.md` (Abschnitt "Completeness-Check"). Nicht vertieft
(bewusst, geringe Priorität): `docs-site/` (öffentliche, nicht-sensible Dokumentation),
`design/` (kein Backend-Zugriff, keine sicherheitsrelevante Logik).
