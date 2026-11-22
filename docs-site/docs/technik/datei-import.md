# Datei-Import (Technik und Betrieb)

Phase P0 des Plans «Cloud-Datei-Importer» (2026-11-21): anbieterneutrale Quellen ZIP/Takeout und
Ordner-Upload, Regel-Engine, Hintergrundverarbeitung, Bericht. Microsoft- und Google-Anbindung
(OAuth, Tokens) folgen in P1/P2.

## Bausteine

| Teil | Ort |
|---|---|
| Tabellen `import_job`, `import_item` (tenant_id + RLS, Migration `0230_cloud_import`) | `backend/app/models/import_entities.py` |
| Routen `/api/cloud-import/...` (alle `files.import`) | `backend/app/api/routes/cloud_import.py` |
| Pfade, Takeout, Dateiart | `backend/app/services/cloud_import/paths.py` |
| Regel-Engine (rein, RE2) | `backend/app/services/cloud_import/rules.py` |
| Auftrag, Vorschau, Start | `backend/app/services/cloud_import/jobs.py` |
| Hintergrundjob `cloud_import` (job-worker) | `backend/app/services/cloud_import/worker.py` |
| Wizard | `frontend/app/files/import`, `frontend/components/file-import` |

## Ablauf

1. `POST /cloud-import/jobs` legt einen Auftrag an (`draft`). Der Partial Unique Index
   `uq_import_job_one_active` erlaubt je Mandant nur einen Auftrag in `draft|ready|queued|running|cancel_requested`.
2. Quelle einlesen:
   - ZIP: `POST /cloud-import/uploads/{id}/archive` streamt wie der Galerie-Upload direkt auf den
     Upload-Datenträger (`ImportUploadRoute`, eigene `UploadAdmissionMiddleware`) nach
     `UPLOAD_ROOT/_staging/cloud-import/<id>/`. Gelesen wird nur das Inhaltsverzeichnis.
   - Ordner: `POST /cloud-import/jobs/{id}/manifest` (Pfade und Grössen, je bis 5000).
   - `POST .../finish-listing` → `ready`.
3. `POST .../preview` rechnet die Regeln über alle Einträge (rein, ohne Schreiben) und speichert
   Regeln/Optionen, solange alle gültig sind.
4. `POST .../start` prüft Regeln, Rechte (Bilder: `photos.manage`, Dokumente: `files.manage`) und
   Kontingent, friert das Ergebnis je Datei ein (`status`, `tags`, `estimated_date`, `albums`,
   `group_key`) und setzt `queued`.
5. Ordner-Quelle: der Browser holt `GET .../pending-uploads` und lädt nur diese Dateien über
   `POST /cloud-import/uploads/{id}/files` (Pfadliste im Feld `paths`). Unerwartete Pfade werden
   verworfen; mehr als 5 GiB gestagt → 429 `staging_busy`.
6. Der Loop `cloud_import` (5 s, Lock-ID 202600050) holt Aufträge per `FOR UPDATE SKIP LOCKED` mit
   Lease (5 min), faire Reihenfolge nach `served_at`, Zeitscheibe 60 s. Ein Batch (gleiche Art, Tags,
   Schätzdatum; Bilder 4, Dokumente 10, keine gleichen Dateinamen) läuft durch
   `FileService.save_gallery_uploads` bzw. `save_document_uploads`. Der Status der Einträge wird im
   `before_commit`-Hook in derselben Transaktion geschrieben wie die neuen Dateien - eine
   Wiederaufnahme nach Absturz importiert nichts doppelt.

## Entscheide 2026-11-22

- Album-Aktionen nur mit `import_job.albums_enabled` (Standard aus); ohne bleibt `albums` leer.
- Albumnamen (`name:<Name>`): gleichnamiges manuelles Album des eigenen Mandanten wird wiederverwendet,
  bei mehreren das älteste (`created_at`, `id`); `album_report` hält `reused`/`candidates` für den Bericht.
- Duplikate: sichtbare und verwaltbare vorhandene Dateien bekommen Tags (Vereinigung, nie entfernt) und
  Album-Einträge (`add_items` ohne Überschreiben); `import_item.existing_file_id`, Code `duplicate_enriched`.
  `existing_file_id` zählt nicht für die Aufbewahrung des Berichts.
- Takeout: beim Hochladen eines Archivs werden die Metadaten-JSON im selben Ordner zugeordnet
  (`.json`, `.supplemental-metadata.json` und gekürzte Formen, Zähler `(n)`), je höchstens 64 KiB
  gelesen und `photoTakenTime.timestamp` als `hint_date` gespeichert. Rangfolge EXIF > Takeout > Regel;
  `date_source` (`takeout`/`rule`) erscheint in Vorschau und Bericht. JSON in einem anderen
  Teilarchiv als das Foto wird nicht zugeordnet.

## Planner-Statistik

Nach je 5000 neu importierten Dateien und am Ende eines Auftrags ruft der Worker
`hocx_analyze_upload_tables()` auf (SECURITY DEFINER aus Migration 0230: `ANALYZE` von `stored_file`,
`gallery_image`, `photo_search_doc`). Ohne das schätzt Postgres nach einem Massenimport bis zum
nächsten Autoanalyze rund eine Zeile je Mandant und wählt für Fotoliste und Suche Nested-Loop-Pläne
mit Minuten Laufzeit (Befund aus fix/search-perf-1.5.1). Fehler werden nur geloggt.

## Sicherheit

- ZIP-Namen werden normalisiert (`\` → `/`, Steuer-/Bidi-Zeichen, NFC, `..` verworfen) und nie als
  Dateisystempfad verwendet (Zip-Slip). Entpackt wird je Eintrag höchstens Grenze + 1 Byte
  (Zip-Bomb), angegebene Grössen zählen nicht; verschlüsselte Einträge werden abgelehnt.
- Regex nur über RE2 (`google-re2`, lineare Laufzeit); Globs werden nach RE2 übersetzt.
  Grenzen: 50 Regeln, Regex 200 Zeichen, Glob 300 Zeichen / 10 `**`.
- Virenscan, Magic-Byte, Grössen, Duplikate, Kontingent: unverändert aus der Upload-Pipeline.
- Rate-Limits: Auftrag anlegen 30/h je Mandant, Vorschau 600/10 min je Person, Start 20/h je Mandant.
- Mutationen nur durch die Person, die den Auftrag angelegt hat; sehen und abbrechen dürfen alle
  mit `files.import`. Fremde Auftrags-IDs: 404.

## Aufbewahrung und Aufräumen (im Loop)

- Nie gestartete Aufträge: nach 7 Tagen verworfen (`error=expired`).
- Ordner-Import ohne Uploads seit 7 Tagen: offene Dateien `not_uploaded`, Auftrag `done`.
- Unterbrochene Aufträge (`failed`): Quelle nach 7 Tagen gelöscht, danach kein Fortsetzen mehr.
- Bericht (`import_item`): bleibt, solange mindestens eine importierte Datei existiert
  (`stored_file_id`, FK `SET NULL` beim endgültigen Löschen); Aufträge ohne importierte Datei
  bleiben mindestens 7 Tage sichtbar.
- Staging verwaister Aufträge wird nach 24 h entfernt.

## Variablen

`CLOUD_IMPORT_MAX_JOB_FILES` (50000) und `CLOUD_IMPORT_MAX_JOB_BYTES` (100 GiB) für backend und
job-worker, siehe RUNBOOK Abschnitt 17. Keine Secrets in P0.
