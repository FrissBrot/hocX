# Fork D — Background Jobs / WebSocket-Origin / Race Conditions

Scope: Audit-Abschnitte 16, 17, 21 (WS-Teil). Kein Code geändert, kein Commit. Kein Live-E2E-Test
gelaufen (Begründung siehe RACE-01 — statische Analyse war für die Fragestellung ausreichend
konklusiv, ein Live-Test hätte nur dasselbe Ergebnis mit hohem Aufwand reproduziert).

## BG-01 — photo-analysis-worker-Fehler erreichen `system_error_log` nie (auch bei Fix unmöglich ohne DB-Grant)

Status: **CONFIRMED**
CWE: CWE-778 (Insufficient Logging)

Betroffene Dateien: `photo-analysis-worker/app/worker.py` (Zeilen 63-69, 28-51),
`backend/alembic/versions/0067_photo_analysis_job.py` (Zeilen 86-102)

Betroffene Funktionen: `run()`, `_process_job()`

### Security Invariant

I8 (siehe SECURITY_MODEL.md): unerwartete Backend-Fehler landen zentral in `system_error_log`
und sind im Platform-Admin-Panel sichtbar — als Sicherheitsnetz auch für Anomalien, die auf
Angriffsversuche hindeuten könnten (dieser Worker verarbeitet Bilddaten aus nicht
vertrauenswürdigem User-Upload über OpenCV/onnxruntime, eine klassische Parser-Angriffsfläche).

### Beschreibung

`run()` fängt jede Exception aus `_process_job()` nur mit `logger.exception(...)` (Container-Log)
und markiert den Job als `failed` mit der Fehlermeldung im `photo_analysis_job.error`-Feld. Es
gibt keinen Aufruf von `record_system_error`/`insert_error_log` oder einem Äquivalent. Selbst wenn
jemand naiv `record_system_error(...)`-artigen Code ergänzen würde: die Postgres-Rolle
`hocx_photo_worker` hat laut Migration `0067_photo_analysis_job.py` NUR Rechte auf
`stored_file` (SELECT von 4 Spalten, UPDATE von `face_quality_score`) und `photo_analysis_job`
(SELECT, UPDATE) — kein GRANT auf `system_error_log`. Ein einfacher INSERT-Versuch würde mit
"permission denied" scheitern.

### Root Cause

Der Worker wurde als komplett separater, minimal-privilegierter Prozess konzipiert (bewusstes
Isolationskonzept, siehe `photo-analysis-worker/README.md`), aber die zentrale
Fehlererfassungs-Konvention (`system_error_log`, CLAUDE.md) wurde bei diesem dritten
Service nicht mitgezogen — anders als bei `abgabebox-backend`, das dieselbe Konvention korrekt
mit eigenem `source="abgabebox-backend"` implementiert.

### Preconditions

Keine Angreifer-Rechte nötig, um den Fehlerzustand zu erzeugen (z. B. ein beschädigtes/
manipuliertes Bild, das den Detector zum Absturz bringt, landet automatisch in diesem blinden
Fleck). Ein Angreifer mit Upload-Rechten (Tenant-User oder sogar Abgabebox-Uploader, da Fotos
auch über die Abgabebox eingehen und später vom Worker verarbeitet werden) profitiert davon, dass
wiederholte fehlgeschlagene/verdächtige Verarbeitungsversuche nirgends zentral sichtbar werden.

### Attack Path (Impact-Illustration, kein direkter Exploit)

1. Angreifer lädt eine Serie präparierter Bilddateien hoch (z. B. um einen bekannten
   OpenCV/onnxruntime-Parser-Bug gezielt zu triggern, Fuzzing-artig).
2. `photo-analysis-worker` verarbeitet sie, ein Teil schlägt fehl (Exception in `_process_job`).
3. Fehler landet nur im Container-Log (nicht zentral ausgewertet) und im
   `photo_analysis_job.error`-Feld (keine Admin-UI zeigt dieses Feld gebündelt/alarmierend an).
4. Platform-Admins bemerken wiederholte/gezielte Angriffsversuche gegen diesen Service nicht,
   anders als bei jedem anderen der drei Services.

### Proof of Concept

Kein aktiver Exploit nötig/sinnvoll — Finding ist eine Observability-Lücke, kein direkter Bypass.
Nachweis rein durch Code-/Grant-Lektüre (siehe Evidence).

### Impact

