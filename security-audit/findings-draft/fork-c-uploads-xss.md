# Fork C — Uploads / Injection / XSS — Ergebnisse

Scope: `backend/app/api/routes/files.py`, `word_import.py`, `gallery_upload_route.py`,
`scanner.py`, `frontend/components/ui/rich-text-editor.tsx`, gezielte Injection/SSRF-Greps.
Methodik: Abschnitte 12, 13, 14, 28 des Audit-Auftrags. Keine Codeänderungen.

## Ergebnis vorab: keine neuen CONFIRMED/NEEDS_VERIFICATION-Findings in diesem Scope

Alle als "Auffälligkeit für Vertiefung" markierten Punkte aus Phase 1 wurden geprüft und
widerlegt (False-Positive-Check bestanden) oder als bereits bestehende, bewusste
Risikoakzeptanz identifiziert. Details unten, mit Evidence.

## [C-01] [INFO] gallery_upload_route.py — Registrierung geklärt, kein Bug

Status: FALSE_POSITIVE (Verdacht aus Phase 1 widerlegt)
Betroffene Dateien: `backend/app/gallery_upload_route.py`, `backend/app/api/routes/files.py:58-60`

`files.router = APIRouter(route_class=GalleryUploadRoute)` — `GalleryUploadRoute` ist die
`route_class` für den GESAMTEN `files`-Router (nicht nur einen Einzel-Endpoint). Der Handler
selbst prüft `request.method != "POST" or not path.endswith('/files/gallery-uploads')` und
reicht alle anderen Requests unverändert an `original(request)` durch. `files.router` wird in
`main.py:462` regulär über `app.include_router(files.router, prefix="/api", ...)` eingebunden.
Der Endpoint ist also korrekt registriert und erreichbar; die Custom-`route_class` dient nur
dazu, den Multipart-Parser für diesen einen Pfad durch `GalleryMultipartParser` zu ersetzen
(Dateien landen direkt auf Platte statt im Speicherpuffer). Zusätzlich prüft
`authorize_gallery_upload()` (Zeile 55-60 in `gallery_upload_route.py`) VOR dem ersten
Dateibyte per `require_writer(...)`, bevor überhaupt geparst wird — Defense-in-Depth gegen
Denial-of-Service durch unauthentifizierte grosse Uploads (die normalen FastAPI-Dependencies
prüfen am Ende nochmal).

## [C-02] [INFO] scanner.py — kein blockierender Event-Loop-Call gefunden

Status: FALSE_POSITIVE (Verdacht aus Phase 1 widerlegt)
Betroffene Dateien: `backend/app/scanner.py`, `backend/app/services/file_service.py:743-746,
1477-1494, 1515-1533`, `backend/app/services/tenant_import_service.py:727`,
`backend/app/services/submission_service.py:628`

Jeder Aufrufer von `scanner.scan_bytes`/`scan_file` (synchron, blockierend) wurde geprüft:
- `file_service.py:1494` (`save_word_import_document`): läuft nur innerhalb
  `WordImportQueueService.ingest()`, das selbst via `run_in_threadpool()` aufgerufen wird
  (siehe Kommentar Zeile 1474-1478) — kein Event-Loop zum Blockieren vorhanden.
- `file_service.py:1528` (`rescan_pending_internal_files`) und
  `submission_service.py:628` (`rescan_pending`): beides Bodies von Background-Loop-Tasks
  (`upload_pipeline_rescan_loop`/`abgabebox_rescan_loop` in `main.py`), die über
  `run_advisory_locked_loop` laufen — kein Live-Request-Handler.
- `tenant_import_service.py:727`: Teil eines Tenant-Import-Jobs (Admin-Operation, kein
  Publikums-Request-Pfad), mit explizitem Kommentar-Verweis auf einen früheren Fund
  ("audit S4, 2026-08-16") zum Nicht-Vertrauen des importierten `scan_status`.
- Jeder direkte Request-Pfad (`file_service.py:743-746, 872, 1148`) nutzt korrekt
  `await scanner.scan_many(...)`, nie das blockierende `scan_bytes`/`scan_file`.

Kein Analogon zum in `abgabebox-backend` bereits gefundenen "Critical audit finding
2026-08-27"-Muster (blockierender `scan_bytes()` auf dem Request-Pfad) im Hauptbackend.

## [C-03] [INFO] files.py — Tenant-/Ownership-Scoping bei StoredFile/ProtocolImage konsistent

Status: FALSE_POSITIVE (Verdacht aus Phase 1 — Cross-Reference zu Fork A — widerlegt für
DIESE Datei; Fork A prüft die übrigen Routendateien)
Betroffene Dateien: `backend/app/api/routes/files.py` (alle `get_by_public_id(db, StoredFile,
...)`/`ProtocolElementBlock`/`ProtocolImage`-Aufrufe), `backend/app/services/access_service.py`

