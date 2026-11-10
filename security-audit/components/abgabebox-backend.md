# Component: abgabebox-backend

Status: **REVIEWED (Inventar) + Race-Condition-Vertiefung durch Fork D abgeschlossen**
(siehe `security-audit/findings-draft/fork-d-background-race.md`, RACE-01/MIG-01):
verschachtelte Advisory-Locks sind TOCTOU-frei (FALSE_POSITIVE auf den unten unter Abschnitt 9
notierten Verdacht — `serialized_upload` ist per-Tenant, nicht global, Korrektur der
Fehleinschätzung unten); Migration `0088_remove_manual_storage_quota` ohne Enforcement-Gap.
Noch offen (nicht Fork D's Scope): verschluckter `insert_upload_log`-Fehler, Captcha-
Bypass-Bedingung, Traefik-Rate-Limit-Verifikation — siehe Abschnitt 9 unten.

## 1. Struktur

```
abgabebox-backend/
  app/
    main.py              FastAPI app, lifespan (quarantine_cleanup_loop), CORS, Upload-Admission-
                          Middleware, globale Exception-Handler, /api/health
    config.py             Settings (pydantic-settings), VAR_FILE-Secret-Loading, is_dev_or_test_environment()
    db.py                 engine/SessionLocal (eigene DB-Verbindung, restricted Rolle),
                          tenant_upload_lock (pg_advisory_xact_lock), serialized_upload (pg_try_advisory_xact_lock)
    models.py             SQLAlchemy-Core Table()-Defs, bewusst NICHT ORM/Reflection - bildet nur die
                          Spalten ab, die die restricted Postgres-Rolle 'hocx_abgabebox' sehen darf
    repository.py         Alle DB-Zugriffe (Core select/insert), kein db.add()/db.refresh()
    routes/public.py      Einziges Routen-Modul: alle öffentlichen Endpunkte unter /api/public/*
    upload_admission.py   ASGI-Middleware: Content-Length-Check, Concurrency-Cap (max_active=1),
                          Disk-Space-Check, vor Starlettes Multipart-Parser
    captcha.py            FriendlyCaptcha-Verifikation + eigenes HMAC-Sitzungstoken
    scanner.py             ClamAV-Anbindung (pyclamd), scan_bytes/scan_file/scan_many (bounded concurrency)
    storage.py             Dateisystem: quarantine/ vs. regulärer Storage, tenant_storage_bytes (rglob+stat),
                          cleanup_stale_quarantine_files
    element_resolver.py   Berechnet offene Abgabe-"Elemente" (Termine/Listen-Einträge/manuell) -
                          bewusste Duplikation der Fensterlogik aus backend/app/services/submission_service.py
    schemas.py             Pydantic-Response-Modelle (rein Output, keine Input-Validierung über Pydantic)
  tests/                  14 Testdateien (siehe unten)
```

Eigenständiger FastAPI-Service, komplett unabhängig vom Haupt-`backend/` deployt (eigener
Container, eigene `Settings`), verbindet sich aber auf dieselbe Postgres-Instanz über die
**restricted DB-Rolle `hocx_abgabebox`** (Column-Level-Grants, siehe `backend/alembic/versions/
0020_abgabebox.py`, `0023_abgabebox_select_grants`, `0090_abgabebox_tenant_storage_quota_grant`).
Kein Reflection/ORM-Mapping bewusst, damit `db.refresh()`/`db.get()` nie versehentlich ein
SELECT auf Spalten auslöst, die die Rolle nicht lesen darf.

Kein Auth-System, keine Sessions, kein Login — die einzige Instanz von "Authentifizierung" ist
der Link-Token in der URL.

## 2. Public-Token-Modell

- **Link-Token** (`submission_link.token`): einziges Credential, `secrets.token_urlsafe(24)`
  laut Kommentar in `routes/public.py` (32 URL-safe-Base64-Zeichen), validiert gegen
  `_LINK_TOKEN_PATTERN = ^[A-Za-z0-9_-]{16,128}$` (Format-Check ohne DB-Zugriff) und danach per
  `repository.get_link_by_token` gegen die DB aufgelöst. Kein Expiry-Feld im Modell
  (`submission_link_table` hat keine Ablaufspalte) — Token gilt bis es in der DB gelöscht/
  ersetzt wird (Verwaltung dieser Tabelle liegt im Haupt-Backend, hier nicht sichtbar).
- Unbekannter Token UND Token ohne freigeschaltetes Feature ("abgabebox" nicht gebucht) liefern
  beide `404` — bewusst ununterscheidbar, um keine Tenant-Existenz zu verraten. Ein **bekannter**
  Token, dessen Tenant das Feature nicht gebucht hat, bekommt separat `403 FEATURE_DISABLED`
  (nur erreichbar, wenn der Token schon korrekt aufgelöst wurde).
- **Assignment-Slug** (`public_slug`) zusätzlich zum Link-Token nötig, um eine konkrete Abgabe
  zu erreichen; wird IMMER zusammen mit `tenant_id` UND `_linked_to(link_id)` gefiltert (Join
  über `submission_assignment_link`) — ein Assignment ist also nicht nur tenant-, sondern auch
  link-scoped.
- **Captcha-Session-Token**: eigenes HMAC-signiertes Token (`captcha.py`), scope-gebunden an
  `link_token:assignment_slug:element_ref` + IP-Fingerprint-Hash + Ablauf (`captcha_session_ttl_minutes`,
  Default 120 min). Nicht dieselbe Bibliothek/Implementierung wie das Haupt-Backend
  (`backend/app/core/security.py`), aber gleiches Format (`base64url(payload).base64url(hmac)`),
  bewusst dupliziert für Service-Isolation.

## 3. Upload-Pipeline

Client → `POST /api/public/{link_token}/assignments/{assignment_slug}/elements/{element_ref}/upload`
→ (Middleware: `UploadAdmissionMiddleware`, Content-Length/Disk-Space/Concurrency-Cap) →
Route-Validierung (Captcha-Session, Element offen, Dateityp/-größe, Magic-Number-Check) →
`tenant_upload_lock` (pg-advisory, quota-check + quarantine-write atomar) → ClamAV-Scan
(`scan_many`, bounded concurrency) → clean: `move_from_quarantine` in regulären Storage,
infected/error: löschen → `insert_full_upload` (eine DB-Transaktion: `submission_upload` +
`stored_file` + `submission_upload_file`).

- **Dateityp-Validierung**: doppelt — (a) Extension gegen `assignment.allowed_file_types`
  (Tenant-Konfiguration), (b) Magic-Number-Check `_content_matches_extension()` gegen die
  tatsächlichen ersten Bytes (PDF/JPEG/PNG/GIF/WEBP/ZIP-Container für docx/xlsx/pptx/pages/key/
  numbers/OLE-Container für doc/xls/ppt/HEIC-ftyp-Brands). Client-`Content-Type`-Header wird
  nirgends vertraut — `mime_type` kommt ausschließlich aus dem serverseitigen
  `_EXTENSION_MIME_MAP` (Kommentar im Code verweist explizit auf einen historischen Stored-XSS-
  Fund, der so behoben wurde).
- **Dateinamen**: Original-Dateiname wird NICHT als Storage-Pfad verwendet — gespeicherter
  Pfad ist immer `tenant-{id}/assignment-{id}/{uuid4().hex}{suffix}` (`storage.py::save_to_quarantine`/
  `save_file`). Der `suffix` selbst kommt aus `Path(original_name).suffix.lower()`, ungefiltert
  in den generierten Dateinamen übernommen (kein Traversal möglich, da nur als Suffix nach einem
  server-generierten UUID-Namen angehängt — kandidatenwürdig für Vertiefung, siehe unten).
  `original_name`/`display_name` in der DB ist ein serverseitig neu zusammengesetzter Name
  (`{assignment_slug}_{element_slug}_{date}{counter}{suffix}`), nicht der Client-Dateiname.
- **Größe**: pro Datei `assignment.max_file_size_mb` (Tenant-Konfiguration), pro Request
  `MAX_UPLOAD_REQUEST_BYTES` (150 MB) + `settings.max_files_per_upload_request` (hart, 1–50,
  unabhängig von `max_files_per_element`), zusätzlich `UploadAdmissionMiddleware` (Content-Length
  vor jedem Parsing) und Traefik `abgabebox-upload-body-limit` (eine Ebene früher, laut Kommentar
  mit `MAX_UPLOAD_BODY_BYTES` synchron zu halten — externe Config, hier nicht geprüft).
- **Virenscan**: ClamAV über `pyclamd`, `scan_many()` mit `asyncio.Semaphore(4)` +
  `asyncio.to_thread` (nicht blockierend). `infected` UND `error` (ClamAV nicht erreichbar über
  eine harte Grenze `MAX_SCAN_BYTES=100MiB` hinaus oder Verbindungsfehler → `pending`, nicht
  `error`) werden unterschiedlich behandelt: `error` → generische Ablehnung (422),
  `pending` (ClamAV down) → Datei bleibt in Quarantäne für spätere Rescan, Request wird trotzdem
  als "submitted" durchgelassen (kumulatives Modell).
- **Duplikate**: SHA-256-Exact-Match pro Element (blockiert stillschweigend, keine Fehlermeldung
  ans Frontend — "Anzahl empfangen" bleibt stabil, um keine Duplikate zu verraten) + Perceptual-
  Hash-Ähnlichkeitswarnung mandantenweit (nur Warnung, kein Block).
- **Quota**: `min(Tenant.storage_quota_bytes, ABGABEBOX_TENANT_STORAGE_QUOTA_MB)` — seit
  2026-09-24 wird das echte Plan/Paket-Kontingent aus der `tenant`-Tabelle geprüft, nicht mehr
  nur die globale Konstante. Usage wird per Filesystem-Walk (`tenant_storage_bytes`, rglob+stat)
  UND per DB-Funktion (`get_tenant_storage_usage_bytes` → `public.upload_storage_usage(tenant_id)`,
  SQL-Funktion, hier nicht gelesen) parallel geprüft (beide Checks müssen bestehen).
- **Race-Condition-Schutz**: zwei verschiedene Postgres-Advisory-Locks — `serialized_upload`
  (`pg_try_advisory_xact_lock`, Namespace `909100001`, geteilt mit
  `backend/app/services/upload_lock.py`, Polling alle 50ms) umschließt Checksum-Lookup+Scan+
  Commit; `tenant_upload_lock` (`pg_advisory_xact_lock`, Offset `300_000_000_000 + tenant_id`)
  umschließt konkreter den Quota-Check + Quarantäne-Schreibvorgang. Beides Cross-Process-Locks
  (Service läuft mit `--workers 2`), nicht In-Process-`asyncio.Lock`.

## 4. Quarantäne-Cleanup-Loop (`app/main.py::quarantine_cleanup_loop`)

- Läuft als `asyncio.create_task` im `lifespan`-Context (außerhalb jedes HTTP-Requests).
- Singleton-Schutz über `pg_try_advisory_xact_lock(202600007)` — nur eine Service-Instanz/Worker
  führt den Cleanup pro Intervall aus.
- Löscht nur Dateien in `quarantine/`, die (a) älter als `max(24h, quarantine_max_age_minutes)`
  sind UND (b) laut `upload_path_referenced(db, path)` (SQL-Funktion) nicht in einer laufenden
  DB-Referenz stehen — "DB-Ausfall darf keine Daten löschen" (Kommentar), da `is_referenced=None`
  → sofortiger No-op.
- Fehlerbehandlung: `except Exception as exc` → `_logger.exception(...)` (lokales Log) UND
  `_record_background_error(exc)` → `insert_error_log(..., source="abgabebox-backend", ...)`.
  Damit korrekt an die CLAUDE.md-Kettenregel für Background-Loops außerhalb des Request-Zyklus
  angeschlossen — kein `from exc` nötig, da hier direkt geloggt statt weitergeworfen wird.

## 5. `insert_error_log` — `source`-Wert

`repository.py::insert_error_log` (Zeile 311–336) setzt **hart** `source="abgabebox-backend"`
(kein Parameter, kein Aufrufer kann einen anderen Wert einschleusen) — entspricht exakt der in
CLAUDE.md geforderten Konvention. Aufrufer: `main.py::_record_error` (globaler
`Exception`-Handler + `HTTPException`-Handler mit `exc.__cause__`-Check, identisches Muster zum
Haupt-Backend), `main.py::_record_background_error` (Quarantäne-Loop), und implizit über beide
jede Route via die globalen Handler. Kein Aufrufer außerhalb dieser Datei setzt `source` separat.
→ **Keine Auffälligkeit hier**, Konvention sauber eingehalten (im Gegensatz zum in CLAUDE.md
dokumentierten historischen Bug in `backend/app/core/background_loops.py`).

## 6. Tenant-/Owner-Bezug

Jede Ressource ist über `tenant_id` (direkt oder via Join) gescoped:
`submission_link.tenant_id` → `submission_assignment.tenant_id` (zusätzlich `_linked_to(link_id)`-
Join über `submission_assignment_link`) → `event`/`list_definition`/`list_entry` je über
`tenant_id` bzw. transitiv über die Assignment-Zuordnung. Jede Query in `repository.py`, die eine
Assignment/Event/List-Definition lädt, filtert nach `tenant_id=tenant["id"]` (aus dem Link
abgeleitet) — keine Stelle gefunden, die eine ID ohne Tenant-Filter aus Client-Input auflöst
(alle IDs im Payload sind `link_token`/`assignment_slug`/`element_ref`, keine rohen DB-IDs).
Owner-Bezug bei Uploads: `assignment_id`/`event_id`/`list_entry_id` werden serverseitig aus dem
bereits tenant-gescoped `assignment`/`element`-Dict übernommen, nie aus Client-Feldern.

## 7. Routen (alle in `routes/public.py`, Prefix `/api/public/`)

| Route | Methode | Zweck |
|---|---|---|
| `/{link_token}/assignments` | GET | Liste offener Assignments für einen Link |
| `/{link_token}/assignments/{slug}` | GET | Detail eines Assignments |
| `/{link_token}/assignments/{slug}/elements` | GET | Offene Elemente (Termine/Listeneinträge) |
| `/{link_token}/assignments/{slug}/elements/{ref}/captcha-verify` | POST | FriendlyCaptcha lösen → Session-Token |
| `/{link_token}/assignments/{slug}/elements/{ref}/upload` | POST | Datei-Upload |

Zusätzlich in `main.py`: `GET /api/health` (kein DB-Zugriff, kein Auth nötig, Compose-Healthcheck).
Keine Admin-/internen Endpunkte in diesem Service — Verwaltung der Links/Assignments erfolgt
ausschließlich im Haupt-`backend/`.

## 8. Tests (`abgabebox-backend/tests/`, 14 Dateien)

`test_captcha_fail_closed_in_production.py`, `test_cycle_years.py`, `test_element_sort.py`,
`test_exact_upload_duplicates.py`, `test_link_token_access.py`, `test_manual_assignment.py`,
`test_max_files_per_request.py`, `test_perceptual_hash.py`, `test_scan_many_concurrency.py`,
`test_storage_quarantine_parity.py`, `test_tenant_storage_bytes_async.py`,
`test_tenant_storage_quota_uses_plan.py`, `test_tenant_upload_quota_lock.py`,
`test_upload_capacity.py`, `test_upload_size_limits.py`. Namen deuten auf bereits vorhandene
Regressionstests für mehrere der oben notierten Security-relevanten Fixes (Captcha-Fail-Closed,
Token-Zugriff, Quota-Lock, Storage-Parity) — Inhalt/Abdeckung noch nicht geprüft (Tiefenprüfung
folgt in TEST_RECOMMENDATIONS.md-Phase).

## 9. Auffälligkeiten für Vertiefung (nur benannt, nicht bestätigt)

- **Link-Token-Format-Check ist reiner Regex, kein Rate-Limiting/Lockout hier im Code selbst**
  (Kommentar in `captcha.py` erwähnt "Traefik's per-IP rate limit on this endpoint (5/min)" als
  externe Annahme, NICHT in diesem Fork verifiziert — in `docker-compose*.yml`/Traefik-Config
  noch gegenlesen, ob diese Middleware wirklich existiert, an die richtige Route gebunden ist und
  tatsächlich pro Client-IP statt z. B. pro Host greift) und ob es Token-Enumeration
  (32-stelliges `token_urlsafe` ist praktisch nicht brute-forcebar, aber prüfenswert) bzw.
  Captcha-Bypass durch IP-Rotation abdeckt.
- **`_EXTENSION_MIME_MAP`/`_content_matches_extension`**: OLE-Container-Check (doc/xls/ppt)
  prüft laut eigenem Code-Kommentar nur das Containerformat, nicht den echten Office-Subtyp
  (CLSID) — Autor selbst stuft das als Data-Integrity-Gap ein, nicht als Code-Execution/XSS,
  da `mime_type` immer serverseitig fix bleibt. Für Findings-Phase als bereits bekannt/akzeptiert
  vermerken, nicht neu "entdecken".
- **ClamAV `error` bei `BufferTooLongError`/Nicht-FOUND-Antwort**: `scan_bytes` gibt bei jedem
  sonstigen `Exception` `"pending"` zurück (ClamAV-Verbindungsfehler) — prüfen, ob ein Angreifer
  gezielt einen ClamAV-Fehlerzustand herbeiführen kann, der zu `"pending"` statt `"infected"`/
  `"error"` führt und so eine noch nicht gescannte Datei dauerhaft in Quarantäne "geparkt" bleibt
  (kein automatisches Rescan-Sweep-Modul in diesem Service selbst sichtbar — evtl. im
  Haupt-Backend, prüfen).
- **`insert_upload_log`-Fehler werden verschluckt** (`_log()`-Closure in `routes/public.py`,
  `except Exception: pass`, Zeile ~347) — kein `record_system_error`/`insert_error_log`-Aufruf
  hier. Gemäß CLAUDE.md-Regel 4 (verschluckte Exception außerhalb bewusster Best-Effort-Fälle)
  ein Kandidat für einen Findings-Eintrag (Observability-Lücke, nicht direkt Security, aber
  verdeckt evtl. Angriffsmuster in den Logs).
- **Quota-Race zwischen den zwei Locks**: `serialized_upload` (Namespace 909100001) umschließt
  den äußeren Block inkl. Checksum-Vergleich, `tenant_upload_lock` (Offset 300000000000+tenant_id)
  nochmal separat den Quota-Check innerhalb — zwei verschachtelte Advisory-Locks mit
  unterschiedlichem Scope (global seriell vs. pro Tenant). Prüfen, ob das tatsächlich TOCTOU-frei
  ist oder ob `serialized_upload` (global über ALLE Tenants seriell) den inneren
  `tenant_upload_lock` praktisch redundant macht bzw. ob eine Reihenfolge existiert, in der der
  äußere Lock zu früh freigegeben wird, bevor `tenant_storage_bytes()` die neuen Quarantäne-Dateien
  sieht.
- **`cleanup_stale_quarantine_files`**: läuft nur in `abgabebox-backend`, aber Quarantäne-Ordner
  wird laut `storage.py`-Kommentar auch vom Haupt-`backend` gelesen (Rescan-Flow) — prüfen, ob
  der Haupt-Backend-Rescan-Prozess und dieser Cleanup-Loop sich gegenseitig Dateien wegnehmen
  können (Race zwischen Rescan-Move und Alters-Löschung).
- **CORS**: `allow_origins=[settings.cors_allow_origin]` (ein einzelner Origin-String, Default
  `https://abgabe.example.com`) — prüfen, ob der reale Produktions-Origin-Wert (aus `.env`, nicht
  gelesen) korrekt gesetzt ist und keine Wildcard/mehrere Origins nötig wären (Custom-Domain-Fall
  laut Git-Log "Custom-Domain-Origin" im Haupt-Backend — prüfen, ob Abgabebox denselben
  Custom-Domain-Mechanismus braucht und ihn ggf. nicht hat).
- **Element-Ref-Namespace `MANUAL_ELEMENT_REF = "manual"`**: geprüft, ob ein Client
  `element_ref="manual"` für ein Nicht-manuelles Assignment einschleusen und so eine falsche
  Element-Auflösung erzwingen könnte — `resolve_single_element` iteriert aber über
  `resolve_open_elements()` (serverseitig berechnet) und vergleicht nur exakt, kein Weg
  gefunden, das zu spoofen, ohne dass das Assignment selbst `source_type == "manual"` ist.
  Niedrige Priorität, evtl. in FINDINGS.md als "geprüft, kein Fund" vermerken statt offen lassen.

## Verbleibende Arbeit für diese Komponente

- Phase 2 (Findings): jede der oben genannten Auffälligkeiten aktiv verifizieren/widerlegen
  (False-Positive-Check gemäß Audit-Methodik), insbesondere Quota-Race zwischen den zwei Locks
  und den verschluckten `insert_upload_log`-Fehler.
- Cross-Komponenten-Abgleich mit Haupt-`backend`: `backend/alembic/versions/0020_abgabebox.py`
  (GRANT-Statements) gegen `app/models.py` hier gegenlesen, ob die Spalten-Grants tatsächlich
  genau das erlauben, was `models.py` behauptet (Modul-Docstring warnt selbst, dass
  `stored_file`/`submission_upload_file` mittlerweile tabellenweit lesbar sind, aber die
  Kommentare bei `submission_upload_table`/`submission_link_table` das nicht überall
  nachgezogen haben könnten — TEXTUELL prüfen, nicht nur den Docstring glauben).
- `upload_storage_usage`/`upload_path_referenced` (SQL-Funktionen) selbst noch nicht gelesen —
  liegen vermutlich in `backend/sql/` oder einer Alembic-Migration, nicht in diesem Service.
- Traefik-Rate-Limit (`abgabebox-rate-limit`) nochmal exakt gegen die tatsächlich aktive
  Compose-Datei der Produktionsumgebung abgleichen (mehrere `docker-compose*.yml` vorhanden,
  hier nur grob gegengelesen, nicht die Precedence zwischen ihnen).
