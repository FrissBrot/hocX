# Component: photo-analysis-worker

Status: REVIEWED_WITH_FINDINGS (Phase 2 durch Fork D abgeschlossen, siehe
`security-audit/findings-draft/fork-d-background-race.md`: BG-01 CONFIRMED [fehlende
Fehlererfassung, DB-Rolle hat kein GRANT auf system_error_log]; Tenant-Scoping von
`fetch_files` gegen Job-Erzeugung in `backend/app/services/file_service.py` verifiziert —
FALSE_POSITIVE, kein Cross-Tenant-Leck, Aufrufer scoped korrekt)

Files reviewed (Phase 1): `app/worker.py`, `app/db.py`, `app/face_quality.py`, `requirements.txt`,
`Dockerfile`, `README.md` (alle Dateien der Komponente; `tests/*` nur per `find` gelistet,
nicht inhaltlich gelesen)
Endpoints reviewed: keiner (kein HTTP/WS-Interface, siehe unten)

## 1. Zweck & Architektur

"Phase 3" des Foto-Culling-Features: bewertet Schärfe/Belichtung des sichersten erkannten
Gesichts in einem Bild (`stored_file.face_quality_score`). Kein HTTP-Server, keine Queue-
Bibliothek — ein simpler Polling-Loop (`app/worker.py::run`), der alle
`PHOTO_WORKER_POLL_INTERVAL_SECONDS` (Default 10s) per `SELECT ... FOR UPDATE SKIP LOCKED`
gegen die Tabelle `photo_analysis_job` nach der ältesten `status='queued'`-Zeile pollt
(`app/db.py::claim_next_job`), sie auf `running` setzt, verarbeitet und danach `done`/
`failed` schreibt (`finish_job`). Bilddateien werden nicht über die Job-Payload
transportiert, sondern über einen **geteilten Storage-Mount** (`STORAGE_ROOT`,
Default `/app/storage`) anhand von `stored_file.storage_path` gelesen — derselbe Pfad, den
`backend` über `STORAGE_ROOT` auflöst (Kommentar in `worker.py` verweist explizit auf
`_safe_storage_path` im Backend).

## 2. Trust Boundary

- Eigener Docker-Container, eigenes Image (`Dockerfile`), läuft laut README `read_only` und
  ohne Laufzeit-Netzwerkzugriff (Modell wird beim Build gepinnt per SHA-256 geladen).
- Eigene, **restriktive** Postgres-Rolle `hocx_photo_worker` (siehe Migration
  `0067_photo_analysis_job.py`, laut README nur Zugriff auf wenige `stored_file`-Spalten +
  `photo_analysis_job`), nicht die volle `hocx_app`-Rolle. Dediziertes Isolations-Konzept:
  falls eine Bild-Parsing-Schwachstelle (OpenCV/onnxruntime) den Prozess kompromittiert, ist
  der DB-seitige Blast Radius bewusst eng gehalten.
- **Tenant-Kontext**: Der Job trägt `tenant_id` (`claim_next_job` selektiert es mit), aber
  `fetch_files()` liest die Dateien ausschliesslich per `stored_file.id = ANY(:ids)` — **ohne**
  erneuten Abgleich, dass jede `stored_file_id` tatsächlich zu `job["tenant_id"]` gehört. Der
  Worker vertraut also vollständig darauf, dass der Aufrufer (Backend, beim Job-Enqueue) die
  `stored_file_ids`-Liste bereits korrekt auf den Tenant beschränkt hat. Das ist keine
  Verletzung *dieser* Komponente per se, aber eine Abhängigkeit, die im Backend-Teil des
  Audits (Job-Erzeugung, vermutlich `backend/app/services/file_service.py`) explizit
  verifiziert werden muss: wird dort tenant-scoped erzeugt, oder könnte eine
  `stored_file_id` aus Tenant B in einen Job für Tenant A geraten (→ Cross-Tenant-Schreiben
  von `face_quality_score` auf fremde Datei als Nebenwirkung, geringer Impact, aber ein
  Isolations-Leck)? → **TODO für Backend-Teil, nicht hier.**
- Läuft als Non-Root-User `photo-worker` (UID 5002) im Container.

## 3. Input-Verarbeitung

- Verarbeitet Bilddateien, die letztlich aus User-Uploads stammen (nicht vertrauenswürdiger
  Input), via OpenCV (`cv2.imdecode`, `FaceDetectorYN`) — Version `opencv-python-headless==5.0.0.93`,
  `numpy==2.5.3`. Kein Pillow/EXIF-Parsing in dieser Komponente.
  `score_face_quality` behandelt leere/undekodierbare Buffer defensiv (`return None`), inkl.
  eines dokumentierten Workarounds für einen C++-Assert bei leerem Buffer.
