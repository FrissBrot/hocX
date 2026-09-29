# FINDINGS

Konsolidiert aus `findings-draft/fork-a..e-*.md` (Phase 2, 2026-09-30). Reihenfolge:
Critical → High → Medium → Low → Info. Bisher **keine Critical/High** gefunden — die in
Phase 1 als höchstes Risiko eingestufte Tenant-Isolation-Hypothese (I3) hat sich bei der
Tiefenprüfung NICHT bestätigt.

---

## [BG-01] [MEDIUM] photo-analysis-worker-Fehler erreichen `system_error_log` nie

Status: **CONFIRMED**
CWE: CWE-778 (Insufficient Logging)

Betroffene Dateien/Funktionen: `photo-analysis-worker/app/worker.py::run()`/`_process_job()`
(Zeilen 28-69), `backend/alembic/versions/0067_photo_analysis_job.py` (Zeilen 86-102, GRANTs)

### Security Invariant
I8 — unerwartete Backend-Fehler landen zentral in `system_error_log`, sichtbar im
Platform-Admin-Panel (CLAUDE.md, "Zentrale Fehlererfassung").

### Beschreibung
`run()` fängt jede Exception aus `_process_job()` nur mit `logger.exception(...)` (Container-Log)
und markiert den Job als `failed`. Kein Aufruf von `record_system_error`/Äquivalent. Selbst ein
naiver Nachtrag würde scheitern: die Postgres-Rolle `hocx_photo_worker` hat laut Migration `0067`
kein GRANT auf `system_error_log` (nur `stored_file`, `photo_analysis_job`).

### Root Cause
Der Worker wurde als separater, minimal-privilegierter Prozess konzipiert; die zentrale
Fehlererfassungs-Konvention wurde bei diesem dritten Service (anders als bei
`abgabebox-backend`) nicht mitgezogen.

### Preconditions
Keine — jeder Verarbeitungsfehler (auch durch harmlos-defekte Bilder) landet im blinden Fleck.
Angreifer mit Upload-Rechten (Tenant-User oder Abgabebox-Uploader) profitieren davon, dass
gezielte/wiederholte Angriffsversuche gegen den Bildparser (OpenCV/onnxruntime) nirgends
zentral sichtbar werden.

### Impact
MEDIUM — Observability/Detection-Gap für einen Service, der nicht vertrauenswürdigen Input aus
zwei Upload-Pfaden verarbeitet. Kein direkter Datenverlust/Zugriffsverstoss.

### Existing Mitigations
`logger.exception` (Container-Log), `photo_analysis_job.error` (DB-persistiert, aber ohne
bündelnde Admin-UI).

### Why Insufficient
CLAUDE.md verlangt explizit das Platform-Admin-Panel als einzigen vorgesehenen Weg; Container-Logs
werden dort nicht gebündelt/alarmiert.

### Recommended Fix — **Entscheidung des Nutzers erforderlich** (Architektur-Frage)
(a) `hocx_photo_worker` ein eng gefasstes `GRANT INSERT (...) ON system_error_log` geben + neuer
erlaubter `source`-Wert `"photo-analysis-worker"` (CHECK-Constraint in `sql/baseline_schema.sql`
UND `SOURCE_LABELS` in `admin-error-log.tsx` müssten synchron erweitert werden) — weicht das
Least-Privilege-Konzept der Rolle leicht auf.
(b) Ein Backend-Loop pollt periodisch `photo_analysis_job.status='failed'` und ruft
`record_system_error` stellvertretend mit vorhandenem `source="backend"` auf — kein neues GRANT
nötig, aber ein neuer Loop/eine neue Zuständigkeit im Hauptbackend.

### Regression Test
Job mit garantiert fehlschlagendem `_process_job` laufen lassen, verifizieren dass ein
`system_error_log`-Eintrag (bzw. gewählter Ersatzmechanismus) mit korrektem `source` entsteht.

### Evidence
`photo-analysis-worker/app/worker.py:63-69`; `backend/alembic/versions/0067_photo_analysis_job.py:86-102`.

---