MEDIUM (Observability/Detection-Gap für einen Service, der nicht vertrauenswürdigen Input aus
zwei verschiedenen Upload-Pfaden verarbeitet). Kein direkter Datenverlust/Zugriffsverstoß.

### Existing Mitigations

`logger.exception(...)` schreibt ins Container-Log (falls Log-Aggregation/-Monitoring extern
existiert, evtl. dort sichtbar — ausserhalb des Code-Audits nicht verifizierbar).
`photo_analysis_job.error` ist zumindest in der DB persistiert (kein vollständiger Datenverlust
der Fehlermeldung selbst).

### Why Existing Mitigations Are Insufficient

Container-Log-Sichtung ist laut CLAUDE.md explizit NICHT der vorgesehene Weg
("ausschliesslich im Platform-Admin-Panel angezeigt") — es gibt keine Admin-UI, die
`photo_analysis_job.error`-Werte bündelt/alarmiert, im Gegensatz zu `system_error_log`.

### Recommended Fix

Zwei Optionen (Entscheidung, welche gewählt wird, eher Architektur- als reine Code-Frage —
für FINAL_REPORT als Kandidat "Entscheidung erforderlich" vormerken, da Grant-Erweiterung
das bewusste Least-Privilege-Konzept dieser Rolle leicht aufweicht):
(a) `hocx_photo_worker` ein zusätzliches, sehr eng gefasstes GRANT geben:
`GRANT INSERT (tenant_id, source, message, ...) ON system_error_log TO hocx_photo_worker`
(nur INSERT, keine SELECT/UPDATE/DELETE — Worker soll nie fremde Logs lesen), dazu im Worker
`insert_error_log`-Äquivalent mit festem `source` (neuer, in der CHECK-Constraint erlaubter Wert
nötig, z. B. `"photo-analysis-worker"` — CHECK-Constraint in `sql/baseline_schema.sql` UND
Frontend-`SOURCE_LABELS` in `admin-error-log.tsx` müssten synchron erweitert werden).
(b) Leichtgewichtiger: der bereits vorhandene `upload_pipeline_rescan_loop`/ein neuer
Backend-Loop liest periodisch `photo_analysis_job`-Zeilen mit `status='failed'` und ruft dafür
`record_system_error` im Namen des Hauptbackends auf (kein neues GRANT nötig, Fehlerdetails
bleiben im bestehenden `source` in {"backend","abgabebox-backend"}).

### Regression Test

Neuer Test in `photo-analysis-worker/tests/test_worker.py` (oder `backend/tests`, je nach
gewählter Fix-Option): einen Job mit garantiert fehlschlagendem `_process_job` (z. B. gemockter
Read-Error) laufen lassen, verifizieren dass ein `system_error_log`-Eintrag (bzw. der gewählte
Ersatzmechanismus) mit korrektem `source` entsteht.

### Evidence

- `photo-analysis-worker/app/worker.py:63-69` (kein `record_system_error`-Äquivalent)
- `backend/alembic/versions/0067_photo_analysis_job.py:86-102` (GRANTs für `hocx_photo_worker`,
  kein `system_error_log`-Grant)
- CLAUDE.md, Abschnitt "Zentrale Fehlererfassung", Punkt 2 (Background-Code ausserhalb
  HTTP/WS wird von globalen Handlern nie erreicht, muss selbst loggen)

---

## WS-01 — WebSocket-Origin-Allowlist ist nicht tenant-gescoped (Defense-in-Depth-Lücke, kein bestätigter Bypass)

Status: **FALSE_POSITIVE** (als ausnutzbarer Bypass) / dokumentiert als Verbesserungsvorschlag,
nicht als Finding mit Impact — siehe False-Positive-Check unten.

Betroffene Datei: `backend/app/api/routes/collaboration_ws.py:161-200`
(`_active_app_domain_origins`, `_origin_allowed`)

### Beschreibung

`_active_app_domain_origins()` liefert JEDE aktive Custom-App-Domain über ALLE Tenants hinweg als
gültigen WebSocket-`Origin` — nicht nur die Domain(s) des Tenants, dem das angefragte Protokoll
gehört. Ein Origin-Check, der nur prüft "ist dieser Origin irgendeine aktive Domain irgendeines
Tenants", statt "gehört dieser Origin zum Tenant der Zielressource", ist weiter gefasst als
nötig.

### False-Positive-Check (Abschnitt 28)

- `origin` muss exakt (String-Gleichheit, kein Wildcard/Subdomain-Matching) in der Menge sein —
  kein Präfix-/Suffix-Bypass möglich.
