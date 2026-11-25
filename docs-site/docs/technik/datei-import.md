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
  `date_source` (`takeout`/`rule`) erscheint in Vorschau und Bericht. Der Zeitstempel wird als
  Kalendertag in Europe/Zurich übernommen (hocX hat keine Mandanten-Zeitzone; gleiche Zone wie die
  übrigen Datumsangaben).
- Bekannte Einschränkungen (P0): JSON in einem anderen Teilarchiv als das Foto wird nicht zugeordnet;
  bei einem Ordner-Upload (entpacktes Takeout) werden die JSON nicht ausgewertet.

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
job-worker, siehe RUNBOOK Abschnitt 17. API-Quellen (P1): `CLOUD_IMPORT_ENABLED`,
`CLOUD_IMPORT_TOKEN_KEY` (+ `_PREVIOUS`, Secret, von `env_migrate.sh` erzeugt),
`CLOUD_IMPORT_REDIRECT_BASE_URL` und je Anbieter Client-ID/Secret/Ablaufdatum, siehe RUNBOOK
«Cloud-Import einrichten».

## API-Quellen (Phase P1, Fundament)

Gemeinsames Fundament für alle Cloud-Anbieter (Microsoft in 1.6, weitere Adapter folgen nach demselben
Muster). Migration `0281_cloud_import_connections`.

| Teil | Ort |
|---|---|
| Tabelle `import_connection` (tenant_id + RLS, Tokens nur verschlüsselt) | `backend/app/models/import_entities.py` |
| Token-Verschlüsselung (MultiFernet, `CLOUD_IMPORT_TOKEN_KEY` + `_PREVIOUS`) | `services/cloud_import/token_crypto.py` |
| Ausgehendes HTTP (Allowlist, SSRF, Redirects, Bearer-Regeln, 429/503) | `services/cloud_import/http.py` |
| OAuth Code + PKCE, `state`, ausstehende Verbindung | `services/cloud_import/oauth.py` |
| Verbindungen, Refresh, Löschen | `services/cloud_import/connections.py` |
| Adapter-Schnittstelle und Register | `services/cloud_import/providers/base.py`, `providers/__init__.py` |
| Auflisten und Download im job-worker | `services/cloud_import/remote.py` (aus `worker.run_slice`) |
| Zentraler Callback (ohne Sitzung) | `api/routes/cloud_import_oauth.py` |
| Wizard: Anmelden, eigener Ordnerbaum, Auflisten | `frontend/components/file-import/import-cloud-step.tsx`, `import-cloud-tree.tsx` |
| Nachgebauter Transport für Tests/E2E | `services/cloud_import/fake_http.py` (nur mit `CLOUD_IMPORT_FAKE_PROVIDERS`) |

### Ablauf

1. Wizard: Kachel des Anbieters (nur angeboten, wenn `CLOUD_IMPORT_ENABLED`, `CLOUD_IMPORT_TOKEN_KEY` und
   die Anbieter-Konfiguration gesetzt sind) → `POST /cloud-import/jobs` mit `source=<anbieter>` (`draft`).
2. `POST /cloud-import/oauth/<anbieter>/start` → Autorisierungs-URL. `state` (32 Byte, Redis 10 min,
   nur der SHA-256 als Schlüssel) bindet Person, Mandant, Auftrag, Stufe und Rücksprung-Host; PKCE S256.
3. Anbieter → `…/api/cloud-import/oauth/<anbieter>/callback` auf der zentralen Domain
   (`CLOUD_IMPORT_REDIRECT_BASE_URL`, sonst `https://TRAEFIK_DOMAIN`). `form_post` als POST (Origin-Guard
   nimmt genau diesen Pfad aus), `query` nur für Anbieter ohne `form_post`. Der Callback löst den Code mit
   dem Verifier ein, legt die Tokens verschlüsselt als «ausstehend» ab (10 min) und leitet auf
   `/files/import?job=…#cloud_finish=<einmal-token>` (zentrale oder eigene App-Domain, sonst relativ).
4. Der Wizard ruft mit der Sitzung `POST /cloud-import/oauth/finish`. Nur wenn die angemeldete Person
   die aus dem `state` ist, entsteht die Verbindung (Schutz vor Login-CSRF); sonst 403 und die Tokens
   sind verworfen.
5. Ordnerbaum: `GET /cloud-import/jobs/{id}/browse?ref=&cursor=` liest live beim Anbieter, speichert
   nichts. Auswahl: `POST /cloud-import/jobs/{id}/selection` → `listing`.