## [FEAT-01] [MEDIUM] Aktive Custom-Domains bleiben nach Feature-Entzug unbegrenzt funktional

Status: **CONFIRMED**
CWE: CWE-862 (Missing Authorization) / Business-Logic-Bypass eines Paid-Features

Betroffene Dateien/Funktionen: `backend/app/services/admin_tenant_service.py::update_tenant_features`
(Z. 423-440), `backend/app/services/traefik_config_service.py::regenerate` (Z. 104-111),
`backend/app/services/domain_health_check_service.py::run_health_check` (Z. 12-18)

### Security Invariant
Ein deaktiviertes Feature darf nicht weiter nutzbar bleiben — auch nicht über eine bereits
provisionierte Ressource.

### Beschreibung
`require_feature(actor, "custom_domain")` wird NUR beim Anlegen (`create_domain`) und
Verifizieren (`verify_domain`) einer Domain geprüft. Sobald eine Domain `status='active'`
erreicht hat, prüft keiner der Pfade, die sie am Leben halten, das Feature erneut:
`traefik_config_service.regenerate()` und `domain_health_check_service.run_health_check()`
selektieren beide nur `WHERE status='active'`, ohne Join gegen `tenant_feature`.
`update_tenant_features()` (Feature-Entzug durch Platform-Admin) löscht nur die
`TenantFeature`-Zeile, rührt `TenantDomain` nicht an.

### Attack Path (Ablauf, der sich von selbst ergibt — kein Angreifer nötig)
1. Tenant hat `custom_domain` gebucht, Domain aktiv/verifiziert.
2. Feature wird entzogen (Downgrade oder manuelle Admin-Aktion).
3. `TenantDomain` bleibt `status='active'`.
4. Traefik routet weiterhin, Health-Check hält sie "gesund" — unbegrenzt, ohne dass das Feature
   bezahlt/gebucht ist. Erst ein manuelles `DELETE .../domains/{id}` (bewusst ohne Feature-Gate,
   damit nach Downgrade überhaupt löschbar) beendet die Nutzung — nirgends automatisch gekoppelt.

### Impact
MEDIUM — Business-Logic/Payment-Bypass, kein Cross-Tenant-Datenzugriff (Tenant sieht nur eigene
Daten, nur über eine nicht mehr bezahlte Domain). Schaden proportional zu betroffenen
Tenants/Dauer.

### Recommended Fix
`regenerate()` und `run_health_check()` zusätzlich gegen `tenant_feature` joinen und
Domains ohne aktives Feature auslassen (kleinerer Eingriff: 1 JOIN in 2 Funktionen) — deckt
FEAT-02 (unten) automatisch mit ab, da beide über dieselbe Logik laufen. Alternativ:
`update_tenant_features` setzt bei Entzug betroffene Domains auf einen neuen Status
`suspended` (reaktivierbar ohne erneute DNS-Verifikation beim Wieder-Zubuchen).

### Regression Test
Tenant mit aktiver, verifizierter Custom-Domain; Feature entziehen; verifizieren, dass die
Domain NICHT mehr im generierten Traefik-Router-Config auftaucht.

### Evidence
`admin_tenant_service.py:423-440`; `traefik_config_service.py:104-111`;
`domain_health_check_service.py:12-18`.

---

## [FEAT-02] [MEDIUM] Tenant-Import stellt aktive Custom-Domains wieder her, ohne dass das Feature je gebucht wurde

Status: **CONFIRMED** (Spezialfall von FEAT-01, gleiche Root Cause)
CWE: CWE-862

Betroffene Datei/Funktion: `backend/app/services/tenant_import_service.py::_import_tenant_domains`
(Z. 419-451), aufgerufen aus `_run()` (Z. 193) VOR jeder Feature-Zuweisung.