- Modell (`face_detection_yunet_*.onnx`) wird beim Image-Build von einer festen Upstream-URL
  geladen und gegen einen fest im Dockerfile hinterlegten SHA-256 geprüft — kein Laufzeit-
  Download, kein SSRF-Vektor über das Modell selbst.
- Für die eigentliche Tiefenprüfung relevant, aber hier nur notiert (siehe Abschnitt 7):
  OpenCV-Bilddecoder als Angriffsfläche für malformed/polyglot Images (Parser-Bugs,
  Decompression-Bombs) — Analyse gehört in Phase "File Uploads"/Injection, nicht Inventar.

## 4. Fehlerbehandlung (zentrale Fehlererfassung)

Läuft vollständig **ausserhalb** eines HTTP-Request-Zyklus (reiner `while True`-Polling-Loop,
kein FastAPI, kein WebSocket) — genau der in CLAUDE.md beschriebene Fall, in dem die globalen
Exception-/HTTPException-Handler **nicht** greifen.

- `run()` fängt `except Exception as exc` um `_process_job(...)`, loggt nur
  `logger.exception(...)` und ruft `finish_job(..., status="failed", error=str(exc))` — es
  gibt **keinen** Aufruf von `record_system_error(...)` (backend-Konvention) oder einem
  Äquivalent für diese Komponente. Der Fehler landet also nur im Container-Log und im
  `photo_analysis_job.error`-Feld der betroffenen Zeile, nicht in `system_error_log` /
  Platform-Admin-Panel.
- Innerhalb `_process_job` wird ein `OSError` beim Lesen einer fehlenden Datei ebenfalls nur
  geloggt (`logger.warning`), nicht zentral erfasst — bewusst als Best-Effort behandelt
  (Kommentar: Datei fehlt auf Platte, Job soll trotzdem nicht ewig requeued werden).
- **Kandidat für Finding** (noch NEEDS_VERIFICATION, gehört in Phase "Background Jobs"):
  Dieses Muster entspricht exakt dem in CLAUDE.md als Hauptursache dokumentierten Bug-Typ
  ("Wartungs-Loop-Fehler kommen nie in der Admin-Page an"), nur an einer neuen Stelle
  (separater Service statt `backend/app/core/background_loops.py`). Zu klären: hat
  `photo-analysis-worker` überhaupt Zugriff/Grund, in `system_error_log` zu schreiben (eigene
  DB-Rolle, ggf. keine Berechtigung auf diese Tabelle), oder ist das bewusst ausgeklammert?
  Falls die Rolle keinen Zugriff hat, wäre das ein Architektur-Gap, keine einfache Ein-Zeilen-
  Ergänzung.

## 5. Externe Abhängigkeiten (SSRF)

Keine Laufzeit-Netzwerkzugriffe (README + Dockerfile-Kommentar: `read_only`, Modell zur
Build-Zeit gepinnt geladen). Kein SSRF-Vektor identifiziert.

## 6. Tests

Vorhanden: `tests/test_db.py`, `tests/test_face_quality.py`, `tests/test_worker.py`,
`tests/conftest.py`. Laut README deckt `test_face_quality.py` echte Fotoerkennung inkl.
eines bereits gefundenen realen Bugs ab (Auflösungsgrenze der YuNet-Erkennung). Inhalt der
Tests nicht gelesen (Inventar-Phase) — Tiefenprüfung/Security-Regressionstests folgt in
späterer Phase (`TEST_RECOMMENDATIONS.md`).

## 7. Auffälligkeiten für Vertiefung

- **Fehlererfassung fehlt** in `run()`/`_process_job` (Abschnitt 4) — Kandidat für Finding,
  Verifizierung: hat `hocx_photo_worker` Schreibrecht auf `system_error_log`?
- **Tenant-Scoping von `fetch_files`** verlässt sich vollständig auf den Aufrufer
  (Backend-Job-Erzeugung) — muss dort verifiziert werden (Cross-Tenant-Schreibzugriff auf
  `face_quality_score` als möglicher Nebenkanal).
- OpenCV-Bilddecoder-Angriffsfläche (malformed/polyglot/Decompression-Bomb) — gehört in
  File-Upload/Injection-Phase, hier nur vermerkt.
- README dokumentiert selbst offene Lücken: `scripts/deploy.sh`, `scripts/lib/env.sh` und der
  GitHub-Actions-Release-Workflow bauen/pushen dieses Image **nicht** und provisionieren die
  nötigen Secrets (`PHOTO_WORKER_DB_PASSWORD`, `PHOTO_WORKER_DATABASE_URL`) nicht — relevant
  für die Deployment-Phase (nicht: Code-Sicherheit dieser Komponente, sondern Betriebsreife).
- `MAX_ANALYSIS_JOB_IMAGES=2000` wird laut Kommentar in `backend/app/services/file_service.py`
  durchgesetzt — muss dort verifiziert werden (DoS-Grenze serverseitig, nicht nur clientseitig).
