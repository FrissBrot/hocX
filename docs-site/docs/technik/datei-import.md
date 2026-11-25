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
«Cloud-Import einrichten». Dropbox: `CLOUD_IMPORT_DROPBOX_APP_KEY`, `CLOUD_IMPORT_DROPBOX_APP_SECRET`
(Secret, `_FILE`); WebDAV: nur der Schalter `CLOUD_IMPORT_WEBDAV_ENABLED`.

## API-Quellen (Phase P1, Fundament)

Gemeinsames Fundament für alle Cloud-Anbieter (seit 1.7: Microsoft, Google Drive, Google Fotos, Dropbox und WebDAV nach demselben
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
- Rücksprung mit dem Abschluss-Token nur auf die zentrale Domain oder eine **gesunde** eigene App-Domain
  mit gebuchtem Feature (wie die Domain-Bridge), geprüft beim Start und erneut im Callback; sonst
  relativ auf die Callback-Domain. Microsoft zeigt immer die Kontoauswahl (`prompt=select_account`), damit
  ein fremder Autorisierungs-Link nie still per SSO durchläuft.
- «Gleiches Konto» beim erneuten Anmelden über die stabile Kennung des Anbieters (`account_subject`,
  Microsoft: Tenant + Objekt-ID), nie über den Anzeigenamen.
- Ein 401 vom Download-Host ist kein abgelaufenes Token (kein Refresh/needs_reauth), sondern
  `access_denied`; je Download höchstens 30 min, die Lease deckt das ab.
- `CLOUD_IMPORT_FAKE_PROVIDERS` setzt nur `docker-compose.e2e.yml`; `docker-compose.yml` erzwingt `false`
  (nicht über `.env` aktivierbar), `config.py` bricht ausserhalb von `development` ab.
- `User-Agent: ISV|hocX|hocX/<Version>` (Microsoft-Empfehlung gegen Drosselung).

### Dropbox (P3)

`services/cloud_import/providers/dropbox.py`, Nachbau `fake_dropbox.py`.

- App mit **Scoped access**, Scopes `account_info.read` (immer dabei), `files.metadata.read`,
  `files.content.read`; nur lesend. Code + PKCE, `token_access_type=offline` (Refresh-Token),
  `force_reapprove=true` (Zustimmungsseite immer sichtbar). Dropbox liefert den Code nur in der Query
  → GET-Callback. Beim Code-Einlösen und beim Refresh **kein** `scope`-Parameter
  (`OAuthConfig.send_scope_on_exchange`/`send_scope_on_refresh = False`).
- Allowlist: `api.dropboxapi.com`, `content.dropboxapi.com` (Bearer nur dort). RPC über
  `SafeHttpClient.post_json`; der `cursor` von `files/list_folder` geht nur im JSON-Körper an Dropbox.
- Referenzen: `root` oder Datei-/Ordner-ID `id:…` (streng geprüft). Download `GET files/download` mit
  `Dropbox-API-Arg`-Header (`SafeHttpClient.download(headers=…)`, nie an Redirect-Ziele).
- Fachliche Fehler (409, z. B. `path/not_found`) → `not_found`. 429 mit `Retry-After` → Auftrag
  pausiert; zusätzlich Token-Bucket je Konto `request_rate = (5/s, Burst 10)`.
- Nicht ladbare Dateien (Paper, `is_downloadable=false`) erscheinen nicht. Team-Spaces
  (`Dropbox-API-Path-Root`) werden nicht gesondert behandelt: sichtbar ist der persönliche Bereich
  inkl. eingebundener freigegebener Ordner.
- Widerruf bei Trennen/Auftragsende: `auth/token/revoke`.
- `account_subject = dropbox:<account_id>`.

### WebDAV (P3: kDrive, Nextcloud, SwissDisk)

`services/cloud_import/providers/webdav.py`, Client `dav_http.py`, Nachbau `fake_webdav.py`.

- Kein OAuth: `POST /cloud-import/jobs/{id}/webdav/connect` (`files.import`, nur Ersteller, Status
  `draft`/`needs_reauth`/`failed`, Rate-Limit 10/10 min je Person und 30/h je Mandant) mit `preset`
  (`kdrive`, `nextcloud`, `generic`), Benutzer, App-Passwort und je nach Vorlage Server, kDrive-ID oder
  URL. Vorlagen: kDrive `https://connect.drive.infomaniak.com/` bzw.
  `https://<id>.connect.kdrive.infomaniak.com/`; Nextcloud `https://<server>/remote.php/dav/files/<user>/`,
  Rückfall `…/remote.php/webdav/`. Erst ein erfolgreicher `PROPFIND` (Depth 0, Ordner) speichert etwas.
- Zugangsdaten `{"url","user","password"}` als JSON, verschlüsselt mit `CLOUD_IMPORT_TOKEN_KEY` in
  `import_connection.access_token_encrypted` (kein Refresh-Token, keine eigene Migration).
  `connections.context` gibt sie Adaptern ohne `oauth_config()` über `token()`; ein 401 setzt die
  Verbindung auf `needs_reauth` (Zugangsdaten gelöscht) → Passwort neu eingeben, gleiche Adresse und
  gleicher Benutzer (`account_subject` = Hash aus Adresse und Benutzer) setzen den Auftrag fort.
- Referenzen: `p` + base64url des Pfads relativ zur Basisadresse (`dav_http.encode_ref`), dekodiert
  ohne `..`, Steuerzeichen, Backslash. Auflisten mit `PROPFIND` Depth 1 (nie `infinity`), kein Paging.
- Schalter `CLOUD_IMPORT_WEBDAV_ENABLED` (Standard `true`); keine Registrierung nötig.

**SSRF-Schutz (`dav_http.py`, gilt für jede Verbindung inkl. Redirects):**

| Regel | Umsetzung |
|---|---|
| Schema | nur `https`; `http` nur im Fake-Testmodus über den nachgebauten Transport, `RealDavTransport` verbindet nie unverschlüsselt |
| Port | 443, 8443 (`ALLOWED_PORTS`) |
| Adresse | keine Zugangsdaten, Query oder Fragment; keine IP-Literale (auch nicht `2130706433`, `0x7f.1`, `127.1`), keine internen Namen (`localhost`, `*.local`, `*.internal`, `*.home.arpa`, `*.arpa` …), IDN als Punycode |
| DNS | alle Adressen müssen öffentlich sein; die Meldung an die Person unterscheidet «privat aufgelöst» nicht von «nicht auflösbar» (kein Orakel für interne Namen) (`http.ip_is_public`: privat, Loopback, Link-Local/Metadaten, CGNAT 100.64/10, Multicast, reserviert, ULA, Site-Local, IPv4-mapped, NAT64, 6to4, Teredo gesperrt) |
| Rebinding | eine Auflösung je Verbindung, verbunden wird mit genau dieser Adresse; TLS mit SNI und Zertifikatsprüfung auf den Namen |
| Redirects | höchstens 3, jedes Ziel neu geprüft und aufgelöst, Nicht-ASCII prozentkodiert; `PROPFIND` nur auf denselben Ursprung, Downloads auch auf fremde öffentliche Hosts, aber ohne Zugangsdaten (ein 401 dort ist `access_denied`, kein abgelehntes Passwort) |
| Grössen | `PROPFIND` 16 MiB, 20 000 Einträge; Downloads am Strom gemessen (Typ-Limit) |
| Zeit | Aufbau 10 s, Lese-Inaktivität 60 s, Gesamtzeit je Anfrage per Watchdog (schliesst den Socket auch mitten im TLS-Handshake oder Header-Empfang): `PROPFIND` 120 s (Verbindungstest 30 s, ohne offene DB-Transaktion), Download 60 s + 256 KiB/s |
| XML | expat ohne DTD: jede `<!DOCTYPE>`/Entität bricht ab (XXE, Billion Laughs), Tiefe ≤ 32, ≤ 400 000 Elemente; `href` auf fremde Hosts oder ausserhalb der Basis werden ignoriert |
| Geheimnis | Basic-Auth nur an den eingegebenen Ursprung; `DavCredentials.__repr__` ohne Passwort; Logs nur Methode, Host, Pfad, Status; Validierungsfehler spiegeln das Passwort nicht (`hide_input_in_errors`) |

Grenzen: Ein Server im öffentlichen Internet, dessen Name auf die eigene öffentliche Adresse von hocX
zeigt, ist erreichbar (nur die öffentlich gerouteten Dienste, wie für jeden Besucher).

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

### Parallelität, Drosselung, Fairness (Plan §8.3)

- `CLOUD_IMPORT_MAX_PARALLEL_DOWNLOADS` (Standard 2, 1–8) Downloads je Auftrag gleichzeitig. Die Threads
  übertragen nur (Netz → Datei); Token-Refresh und alle DB-Änderungen bleiben im Haupt-Thread. Ein 401
  in einem Thread führt zu einem Refresh im Haupt-Thread und einem neuen Versuch im nächsten Durchgang.
- Token-Bucket je Anbieter und Konto in Redis (`services/cloud_import/pacing.py`, Schlüssel
  `cloud_import_bucket:<anbieter>:<hash des kontos>`), Rate je Adapter über
  `CloudProvider.request_rate = (pro Sekunde, Burst)`; Microsoft 8/s, Burst 16. Backend (Ordnerbaum) und
  job-worker teilen den Eimer (job-worker deshalb im Netz `cache`). Kurze Wartezeit (≤ 2 s) wird
  abgewartet, längere pausiert den Auftrag wie ein 429. Ohne Redis: lokaler Eimer je Prozess.
- Fairness zwischen Mandanten: höchstens ein Import je Mandant, `claim_next` bedient immer den am
  längsten nicht bedienten Auftrag, Zeitscheibe 60 s je Auftrag und Tick, gedrosselte Aufträge
  (`not_before`) werden übersprungen.

### Mails (Plan §9)

Kategorie «Datei-Import» (`imports`, nur mit `files.import`), nur an die auslösende Person, ohne
Dateinamen: `cloud_import.done` (abgeschlossen, Zahlen + Link `/files/import?job=…`),
`cloud_import.failed` (unterbrochen, mit Grund: Kontingent, Rechte, Anbieter, `reauth_expired` …) für
**alle Quellen** inkl. ZIP/Ordner, und `cloud_import.needs_reauth`. Abgebrochene und nie gestartete
Aufträge bekommen keine Mail.

### Plattform-Admin

`/admin/cloud-imports` (owner): laufende Importe aller Mandanten mit Status und Fortschritt (keine
Dateinamen, keine Konten), Kennzahlen der letzten 30 Tage je Tag und Quelle (Importe, unterbrochene,
importierte Dateien, Volumen, Dateien mit Fehler). **Notfall-Abbruch** (`POST
/api/admin/cloud-imports/{id}/cancel`, `require_admin_write`, Audit `admin.cloud_import_cancelled`): wie
der Abbruch im Verein, importierte Dateien bleiben, Tokens werden gelöscht.

### Monitoring

Check `cloud_import` in `/admin/system`: aktive Aufträge, Aufträge ohne Fortschritt seit 30 min (nicht
gedrosselt), Anzahl `needs_reauth`, Ablauf der Client-Secrets (Warnung ab 30 Tagen, kritisch nach Ablauf,
Warnung ohne gültiges Ablaufdatum), Belegung der Zwischenablage (`stagedMb`, Warnung ab 20 GiB).

## Google Drive und Google Fotos (P2/P3)

Entscheid E-3 (a): nur `drive.file` + Google Picker, **kein** `drive.readonly` (keine CASA). Ganze Ordner
über das Takeout-ZIP (P0). Google Fotos über die Photos Picker API (seit 31.3.2025 einziger Weg).

| Teil | Ort |
|---|---|
| Gemeinsam (OAuth `query`, `access_type=offline`, `prompt=consent`, ID-Token → `sub`/E-Mail/`hd`, Widerruf) | `services/cloud_import/providers/google_common.py` |
| Google Drive (Metadaten, Export, Download) | `providers/google_drive.py` |
| Google Fotos (Picker-Sitzung, `mediaItems`, `baseUrl`) | `providers/google_photos.py` |
| Picker-Token, Fotos-Sitzung (Routen) | `api/routes/cloud_import_google.py` |
| Picker-Seite mit eigener CSP | `frontend/app/files/import/google-picker/page.tsx`, `components/file-import/google-drive-picker.tsx`, `lib/csp.ts` |
| Auswahl im Wizard | `components/file-import/import-google-select.tsx` |
| Nachbau (Tests/E2E) | `services/cloud_import/fake_google.py` (+ `/api/cloud-import/fake-google/*` nur mit `CLOUD_IMPORT_FAKE_PROVIDERS`) |

### Google Drive

- Scopes (volle URLs, so liefert Google sie in der Token-Antwort zurück): `openid`,
  `…/auth/userinfo.email`, `…/auth/drive.file`. Bei der granularen Zustimmung abgewählt →
  `tier = null` → Wizard zeigt `missing_scope` und «Neu anmelden».
- Kein Ordnerbaum (`roots()` leer, `public_info = {"selection": "google_picker"}`). Der Wizard verlinkt
  auf `/files/import/google-picker?job=<id>` (voller Seitenwechsel). Die Seite holt
  `POST /cloud-import/jobs/{id}/google-drive/picker` (Access-Token der eigenen Verbindung, API-Key,
  App-ID; `no-store`, auditiert `cloud_import.picker_token`), lädt `https://apis.google.com/js/api.js`
  mit Nonce, zeigt den Picker (Liste, Mehrfachauswahl, geteilte Ablagen, keine Ordnerauswahl, höchstens
  200) und schickt die IDs an `/selection`. Danach wieder voller Seitenwechsel in den Wizard.
- **CSP (Plan §5.3):** nur für genau `/files/import/google-picker` (`lib/csp.ts::cspVariantForPath`,
  `proxy.ts`, nie auf der Admin-Domain): `script-src` + `https://apis.google.com` (Nonce und
  `'strict-dynamic'` bleiben, kein `'unsafe-inline'`), `frame-src https://docs.google.com
  https://drive.google.com` (sonst `'none'`), `connect-src` + `apis.google.com`, `www.googleapis.com`,
  `content.googleapis.com`, `img-src` + `lh3`–`lh6.googleusercontent.com`, `drive-thirdparty.googleusercontent.com`,
  `ssl.gstatic.com`, `www.gstatic.com`. Nicht auf Admin- und Website-Domain.
  `frame-ancestors 'none'` bleibt. Die Seite hat keine App-Shell und keine App-Links, damit die
  Lockerung nicht über Client-Navigation in andere Ansichten «mitgenommen» wird. Test: `proxy.test.ts`
  und E2E `cloud-import-google.spec.ts`.
- Google-Formate: `files.export` → DOCX/XLSX/PPTX (Zeichnungen PDF); Name bekommt die Endung,
  `provider_mime` bleibt der Google-Typ (der Download entscheidet daran). `exportSizeLimitExceeded`
  (> 10 MB) → `exportLinks` auf `docs.google.com` (Bearer), sonst `too_large`. Nicht exportierbare Typen
  (Formular, Site, Verknüpfung …) haben keine Endung → `unsupported_format` im Bericht.
- Hashes: `sha256:`/`md5:` aus `sha256Checksum`/`md5Checksum` (nur Binärdateien).
- Allowlist: API `www.googleapis.com`, `docs.google.com` (Bearer), Token `oauth2.googleapis.com` (ohne
  Bearer), Umleitungsziele `*.googleusercontent.com` ohne Bearer.
- Drosselung: 429 und 403 `userRateLimitExceeded`/`rateLimitExceeded` → `ProviderThrottled`
  (`http.GOOGLE_RATE_LIMIT_REASONS`), Token-Bucket 8/s, Burst 20.

### Google Fotos

- Scope `…/auth/photospicker.mediaitems.readonly`. `POST /cloud-import/jobs/{id}/google-photos/session`
  legt bei Google eine Sitzung an (ID in `import_job.listing_state.picker_session`), Antwort nur die
  `pickerUri` (muss mit `https://photos.google.com/` beginnen). Der Wizard öffnet sie mit `/autoclose` in
  einem neuen Fenster (Google Fotos lässt sich nicht einbetten → keine CSP-Änderung) und ruft
  `…/session/poll` im Takt von `pollingConfig` auf. Bei `mediaItemsSet` wird die Auswahl
  `session:<id>` gesetzt und das Auflisten beginnt (Ordner «Google Fotos»).
- Download: `baseUrl=d` mit Bearer (Pflicht laut Google), Bearer nur an `lhN.googleusercontent.com`
  (`PhotosHostPolicy`, nie an andere `*.googleusercontent.com`). `baseUrl` gilt 60 min: Zwischenspeicher
  je Prozess (45 min), sonst liest der Adapter die Sitzung frisch.
- Videos (`VIDEO`) → `unsupported_format`. Google liefert die Bilder ohne Standort.
- Ende/Trennen: Token wird bei Google widerrufen (damit ist auch die Sitzung wertlos), eine ersetzte
  Sitzung wird sofort gelöscht.
- Grenze: Die Sitzung läuft bei Google ab (`expireTime`); sehr grosse Auswahlen müssen bis dahin
  heruntergeladen sein, sonst `not_found` im Bericht.

### Variablen (Google)

`CLOUD_IMPORT_GOOGLE_CLIENT_ID`, `CLOUD_IMPORT_GOOGLE_CLIENT_SECRET` (Secret, `_FILE`),
`CLOUD_IMPORT_GOOGLE_CLIENT_SECRET_EXPIRES` (optional, nur dann im Monitoring),
`CLOUD_IMPORT_GOOGLE_API_KEY` (öffentlich, Referrer-beschränkt) und `CLOUD_IMPORT_GOOGLE_APP_ID`
(Projektnummer). Google Drive braucht alle vier Pflichtwerte, Google Fotos nur Client-ID und Secret.
Einrichtung: RUNBOOK «Cloud-Import einrichten», Abschnitt Google.