- Fehlender `Origin`-Header wird abgelehnt (`if not origin: return False`) — fail-closed.
- Ein Tenant kann eine Domain erst nach echter DNS-Verifikation aktivieren
  (`backend/app/services/domain_verification_service.py::verify_domain`, TXT/CNAME-Check gegen
  `expected_target_host`) — ein Angreifer kann also keine beliebige fremde Domain (z. B. eine
  bekannte, stark frequentierte Seite) in die Allowlist einschleusen, ohne deren DNS tatsächlich
  zu kontrollieren. Wer eine Domain per DNS kontrolliert, gewinnt durch deren Aufnahme in diese
  Allowlist nichts, was er nicht schon hätte (er könnte ohnehin beliebige Inhalte auf seiner
  eigenen Domain hosten).
- Das Session-Cookie (`httponly`, `secure`, `samesite=lax`) wird laut `security.py` mit
  `SameSite=Lax` gesetzt. Ein `WebSocket(...)`-Konstruktoraufruf aus JavaScript auf einer
  Cross-Site-Seite ist ein Subresource-Request (keine Top-Level-Navigation) — SameSite=Lax
  verhindert bereits, dass der Browser das Cookie an diesem Request überhaupt mitschickt,
  unabhängig vom Origin-Check. Der Origin-Check selbst ist laut eigenem Code-Kommentar bewusst
  "defensive"/Defense-in-Depth, nicht die einzige Schutzschicht.
- Token wird über das Cookie übergeben (`websocket.cookies.get(...)`, Zeile 208), nicht als
  Query-Parameter — kein Leak über Server-/Proxy-Access-Logs.

### Bewertung

Kein bestätigter Angriffspfad: die einzige Partei, die eine fremde Domain in die globale
Allowlist bekommen könnte, müsste bereits deren DNS kontrollieren, und selbst dann würde
SameSite=Lax das eigentlich schützenswerte Cookie nicht an eine Cross-Origin-WS-Verbindung
weitergeben. Dennoch als **Verbesserungsvorschlag** (LOW/INFO, Defense-in-Depth) für
FINDINGS.md aufnehmen: `_active_app_domain_origins()` könnte zusätzlich `protocol_id`s
Tenant kennen und nur dessen eigene Domain(s) akzeptieren, um die Sicherheitseigenschaft nicht
implizit von SameSite=Lax abhängig zu machen (z. B. falls ein zukünftiges Feature das Cookie auf
`SameSite=None` umstellen müsste).

---

## RACE-01 — Abgabebox Storage-Quota: verschachtelte Advisory-Locks sind TOCTOU-frei (kein Fund, Korrektur einer Vorgänger-Notiz)

Status: **FALSE_POSITIVE** (der in `components/abgabebox-backend.md` notierte
Vertiefungskandidat "Quota-Race zwischen den zwei Locks" ist nach Analyse widerlegt)

Betroffene Dateien: `abgabebox-backend/app/db.py` (`tenant_upload_lock`, `serialized_upload`),
`abgabebox-backend/app/routes/public.py:409-511`

### Korrektur einer Fehleinschätzung im Phase-1-Inventar

`components/abgabebox-backend.md` beschrieb `serialized_upload` fälschlich als "global über ALLE
Tenants seriell" (Namespace 909100001). Tatsächlich ist `serialized_upload(tenant_id)` ein
**Zwei-Schlüssel**-Advisory-Lock (`pg_try_advisory_xact_lock(ns, tenant_id)`, `db.py:78-85`) —
`ns` (909100001) und `tenant_id` bilden zusammen den Lock-Schlüssel, wodurch zwei verschiedene
Tenants automatisch unabhängige Locks erhalten. Beide Locks (`serialized_upload` UND
`tenant_upload_lock`) sind also **beide per-Tenant**, nicht global.

### Analyse

`routes/public.py:409` öffnet `async with serialized_upload(tenant["id"])` und hält diesen Lock
laut Kommentar Zeile 408 bewusst über die GESAMTE restliche Verarbeitung (Checksum-Dedup,
Perceptual-Hash, Quota-Check, Dateischreiben, Scan, finaler DB-Commit) — das serialisiert
JEDE Upload-Anfrage desselben Tenants über beide Uvicorn-Worker-Prozesse hinweg vollständig,
bevor die nächste überhaupt mit ihrer eigenen Prüfung beginnt. Der innere
`with tenant_upload_lock(tenant["id"])` (Zeile 461) ist dadurch für die Nebenläufigkeitsfrage
redundant (er würde nur relevant, falls der äussere Lock-Scope künftig verengt würde) — das ist
bewusste Defense-in-Depth laut Kommentar in `db.py:58-62`, kein Bug.