Jeder der 8 Call-Sites von `public_id_service.get_by_public_id(db, StoredFile/ProtocolImage/
ProtocolElementBlock, ...)` in `files.py` wird UNMITTELBAR danach von einem passenden
`access_service.ensure_can_read_stored_file(...)`/`ensure_can_read_protocol_block(...)`-Aufruf
gefolgt (Zeilen 658-661, 675-678, 700-703, 721-724, 764-767, 778-781, 797-800, 831-834) — genau
das im `public_id_service`-Docstring geforderte Muster. `access_service.ensure_can_read_stored_file`
(`access_service.py:88-103`) selbst prüft korrekt: verlinktes Protokoll → `ensure_can_read_protocol`
(rollenabhängig inkl. `_is_restricted_reader`-Sonderfall), sonst Tenant-Gleichheit + privilegierte
Rolle, mit explizitem, kommentiertem Cross-Tenant-Sonderfall nur für geteilte Alben. Kommentare
in `access_service.py` (`can_read_template`/`can_read_protocol`) zeigen zwei bereits BEHOBENE
frühere Cross-Tenant-Bugs ("used to return True unconditionally") — Regressions-Check: aktueller
Code hat den Fix, keine Rückkehr des alten Verhaltens gefunden.
`bulk_delete_files`/`bulk_update_file_tags` (Zeile 1162-1197) grenzen `payload.file_ids` korrekt
über `service.list_tenant_files(db, user.current_tenant_id, file_ids=ids, ...)` auf den
eigenen Tenant ein (Kommentar zeigt sogar ein bewusst mitbedachtes Album-Leck-Szenario).

## [C-04] [INFO] word_import.py / ZIP-Handling — Decompression-Bomb-Schutz vorhanden

Status: FALSE_POSITIVE (Verdacht aus Phase 1 widerlegt) + eine dokumentierte, bewusste
Risikoakzeptanz (kein neuer Fund, nur vermerkt)
Betroffene Dateien: `backend/app/services/upload_pipeline.py:180-233` (Word-Import-ZIP),
`:245-294` (Galerie-ZIP), `backend/app/services/isolated_parse.py`

- Word-Import-ZIP (`_extract_matching_files_from_zip`): `MAX_ZIP_ENTRIES`-Cap,
  `MAX_ZIP_TOTAL_BYTES`-Cap auf Basis der DEKLARIERTEN Grösse pro Eintrag (nicht der
  tatsächlichen) — der Code selbst dokumentiert das bewusst: "declared, not actual, size -
  sufficient here since uploads require an authenticated writer, not an anonymous endpoint".
  Restrisiko: ein authentifizierter Writer könnte ein ZIP mit falsch deklarierter (kleiner)
  Grösse aber riesigem tatsächlichem Inhalt hochladen und so mehr Speicher/CPU auf einem
  Worker binden als die Caps vorsehen (Zip-Bomb via manipulierte Header) — Impact ist
  DoS-artig, nur durch bereits authentifizierte Tenant-User auslösbar, läuft in
  `run_in_threadpool` (blockiert nicht den Event-Loop anderer Tenants dauerhaft, nur einen
  Threadpool-Slot). Bewertung: LOW, bereits bewusst abgewogen, kein neuer Fund — für
  `TEST_RECOMMENDATIONS.md` als Kandidat für einen Regressionstest vormerken (aktuelles
  Verhalten bei extrem hoher Zip-Kompressionsrate), nicht als FINDINGS-Eintrag.
- Galerie-ZIP (`inspect_gallery_zip`/`iter_gallery_zip_entries`): stärker gehärtet -
  `GALLERY_ZIP_MAX_ENTRIES`, `GALLERY_ZIP_MAX_EXPANDED_BYTES` (20 GiB, grosszügig aber
  gedeckelt) UND zusätzlich pro Eintrag ein `read(GALLERY_DIRECT_IMAGE_MAX_BYTES + 1)`-Trick,
  der die TATSÄCHLICHE Dekompression pro Datei hart begrenzt, unabhängig von deklarierten
  Metadaten. Kein Zip-Bomb-Vektor gefunden. Passwortgeschützte ZIPs werden explizit abgelehnt.
- `.docx`-Parsing läuft isoliert in einem separaten Prozess-Pool (`isolated_parse.py`,
  `multiprocessing`) — selbst ein Parser-Exploit (python-docx/lxml) wäre auf diesen Worker-
  Prozess beschränkt, kein direkter Zugriff auf den Haupt-Event-Loop/andere Tenants' Requests.

## [C-05] [INFO] Injection/SSRF-Grep — keine neuen Funde

Status: FALSE_POSITIVE / geprüft, kein Fund
Betroffene Dateien: `backend/app/services/apple_media.py:111-141`,
`backend/app/services/export_service.py:2190-2257`,
`backend/app/services/statistics_common.py:258-303`,
`backend/app/services/domain_health_check_service.py`,
`backend/app/services/domain_verification_service.py`

- `apple_media.py::transcode_live_clip`: `subprocess.run(command, ...)` mit `command` als
  Liste fester Strings + `Path`-Objekten (kein `shell=True`, keine String-Interpolation von
  Nutzereingabe in die Kommandozeile), `-protocol_whitelist file` verhindert Netzwerkzugriff
  durch ffmpeg selbst. Kein Command-Injection-Vektor.
