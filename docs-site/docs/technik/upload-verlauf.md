# Upload-Verlauf (Technik und Betrieb)

Plan: `audit-reports/plans/2026-11-21-upload-history-plan.md` (Entscheide 21./22.11.2026). Version 1.6.

## Bausteine

| Baustein | Ort |
|---|---|
| Tabellen `upload_job`, `upload_job_item`, `stored_file.upload_job_id`, `stored_file.camera_serial_key`, `gallery_upload_job.upload_job_id` | Migration `0250_upload_history` |
| Rückgängig der Datumskorrektur: `capture_change_batch`, `capture_change_item` | Migration `0251_capture_change_batches` |
| Abgabebox-Trigger `trg_submission_upload_file_history` | Migration `0252_upload_history_abgabebox` |
| Dienst (öffnen, aufnehmen, Items, Abschluss, Sichtbarkeit, Kameras) | `backend/app/services/upload_job_service.py` |
| API `/api/upload-jobs*` | `backend/app/api/routes/upload_jobs.py` |
| Datumskorrektur, Vorschau, Rückgängig | `routes/files.py` (`/files/bulk-capture-date[/preview]`, `/capture-changes*`), `services/capture_change_service.py` |
| Kamera-Kürzel | `services/camera_serial.py` |
| Altbestand | `services/upload_history_backfill.py`, `python -m app.workers.upload_history_backfill` |
| Oberfläche | `frontend/components/uploads/*`, `app/{photos,files}/uploads` |

## Datenmodell und Mandantentrennung

- `upload_job` und `upload_job_item` haben `tenant_id` NOT NULL und die RLS-Policy `tenant_isolation`.
  Item, Datei, Ingest-Auftrag und Korrektur verweisen über zusammengesetzte Fremdschlüssel
  `(tenant_id, upload_job_id)` auf den Vorgang; ein Vorgang eines anderen Mandanten lässt sich damit
  auch durch einen Programmfehler nicht anhängen. `ON DELETE SET NULL (upload_job_id)` lässt die
  `tenant_id` stehen.
- Kanäle: `gallery`, `document`, `todo`, `protocol_image` (ein Vorgang je Protokoll und Tag, E-6),
  `submission_link`, `abgabebox`, `word_import`, `tenant_import`, `cloud_import` (ein Vorgang je
  Import, `import_job_id`).
- Items: `uploaded`, `duplicate`, `metadata_updated`, `rejected`, `infected`, `failed`,
  `discarded`, Quelle `server` oder `client` (vom Browser gemeldet, E-14). Ein späterer Virenfund
  steht nie im Item, er kommt beim Lesen aus `stored_file.scan_status`.

## Ablauf je Weg

- **Galerie:** `POST /upload-jobs` → Vorab-Abgleich mit `upload_job_id` (Duplikate/ergänzte Metadaten
  als Items) → jedes Paket `gallery-uploads` mit `upload_job_id` → der Ingest schreibt die Items im
  `before_commit` derselben Transaktion → `complete`. Abgeschlossen wird, sobald der Browser fertig
  ist und kein Ingest-Auftrag des Vorgangs mehr läuft.
- **Ablage, Pendenz:** wie Galerie, synchron im Request.
- **Ohne `upload_job_id`** (API, ältere Clients) legt jeder Request einen eigenen Vorgang an.
- **Abgabebox:** DB-Trigger auf `submission_upload_file` (SECURITY DEFINER, `search_path = public,
  pg_temp`); die Rolle `hocx_abgabebox` bekommt keine Rechte auf den Verlaufstabellen (E-5). Je
  Einreichung ein Vorgang; Mandant der Datei muss dem Mandanten der Abgabe entsprechen.
- **Persönlicher Link, Word-Import, Datei-Import, Mandanten-Import, Protokollbilder:** im jeweiligen
  Dienst, Items in derselben Transaktion wie die Datei.

## Rechte (E-2)

Keine neue Berechtigung. Sichtbar sind Vorgänge eines Kanals mit dem Recht des Bereichs
(`photos.manage`, `files.manage`, `files.import`, `meetings.edit` für Word-Import, `settings.manage`
für Plattform-Importe, `submissions.read` mit Reichweite für Abgaben, Protokoll-Leserecht für
Protokollbilder). Fremde oder unbekannte IDs ergeben 404. `file-ids` liefert nur beschreibbare
Dateien; alle Bulk-Aktionen laufen über die bestehenden Endpunkte, die jede Datei erneut prüfen.
`POST /upload-jobs` erlaubt höchstens 20 offene Vorgänge je Person.

Namen abgelehnter oder fehlgeschlagener Dateien (Einträge ohne gespeicherte Datei) sieht jede Person
mit dem Recht des Kanals, nicht nur wer hochgeladen hat (User-Entscheid nach dem Security-Review 1.6,
F-8). Ausgeblendet wird ein Name nur, wenn die gespeicherte Datei für die Person verborgen ist.