Die Quota-Prüfung (`get_tenant_storage_usage_bytes`, `tenant_storage_bytes`, Zeilen 489-494)
UND die Quarantäne-Schreibvorgänge (ab Zeile 514) laufen beide innerhalb desselben,
den ganzen Request umschliessenden `serialized_upload`-Locks — es gibt kein Zeitfenster, in dem
ein zweiter Request desselben Tenants seine eigene Prüfung beginnen könnte, bevor der erste
seine Bytes geschrieben hat. Für verschiedene Tenants ist keine Serialisierung nötig (getrennte
Quotas), daher korrekt parallel.

### Warum kein Live-E2E-Test

Die Postgres-Advisory-Lock-Semantik (`pg_try_advisory_xact_lock`, xact-scoped, pro Tenant-Key) ist
deterministisch und aus dem Code eindeutig ableitbar — ein Zwei-Prozess-Test würde exakt dieses
bereits aus der Lock-Reichweite ableitbare Ergebnis reproduzieren, ohne neue Information zu
liefern. Der Aufwand (E2E-Stack hochfahren, Testskript schreiben) steht in keinem Verhältnis zum
Erkenntnisgewinn bei einem Mechanismus, dessen Korrektheit bereits aus den Postgres-Primitiven
selbst folgt. Falls die Bewertung angezweifelt wird: ein praktischer Test wäre trivial
nachrüstbar (zwei parallele `POST .../upload`-Requests knapp über dem Tenant-Quota via
`asyncio.gather` gegen `./scripts/e2e.sh up`).

---

## MIG-01 — Migration `0088_remove_manual_storage_quota`: kein Enforcement-Gap

Status: **FALSE_POSITIVE** (Vertiefungskandidat aus Phase 1 widerlegt)

Die Migration ist ein einmaliger Daten-Backfill (`UPDATE tenant SET storage_quota_bytes = ...`),
keine Schema-Änderung. Die Quota-Durchsetzung selbst liest `tenant.storage_quota_bytes` bei
JEDEM Request live aus der DB (`repository.get_tenant_storage_quota_bytes`) — es gibt keinen
Code, der von einem "Migration bereits gelaufen"-Flag abhängt. Migration selbst dokumentiert
zusätzlich einen bereits behobenen früheren Bug (unconditional Reset restriktiver Overrides,
"audit 2026-09-24", siehe Kommentar Zeilen 7-17) — sauber gefixt, keine neue Lücke gefunden.

---

## Sonstige geprüfte, unauffällige Punkte (Abschnitt 5 der Aufgabenstellung, "böswilliger Aufrufer")

- `backend/app/core/background_loops.py`: ALLE 10 in `main.py` gestarteten Loops
  (`domain_health_check_loop` … `gallery_upload_ingest_loop`, `main.py:354-363`) laufen über den
  gemeinsamen `run_advisory_locked_loop`-Wrapper, der bereits korrekt `record_system_error(db,
  exc=exc)` mit Default-`source="backend"` aufruft (Zeile 93-102) — der in CLAUDE.md
  dokumentierte historische Bug (`source="background_loop"` verletzt CHECK-Constraint) ist hier
  bereits vollständig und zentral behoben, keine Regression gefunden. Kein Loop rollt sein
  eigenes Exception-Handling ausserhalb dieses Wrappers.
- `backend/app/services/file_service.py::create_analysis_job`/`create_pending_analysis_jobs`:
  beide erzeugen `stored_file_ids` ausschliesslich über tenant-gefilterte Queries
  (`list_tenant_files(db, tenant_id, ..., file_ids=file_ids)` — `file_ids` ist nur ein
  zusätzlicher IN-Filter auf einer bereits pro Tenant gebauten UNION-Query, keine
  vertrauensvolle Übernahme roher Client-IDs; `create_pending_analysis_jobs` filtert direkt
  `StoredFile.tenant_id == tenant_id`). `get_analysis_job` prüft zusätzlich `job.tenant_id !=
  tenant_id → 404`. Der in `components/photo-analysis-worker.md` offen gelassene Verdacht
  (Cross-Tenant-Leck über `stored_file_ids`) ist damit **widerlegt** — der Worker vertraut zu
  Recht darauf, dass der Aufrufer bereits korrekt scoped hat.