6. job-worker (`remote.run_listing`): rekursiv mit Paging, Stand in `import_job.listing_state` nach jeder
   Seite → `ready` (bzw. zurück zu `draft` mit `empty_source`/`selection_unavailable`).
7. Regeln, Vorschau, Start wie P0. Danach lädt `remote.download_step` je Datei als Stream nach
   `UPLOAD_ROOT/_staging/cloud-import/<auftrag>/` (`staged`), höchstens 12 gestagte Dateien je Auftrag; die
   bestehende Pipeline übernimmt.
8. Ende (`done`/`cancelled`): Verbindung samt Tokens sofort gelöscht. `failed`: bis `purge_after`
   (7 Tage ohne Nutzung) für «Fortsetzen».

### Fehler und Wiederaufnahme

- `429`/`503` mit `Retry-After` → `import_job.not_before`; `claim_next` bedient den Auftrag erst danach.
- Refresh mit `invalid_grant` → Verbindung `needs_reauth` (Tokens gelöscht), Auftrag `needs_reauth`, Mail
  `cloud_import.needs_reauth` (Kategorie «Datei-Import», nur mit `files.import`). Neue Anmeldung über
  denselben Wizard setzt den Auftrag fort (`listing` bzw. `queued`); nach 7 Tagen `failed` (`reauth_expired`).
- Je Datei bis 5 Versuche mit wachsender Wartezeit (`next_attempt_at`), dann `download_failed`;
  `not_found`, `access_denied`, `too_large`, `host_not_allowed` sofort.
- Absturz: Lease läuft ab, `listing_state` bzw. Einträge `queued`/`staged` machen ohne Doppelte weiter.

### Sicherheit

- Host-Allowlist je Adapter (`HostPolicy`), nur https/443, DNS-Prüfung jeder Adresse (privat, Loopback,
  Link-Local, reserviert → abgelehnt) und Verbindung genau zur geprüften Adresse (kein DNS-Rebinding).
- Redirects nur selbst (höchstens 3), jedes Ziel erneut geprüft. Bearer-Token nur an `api_hosts`, an
  Download-Hosts nur bei `bearer_download_suffixes` (z. B. SharePoint nach tempauth-Ende).
- Referenzen aus dem Browser nur nach `validate_ref`, Benutzer liefern nie URLs.
- Logs: nur Methode, Host, Pfad ohne Query, Status. `TokenSet.__repr__` ohne Tokens.
- Callback in `EXEMPT_PUBLIC_ROUTES`, Token-Spalten in `EXEMPT_COLUMNS` begründet.
- `User-Agent: ISV|hocX|hocX/<Version>` (Microsoft-Empfehlung gegen Drosselung).

### Neue Quelle hinzufügen

1. Modul `services/cloud_import/providers/<anbieter>.py` mit einer Klasse nach `CloudProvider`
   (`key` = Wert aus `IMPORT_PROVIDERS`, Migration 0281 kennt schon `google_drive`, `google_photos`,
   `dropbox`, `webdav`), `host_policy`, `oauth_config()`, `account_info`, `roots`, `list_children`,
   `get_node`, `download`, optional `revoke`, `map_authorize_error`, `public_info`; am Modulende
   `register(<Klasse>())`.
2. Modulname in `providers._ADAPTER_MODULES` eintragen.
3. Nachbau für Tests/E2E: `fake_transport()` (über `fake_http.FakeTransport`) und `fake_scenarios()` für
   die Test-Anmeldeseite `/api/cloud-import/fake-authorize/<anbieter>` (nur mit `CLOUD_IMPORT_FAKE_PROVIDERS`
   im E2E-Stack). Vorlage: `backend/tests/cloud_import_fakes.py`.
4. Konfiguration nach SECURITY-RULES §5.2 (config.py inkl. `_FILE`, `.env*.example`, `env.sh`, `deploy.sh`,
   `docker-compose.release.yml` nur backend + job-worker), Ablaufdatum des Secrets in
   `system_health_service.cloud_import_secret_expiries`.
5. Übersetzungen `fileImport.source.provider.<anbieter>`, `source.providerHint.<anbieter>`,
   `cloud.connectHint.<anbieter>`; Registrierungsanleitung in RUNBOOK und
   `audit-reports/plans/2026-11-25-cloud-import-registrierung.md`.

### Monitoring

Check `cloud_import` in `/admin/system`: aktive Aufträge, Aufträge ohne Fortschritt seit 30 min (nicht
gedrosselt), Anzahl `needs_reauth`, Ablauf der Client-Secrets (Warnung ab 30 Tagen, kritisch nach Ablauf,
Warnung ohne gültiges Ablaufdatum).