### Beschreibung
Tenant-Import (Platform-Admin-only, ZIP-Restore) übernimmt `TenantDomain`-Zeilen der Quelle 1:1
inkl. `status='active'` und ruft sofort `regenerate()` auf. Der komplette Import-Code enthält
keine Referenz auf `TenantFeature` — der neue Tenant hat nach Import keine Feature-Zeilen (also
kein `custom_domain` gebucht), besitzt aber bereits eine voll funktionsfähige, aktiv geroutete
Domain. `tenant_clone_service.py` ist NICHT betroffen (rührt `TenantDomain` nie an, verifiziert
per grep: 0 Treffer).

### Impact
MEDIUM — wie FEAT-01, zusätzlich überraschend für Admins ("Import hat versehentlich ein
Paid-Feature freigeschaltet").

### Recommended Fix
Dieselbe Fix-Richtung wie FEAT-01: sobald `regenerate()`/Health-Check das Feature prüfen, ist
dieser Fall automatisch mitgeschlossen — FEAT-01 zuerst umsetzen, danach FEAT-02 gegenprüfen
(voraussichtlich bereits geschlossen).

### Regression Test
Tenant-Export mit aktiver Custom-Domain in eine Installation ohne `custom_domain`-Feature
importieren; verifizieren, dass die Domain nicht im generierten Traefik-Config auftaucht.

### Evidence
`tenant_import_service.py:419-451,187-193`; Gegenprobe `tenant_clone_service.py` (0 Treffer für
`domain`).

### Verwandter, nicht abschliessend verifizierter Verdacht (für spätere Nachprüfung)
Analoges Muster evtl. bei `abgabebox`: bleiben bestehende Submission-Assignments über den alten
Link-Token erreichbar, nachdem das `abgabebox`-Feature einem Tenant entzogen wurde? Fork J hat
dies nicht abschliessend geprüft (Fokus lag auf `custom_domain`) — als Nachfolge-Check vermerkt,
kein bestätigtes Finding.

---

## [DEP-01] [MEDIUM] Next.js 16.2.12 liegt im Versionsbereich einer kritischen RCE (aktuell nicht ausnutzbar)

Status: CONFIRMED (Versions-Match), Impact aktuell NICHT ausnutzbar (verwundbares Feature ungenutzt)
CWE: CWE-1104

Betroffene Dateien: `frontend/package.json`, `abgabebox-frontend/package.json` (beide `next=16.2.12`)

### Beschreibung
Next.js-Advisory vom 22.09.2026 (Out-of-Band-Release 16.3.6): Versionen `>=16.2.0 <16.3.6` haben
eine RCE über `next/og`/`ImageResponse` (fehlerhaftes SVG-Escaping via Satori). Beide Frontends
pinnen exakt `16.2.12`.

### False-Positive-Check
`grep -rn "next/og\|ImageResponse"` (ausserhalb `node_modules`) → **kein Treffer** in beiden
Frontends. Der konkrete RCE-Pfad ist aktuell nicht erreichbar.

### Impact
Aktuell kein ausnutzbarer Pfad. Next.js 16.2.x hatte aber mehrere kritische Advisories in
kurzer Folge — Update ist trotz aktuell fehlendem Exploit-Pfad sinnvoll, bevor das Feature
versehentlich später genutzt wird.

### Recommended Fix
`next` in beiden `package.json` auf `>=16.3.6` anheben (reiner Patch-Versionssprung), danach
Playwright-E2E-Suiten laufen lassen.

### Evidence
`frontend/package.json`, `abgabebox-frontend/package.json`; Next.js-Advisory GHSA-vcvr-r3jv-pc5j
(22.09.2026).

---

## [DEP-02] [NEEDS_VERIFICATION] Starlette ungepinnt — potenzielle CISA-KEV-Host-Header-Bypass-CVE, tatsächliche Produktionsversion aus dem Repo nicht bestimmbar

Status: NEEDS_VERSION_VERIFICATION (Runtime-Check nötig, nicht aus Code allein lösbar)
CWE: CWE-1395 — konkrete CVE: CVE-2026-48710 ("BadHost"), CVSS 6.5, seit 2026-09-02 in der
CISA-KEV-Liste (aktiv ausgenutzt in freier Wildbahn)

Betroffene Datei: `backend/requirements.txt` (`fastapi==0.140.0`, kein `starlette==`-Pin)

### Beschreibung
CVE-2026-48710 ist ein Host-Header-Auth-Bypass in Starlette `0.8.3`–`1.0.0` (gefixt in `1.0.1`,
21.05.2026). FastAPI `0.140.0` verlangt nur `starlette>=0.46.0` ohne Obergrenze — die tatsächlich
beim Image-Build aufgelöste Version hängt vom Build-Zeitpunkt ab, nicht von einer im Repo
fixierten Version. **Selbst verifiziert**: das aktuell neueste PyPI-Release ist `1.7.0` (weit
über der Fix-Version) — ein Neu-Build heute würde also automatisch eine sichere Version ziehen.
Das Risiko ist daher nicht ein aktiver Bypass im Normalfall, sondern die fehlende
Reproduzierbarkeit/Vorhersagbarkeit: ohne Pin ist nicht aus dem Repo ableitbar, welche Version
in einem älteren, ggf. nicht neu gebauten Produktions-Image tatsächlich läuft.

### Warum hier besonders relevant
Die App hat ein Custom-Domain-Feature (Host-Header-basiertes Routing). Falls ein Backend-Code-
Pfad `request.url`/`request.base_url`/`request.headers["host"]` für eine Security-Entscheidung
nutzt (nicht nur Logging/Link-Generierung), wäre ein Host-Header-Bypass wirkungsvoller als im
Durchschnittsfall — diese spezifische Frage wurde in diesem Fork nicht verifiziert (Cross-Check
empfohlen).

### Preconditions
Nur relevant, falls die tatsächlich deployte Starlette-Version im Bereich `0.8.3`–`1.0.0` liegt
UND ein Code-Pfad existiert, der sich auf den Host-Wert für eine Security-Entscheidung verlässt.

### Recommended Fix
1. `starlette>=1.0.1` explizit in `backend/requirements.txt`/`abgabebox-backend/requirements.txt`
   pinnen (kostenloser Fix, schliesst die Unsicherheit strukturell).
2. Tatsächlich laufendes Produktions-Image inspizieren (`pip show starlette` im Container) —
   ausserhalb der Möglichkeiten dieses Code-Audits (Backend-Container lief zum Prüfzeitpunkt
   nicht). **Residual Risk für FINAL_REPORT.**

### Evidence
`backend/requirements.txt:1`; FastAPI-Changelog (`starlette>=0.46.0` ohne Obergrenze seit 0.136.3);
CVE-2026-48710 (CISA KEV, Fix in 1.0.1); PyPI-Check in dieser Session: neuestes Release `1.7.0`.

---

## [DEP-03] [POTENTIAL/LOW] PyJWT 2.10.1 unter Fix-Version, Risiko auf Platform-Admin-OIDC-Login begrenzt

Status: POTENTIAL (geringes Risiko, begrenzte Angriffsfläche)
CWE: CVE-2026-32597 (`crit`-Header-Parameter aus RFC 7515 wird nicht validiert)

Betroffene Datei: `backend/requirements.txt` (`PyJWT[crypto]==2.10.1`, Fix in `2.12.0`)

### Beschreibung
Genutzt ausschliesslich in `platform_oidc_service.py` (Platform-Admin-SSO/OIDC-Login,
`jwt.decode()` auf ID-Tokens vom konfigurierten IdP). Der reguläre Session-Token-Mechanismus
(`core/security.py`) nutzt PyJWT nicht (eigenes HMAC-Schema). Risiko begrenzt auf den optionalen
OIDC-Login-Pfad, erfordert Kontrolle über IdP/ID-Token-Inhalt.

### Recommended Fix
`PyJWT>=2.12.0` — risikoarmer Hygiene-Fix.

### Evidence
`backend/requirements.txt`; `platform_oidc_service.py`.

---

## [TEN-01] [LOW] Ungenutzte, ungescopte `get_by_public_id`-Repository-Wrapper (toter Code, künftiger Footgun)

Status: CONFIRMED (Hardening-Finding, aktuell kein Exploit-Pfad — Code ist unreachable)
CWE: CWE-1164 / defense-in-depth gegen künftiges CWE-639 (IDOR)

Betroffene Dateien: `app/repositories/user_repository.py::get_by_public_id` (AppUser),
`app/repositories/protocol_element_repository.py::get_by_public_id` (×2: ProtocolElement,
ProtocolElementBlock), `app/repositories/file_repository.py::get_by_public_id` (ProtocolImage)

### Beschreibung
Alle vier Methoden rufen `public_id_service.get_by_public_id` ohne `tenant_id=` auf. Aktuell ruft
sie **niemand** auf (verifiziert per repo-weitem grep) — alle echten Routen nutzen stattdessen
`public_id_service.get_by_public_id(...)` direkt + nachgelagerten `access_service`-Check.

### Attack Path (hypothetisch, aktuell nicht erreichbar)
Ein künftiger Entwickler ruft eine dieser Methoden aus einer neuen Route auf, in der
(fälschlichen) Annahme, sie sei wie die meisten anderen `*Repository.get_by_public_id`-Methoden
(z. B. `EventRepository`, `ParticipantRepository`) bereits tenant-scoped — sie nehmen `tenant_id`
als Pflichtparameter, diese vier nicht. Ergebnis: Cross-Tenant-IDOR.

### Impact
Aktuell keiner (unreachable). Bei künftiger Fehlbenutzung: Cross-Tenant-Leck, Schwere je nach
Modell (AppUser: E-Mail/Rolle; ProtocolElement/-Block/-Image: Protokollinhalte fremder Mandanten).

### Recommended Fix
Diese vier Methoden entweder löschen (kein Aufrufer — einfachste, empfohlene Option) oder
`tenant_id` zum Pflichtparameter machen und intern den passenden `access_repository`-Join
durchführen.

### Regression Test
Falls Löschung: keiner nötig. Falls Parameter-Pflicht: Unit-Test, der belegt, dass
`get_by_public_id` mit `tenant_id=<falscher Tenant>` `None` zurückgibt.

### Evidence
`grep -rn "UserRepository().get_by_public_id\|protocol_element_repository\.\|FileRepository().*ProtocolImage" backend/app`
→ nur die Definitionen selbst, keine Aufrufer.

---

## [DEPLOY-01] [LOW] `ci.yml` ohne workflow-weiten `permissions:`-Block

Status: CONFIRMED
CWE: CWE-276 (Incorrect Default Permissions)

Betroffene Datei: `.github/workflows/ci.yml`

### Beschreibung
Im Gegensatz zu `release.yml`/`build-test-images.yml` setzt `ci.yml` keinen `permissions:`-Block
— Repository-Default-Rechte gelten statt eines im Code nachvollziehbaren Minimalsatzes. Trigger
ist `pull_request`/`push` auf `main`, nicht `pull_request_target`; kein Job nutzt aktuell
Schreib-Aktionen — kein bestätigter Bypass, reines Defense-in-Depth-Gap.

### Impact
Nur relevant, falls Repo-Default grosszügiger als `read` ist UND ein künftiger Job versehentlich
eine schreibende Aktion bekommt.

### Recommended Fix
```yaml
permissions:
  contents: read
```
direkt nach `on:` ergänzen, analog zu `release.yml`/`build-test-images.yml`.

### Evidence
`.github/workflows/ci.yml:1-9` (kein `permissions:`); Gegenprobe `release.yml:24`,
`build-test-images.yml:6`.

---

## [WS-01] [LOW/INFO] WebSocket-Origin-Allowlist ist nicht tenant-gescoped (Verbesserungsvorschlag, kein bestätigter Bypass)

Status: NEEDS_VERIFICATION als Bypass wurde geprüft und **verworfen** — als
Defense-in-Depth-Empfehlung trotzdem aufgenommen.

Betroffene Datei: `backend/app/api/routes/collaboration_ws.py:161-200`

### Beschreibung
`_active_app_domain_origins()` akzeptiert JEDE aktive Custom-Domain über ALLE Tenants als
gültigen WS-`Origin`, statt nur die Domain(s) des Tenants der Zielressource. Kein ausnutzbarer
Bypass gefunden: exakter String-Match (kein Wildcard), fail-closed bei fehlendem Origin, Domain
erfordert vorherige echte DNS-Verifikation, und `SameSite=Lax`-Cookie verhindert ohnehin, dass
das Session-Cookie bei einer Cross-Origin-WS-Verbindung mitgeschickt wird.

### Recommended Fix (Verbesserung, keine Pflicht)
`_active_app_domain_origins()` könnte zusätzlich den `tenant_id` der Zielressource kennen und nur
deren eigene Domain(s) akzeptieren, um die Sicherheitseigenschaft nicht implizit von
`SameSite=Lax` abhängig zu machen (z. B. falls ein künftiges Feature `SameSite=None` erfordert).

### Evidence
`collaboration_ws.py:161-200`; `security.py` (Cookie-Attribute); `domain_verification_service.py::verify_domain`.

---

## [TEN-02] [INFO] Veralteter Docstring in `public_id_service.py`

Status: CONFIRMED (reine Dokumentation, kein Sicherheitsfund)

Betroffene Datei: `app/services/public_id_service.py` (Zeilen 14-21)

### Beschreibung
Docstring nennt `StoredFile`/`ProtocolTodo` als Beispiele für "kein eigenes tenant_id" — beide
haben inzwischen eine eigene `tenant_id`-Spalte. Nur `ProtocolElement`/`ProtocolElementBlock`
(und ungeprüft `ProtocolImage`/`ProtocolText`/`ProtocolDisplaySnapshot`) sind noch transitiv
gescopt.

### Recommended Fix
Docstring aktualisieren, korrekte aktuelle Beispiele nennen.

---

## [PUB-01] [INFO] `/api/clamav/status` gibt Scanner-Version tenant-unabhängig zurück

Status: CONFIRMED (Informationsfund, keine Sicherheitsgrenze verletzt)

Betroffene Datei: `backend/app/api/routes/submission_assignments.py:375-386`

### Beschreibung
`GET /api/clamav/status` verlangt nur `require_abgabebox_read(user)`, keine Tenant-spezifische
Prüfung — ClamAV ist geteilte Infrastruktur für alle Tenants, daher zeigt jeder Tenant mit
gebuchtem Abgabebox-Feature dieselbe globale Versionsnummer. Kein Cross-Tenant-Datenleck (es gibt
keine tenant-spezifische Information, die geleakt würde), nur global statt tenant-gated.

### Impact
Sehr gering — Versionsnummer eines Open-Source-Scanners, kein Secret. Jeder Tenant-User mit
Abgabebox-Feature sieht das ohnehin für den eigenen Zweck.

### Recommended Fix
Kein Handlungsbedarf zwingend. Optional: nur `status` (online/offline) an Tenants ausgeben, volle
Version nur im Platform-Admin-Panel.

### Evidence
`submission_assignments.py:375-386`.

---

## Geprüft, kein Fund (dokumentiert gegen Doppelaufwand — siehe `findings-draft/*.md` für Details)

- Tenant-Isolation: ~20 Call-Site-Gruppen über 10 Backend-Dateien (todos, protocol_elements,
  files, submission_assignments, templates, lists, word_import, fines, users/MFA,
  protocol_todo_service, events) — überall korrekter Tenant-/Ownership-Check.
- Platform-Admin-Authorization: `admin.py` (960 Zeilen, vollständig gelesen) — router-weiter
  `Depends(get_current_admin)`, konsistente `require_admin_write`/`require_admin_owner`-Trennung,
  MFA ohne Fallback erzwungen, Open-Redirect-Schutz bei OIDC-Login solide.
  Automatisierter Guard-Scan über alle Routendateien ohne verdächtige Lücken (Restarbeit siehe TODO).
- Uploads/Injection/XSS: `gallery_upload_route.py`-Registrierung korrekt; kein blockierender
  ClamAV-Call auf Live-Request-Pfad im Hauptbackend; `files.py` durchgängig
  tenant-/ownership-gescoped; ZIP-Handling gehärtet (Galerie stark, Word-Import mit bewusster
  Restrisiko-Akzeptanz, s. `TEST_RECOMMENDATIONS.md`); Subprocess-/SQL-/SSRF-Greps sauber;
  `rich-text-editor.tsx` (Tiptap, `html:false`) kein Stored-XSS-Vektor.
- Background-Loops: alle 10 Loops korrekt an `record_system_error(source="backend")`
  angeschlossen, kein Regressions-Fund des historischen `source="background_loop"`-Bugs.
- Abgabebox Storage-Quota-Race: verschachtelte Advisory-Locks sind TOCTOU-frei (beide Locks
  per-Tenant, nicht global wie in Phase 1 fälschlich notiert).
- Migration `0088_remove_manual_storage_quota`: reiner Daten-Backfill, kein Enforcement-Gap.
- photo-analysis-worker Job-Erzeugung (`file_service.py`): `stored_file_ids` konsequent
  tenant-gefiltert, kein Cross-Tenant-Leck über Job-Payload.
- Deployment: Security-Response-Header bereits doppelt vorhanden (Next.js CSP/HSTS + Traefik),
  CORS korrekt (kein Cross-Origin-Browser-Request zum Backend dank Next.js-Proxy), Docker-Socket-
  Mount bei Traefik weiterhin notwendig, `traefik_config_service.py` gegen Rule-Injection durch
  strikte Hostname-Regex + `yaml.safe_dump` abgesichert, restliche Deploy-Skripte sauber
  (Quoting, `mktemp`+`trap`, Symlink-Ablehnung, Checksum-Pinning).
- Finance/Fines (`finance.py`/`fines.py`): Rollen-Guards passend zur Sensitivität, `kassier`-Rolle
  sauber von `writer` getrennt, ALLE 4 state-changing Fine-Operationen row-locked, Cross-Tenant
  überall blockiert (404 kollabiert Not-Found/Wrong-Tenant/Already-Collected — keine
  Enumeration), Beträge `Decimal`/`Numeric(15,2)`, saubere Fehlerbehandlung bei Overflow.
- Public Endpoints (`share_links.py`/`public_share.py`/`submission_assignments.py`):
  `submission_assignments.py` ist entgegen ursprünglicher Annahme NICHT öffentlich (überall
  `require_abgabebox_read/write`); echte unauthentifizierte Grenze ist nur `public_share.py`
  (4 Routen) — 192-Bit-Tokens, serverseitige Expiry/Revocation bei jedem Zugriff, ununterscheidbare
  404s, App-seitiges Rate-Limiting, kein IDOR über `file_id`/`upload_id`, keine Preisgabe interner
  IDs/Tenant-Metadaten.
- Export-Regression: alle 7 historischen Cross-Tenant-PDF-Export-Fixes in `export_service.py`
  intakt; `statistics.py`/`exports.py` sauber tenant-/rollen-gescoped; LaTeX-Escaping (`_escape_latex`)
  robust — kein `\input`/`\include`-Injection-Vektor über Rich-Text-Inhalte.
- Restliche Tenant-Isolation: `participant_service.py:137` durch nachgelagerten
  `_ensure_app_user_belongs_to_tenant`-Check abgesichert; `ProtocolImage`/`ProtocolText`/
  `ProtocolDisplaySnapshot` haben ausserhalb `files.py` keinen direkten Client-Resolve-Pfad
  (nur interne Joins auf bereits tenant-verifizierten IDs).
- Auth-Kernaudit (Abschnitt 7): CSRF (SameSite=Lax + JSON-only APIs ausreichend; `/bridge` als
  einziger GET-mit-Seiteneffekt selbstlimitierend durch Single-Use/60s-TTL/256-Bit-Token, siehe
  Info-Notiz unten), Rate-Limiting (Redis-backed, 2 unabhängige Schichten: Traefik-IP +
  App-seitig account-scoped), Passwort-Reset existiert bewusst nicht (keine Mail-Infra),
  Session-Revocation korrekt bei allen sicherheitsrelevanten Aktionen (inkl. Admin-MFA-Faktor-
  Löschung über frische `has_mfa_factor`-Prüfung pro Request, keine explizite Revocation nötig),
  Lockouts zeitlich begrenzt (15 Min, kein permanenter DoS), Cookie korrekt host-only (kein
  `domain=`), WebAuthn-RP-ID-Pinning-Fix von 2026-08-25 ohne Regression.

## Info-Notiz (kein Finding, zur Vollständigkeit dokumentiert)

- `/bridge`-Endpoint (Custom-Domain-Session-Bridge, `auth.py`): einziger GET mit Seiteneffekt im
  gesamten Auth-Bereich. Theoretisches "Login-CSRF"-Szenario (Angreifer teilt Opfer den eigenen
  Bridge-Link) ist durch 256-Bit-Single-Use-Token mit 60s-TTL selbst-limitierend — Impact wäre
  bestenfalls, dass das Opfer unbemerkt in der Session des Angreifers landet, kein Zugriff auf
  Opfer-Daten.

## Geprüft, kein Fund — Phase 4 (Welle 3: Feature-Gating, Dependencies, DB/DoS, Tests)

- Feature-Gating: nur 3 Feature-Codes im System (`finance`, `abgabebox`, `custom_domain`).
  `finance`/`abgabebox` API-Ebene durchgehend korrekt gegated (Cross-Ref Fork G/F), kein Bypass.
  `custom_domain` Anlage/Verifizierung korrekt gegated — Lücke nur bei Ressourcen-Lebensdauer,
  siehe FEAT-01/02. Storage-Pakete Platform-Admin-only, kein Self-Service-Bypass.
- DB-Constraints: `tenant_id` NOT NULL + FK CASCADE auf allen tenant-gescopten Tabellen;
  `system_error_log.source`-CHECK exakt wie CLAUDE.md beschrieben; Geldbeträge mit passenden
  CHECK-Constraints (`attendance_fine.amount > 0`, bewusst keine CHECK auf `finance_transaction`
  wegen legitimer negativer Buchungen); UNIQUE-Constraints DB-seitig auf allen Tokens/Slugs/
  Domains; neueste Migrationen (0090-0096) sauber, `SECURITY DEFINER`-Funktionen in 0092 korrekt
  mit `search_path`-Pinning + `REVOKE ALL`/gezieltem `GRANT` gehärtet.
- Denial of Service: Pagination-Limits überall vorhanden (inkl. Service-seitigem Clamping bei
  zwei Admin-Endpoints ohne Route-Level-`le=`); kein ReDoS-fähiges Regex-Muster; PDF-Export
  bereits mit `RLIMIT_AS`/`RLIMIT_CPU`/`Semaphore(4)` gegen Concurrency-Abuse gehärtet;
  Tenant-Clone/-Import ohne Rate-Limit, aber nur Platform-Admin-Owner erreichbar (kein externes
  DoS-Szenario).
- Tests: 7 von 9 stichprobenartig geprüften Security-Invarianten haben bereits solide
  Regressionstests (Details in `TEST_RECOMMENDATIONS.md`). 2 Lücken dort dokumentiert
  (Account-Lockout-Schwellenwert-Test, WS-Origin-Handshake-Test).

## Zusammenfassung — alle 13 Forks (A-M) abgeschlossen

**0 Critical, 0 High, 3 Medium (BG-01, FEAT-01, FEAT-02), 2 Low (TEN-01, DEPLOY-01),
1 Needs-Verification (DEP-02, Starlette-Pin/Runtime-Check), 1 Medium-Dependency (DEP-01,
Next.js-Patch), 1 Potential-Low (DEP-03, PyJWT), 4 Info (TEN-02, WS-01, PUB-01, `/bridge`-Notiz)**.
Keine offenen Punkte mehr aus dem Pflichtkatalog des Audit-Auftrags (Abschnitte 7-26 durchweg
abgedeckt, siehe TODO.md für die vollständige Zuordnung Fork→Abschnitt).