## Datumskorrektur

- `POST /files/bulk-capture-date`: zusätzlich `shift_minutes` (±525 600), `shift_seconds` (±59, nur
  Referenzfoto-Modus), `batch_id` für gestückelte Aufrufe (eigene, nicht rückgängig gemachte, höchstens
  2 h alte Korrektur, sonst 404), `upload_job_id`. Jede tatsächliche Änderung schreibt Wert
  davor/danach in `capture_change_item`.
- `POST /files/bulk-capture-date/preview`: gleiche Prüfungen, schreibt nichts.
- `POST /capture-changes/{id}/undo`: nur Fotos, deren aktueller Wert noch dem neuen entspricht;
  Wert davor NULL entfernt die Korrektur (der Job `capture_date_file_sync` schreibt dann das Original
  zurück). Audit `photo.capture_date_shift_undone`.
- Termin-Zuordnung nur für Fotos, deren Zuordnungstag wechselt; Termine einmal je Aufruf geladen
  (`resync_photos_after_date_change`). Auto-Alben folgen wie in 1.5.1 (`follow_capture_date_change`).

## Kamera-Kürzel (E-13)

`stored_file.camera_serial_key` = die ersten 16 Hex-Zeichen von HMAC-SHA256(Schlüssel, Make ␟ Model ␟
Seriennummer). Schlüssel = HKDF-SHA256 aus `ADMIN_AUTH_SECRET` (salt `hocx-camera-serial-v1`, info
`tenant:<id>`). Kein neues Secret: `ADMIN_AUTH_SECRET` ist produktiv Pflicht, steht in Backend und
job-worker bereit und wird wegen `secret_crypto` nicht leichtfertig gewechselt; HKDF trennt die
Verwendung. Ein Secret-Wechsel lässt ältere und neuere Fotos derselben Kamera als zwei Geräte
erscheinen, sonst nichts. Die Seriennummer selbst wird in keiner Datenbankspalte gespeichert, nicht
geloggt und von keiner API ausgegeben; die Abgabebox und der document-worker berechnen kein Kürzel.
**Grenze:** Die Originaldatei bleibt unverändert gespeichert (der Upload entfernt nur GPS-Daten). Ihre
EXIF-Felder `BodySerialNumber`/`CameraSerialNumber` gehen deshalb bei Downloads, geteilten Alben und
Exporten des Originals mit, wie schon vor 1.6 (User-Entscheid F-7: so belassen, nur dokumentieren). Klon und Mandanten-Import
übernehmen das Kürzel nicht.

**Altbestand:** Nur Dateien, die der bestehende Metadaten-Backfill ohnehin liest, erhalten ein
Kürzel. Ein eigener Lauf über alle Originale (S3) wurde wegen der Last bewusst nicht gebaut.

## Aufbewahrung (E-9)

- Statement-Trigger `trg_stored_file_upload_history` nach dem endgültigen Löschen von Dateien:
  Namen gelöschter Dateien leeren, Vorgang ohne verbleibende Datei sofort löschen, Datumskorrekturen
  ohne Fotos löschen. SECURITY DEFINER, weil auch Rollen ohne Rechte auf den Verlaufstabellen
  Dateien löschen.
- Vorgänge, die nie eine Datei hatten: `retention_service` nach `upload_job_retention_days` (30).
- Länger als 24 h offene Vorgänge schliesst `log_cleanup` (`upload_job_service.close_stale`).
- Vereinsexport (`Uploads.xlsx`, verschlüsselt wie der Rest) und Auskunft enthalten die Vorgänge,
  die Einträge je Datei mit Name, Ergebnis und Grund (auch abgelehnte Dateien), die Datei-Importe mit
  Quellpfad und die Datumskorrekturen mit Wert davor/danach; die Auskunft nur, was die Person selbst
  ausgelöst hat (User-Entscheid F-6 nach dem Security-Review 1.6, ersetzt «ohne Dateinamen» aus E-9).

## Altbestand rekonstruieren (E-7)

Einmal nach dem Update, idempotent (siehe RUNBOOK): exakt aus Abgabebox-Einreichungen,
Datei-Importen, Word-Import-Dokumenten und Galerie-Ingest-Aufträgen der letzten 30 Tage (Pakete mit
weniger als 2 min Abstand zusammen), heuristisch aus den übrigen Galerie-/Ablage-Dateien nach Person,
Bezug, Dateiart und höchstens 10 min Lücke. Alle mit `reconstructed = true`; Protokollbilder bleiben
ohne Vorgang.

## Für später vorbereitet

Kameragruppen (Make/Model/Kürzel) und der Referenzfoto-Modus sind so gebaut, dass eine
Zeitsynchronisierung per QR-Code (gespeicherter Auftrag, nicht umgesetzt) an dieselben Gruppen und
an `capture_change_batch` andocken kann.