- `export_service.py` (pdflatex-Kompilierung): `asyncio.create_subprocess_exec(*command, ...)`
  (kein Shell), bereits explizit gehärtet gegen die naheliegenden Risiken bei
  tenant-kontrolliertem LaTeX-Inhalt: `-no-shell-escape` (kein `\write18`-Command-Exec),
  `-cnf-line=openin_any=p`/`openout_any=p` (kein `\input{/app/.env}`-Datei-Exfiltrations-Pfad),
  `preexec_fn=_limit_compile_resources` (Ressourcenlimits), 120s-Timeout. Sehr bewusst
  dokumentierter, bereits gehärteter Bereich — kein neuer Fund.
  **Cross-Reference/Empfehlung für spätere Phase (nicht Teil dieses Forks):** ob die Markdown→
  LaTeX-Übersetzung des Rich-Text-Editor-Inhalts (siehe C-06) LaTeX-Sonderzeichen (`\`, `%`,
  `$`, `_`, `{`, `}`) korrekt escaped, wurde hier NICHT geprüft (das ist die Template-
  Rendering-Logik in `export_service.py`, nicht Teil des vorgegebenen Scopes dieses Forks) -
  potenzieller Kandidat für einen späteren Fokus-Pass auf den PDF-Export, falls noch nicht
  anderweitig abgedeckt.
- `statistics_common.py`: `text(f"""...{_GROUP_TAGS_SUBQUERY}...""")` — die f-String-
  Interpolation fügt nur eine FESTE, im Code definierte SQL-Konstante ein
  (`_GROUP_TAGS_SUBQUERY`), keine Nutzereingabe; tatsächliche Werte (`tenant_id`,
  `groups_list_name`) werden korrekt über SQLAlchemy-Bind-Parameter (`:tenant_id`) übergeben.
  Kein SQL-Injection-Vektor.
- `domain_health_check_service.py`/`domain_verification_service.py`: Custom-Domain-Check
  nutzt ausschliesslich `dns.resolver` (DNS-A/CNAME/TXT-Lookup gegen die vom Tenant
  eingetragene Domain), KEINEN HTTP-Client, der eine URL abruft — kein klassischer SSRF-
  Vektor (kein Server-seitiger Request, dessen Response-Inhalt/-Timing an den Angreifer
  zurückgespiegelt würde). Kein weiterer Code gefunden, der eine tenant-/nutzerkontrollierte
  URL per HTTP abruft (kein Webhook-Feature identifiziert).

## [C-06] [INFO] rich-text-editor.tsx — kein Stored-XSS-Vektor gefunden

Status: FALSE_POSITIVE (Verdacht aus Phase 1 widerlegt)
Betroffene Dateien: `frontend/components/ui/rich-text-editor.tsx:35-69`

Editor basiert auf Tiptap/ProseMirror mit explizit reduziertem Schema
(`StarterKit.configure({heading:false, code:false, codeBlock:false, blockquote:false,
horizontalRule:false, strike:false})` — nur Bold/Italic/Listen/Absatz bleiben) und
`Markdown.configure({ html: false, ... })` — die entscheidende Einstellung: `tiptap-markdown`
parst beim Laden (`editor.commands.setContent(value, false)`, Zeile 118) eingebettetes HTML in
gespeichertem Markdown-Text NICHT als HTML, sondern als literalen Text. Persistiert wird über
`onUpdate` als `editor.storage.markdown.getMarkdown()` (Markdown-String, kein HTML). Die
Read-Only-Anzeige (`readOnly`-Prop) nutzt denselben Tiptap-Editor/dieselbe Schema-Beschränkung,
keinen separaten `dangerouslySetInnerHTML`-Renderer. Kein Weg gefunden, wie ein Nutzer über
dieses Feld beliebiges HTML/JS in den DOM einschleusen könnte. Kein `TrackedChanges`-
Erweiterungscode gelesen, der das Schema öffnen würde (kurz überflogen: reine
Decorations-Plugin-Logik für Diff-Anzeige, kein HTML-Node/-Mark) — falls eine spätere,
tiefere Prüfung der Tracked-Changes-Extension gewünscht ist, ist das ein möglicher
Nachtrag, aber kein Hinweis auf ein Problem wurde gefunden.

## Verbleibende, nicht in diesem Fork abgedeckte Punkte (Weitergabe an andere Phasen)

- LaTeX-Escaping des exportierten Rich-Text/Markdown-Inhalts im PDF-Export (siehe C-05) —
  Kandidat für einen gezielten Nachfolge-Check (Business-Logic/Export-Phase).
- ZIP-Bomb-Restrisiko bei deklarierter-statt-tatsächlicher Grösse im Word-Import-Batch
  (siehe C-04) — Kandidat für `TEST_RECOMMENDATIONS.md`, kein Findings-Eintrag.
- `TrackedChanges`-Extension (`frontend/components/ui/tracked-changes-extension.tsx`) nur
  oberflächlich gesichtet, nicht Zeile für Zeile geprüft.

Status-Updates: `security-audit/components/backend.md` und
`security-audit/components/frontend.md` wurden am Ende (Abschnitt "Phase 2 Fork C") ergänzt.
