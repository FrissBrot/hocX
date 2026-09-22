# Changelog

Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
Versionierung nach [SemVer](https://semver.org/lang/de/). Die Beta-Historie
(`v0.1.0-beta.1` bis `v0.1.1.1-beta.9.9`) wird hier nicht rekonstruiert; 1.0.0
ist der erste offiziell unterstützte Stand und muss keine älteren
Installationen aktualisieren können.

## [Unveröffentlicht]

## [1.1.2] - 2026-09-22

Wartungsrelease auf 1.1.1 mit Verbesserungen an Fotos, Word-Import und Elementeditor
sowie automatischen GitHub-Releases. Enthält Migration `0083`; sie läuft beim Deploy
automatisch. Für das Update von 1.1.1 sind keine neuen Umgebungsvariablen nötig.

### Update von 1.1.1 auf 1.1.2

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.2` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.
Wer von einer älteren Version kommt, beachtet zusätzlich die Upgrade-Hinweise zu
1.1.0 und 1.1.1 weiter unten.

- Migration `0083_photo_capture_event_link` ergänzt das optionale EXIF-Aufnahmedatum
  samt Index in `stored_file` und das Kennzeichen `event_auto_linked` in `gallery_image`.
  Bestehende Fotos und manuelle Terminzuordnungen bleiben erhalten; vorhandene
  Zuordnungen werden als manuell behandelt.
- EXIF-Aufnahmedaten werden bei neuen Galerie-Uploads gespeichert. Bestehende Fotos
  werden nicht nachträglich ausgelesen; ohne gespeichertes Aufnahmedatum gilt das
  Upload-Datum. Die Migration ordnet alte Fotos nicht automatisch Terminen zu.
  Die Zuordnung erfolgt bei neuen Uploads sowie beim Anlegen oder Ändern von Terminen.
- Vor dem Update das Datenbankbackup prüfen. Ein Image-Rollback nimmt die Migration
  nicht zurück; die zusätzlichen Spalten sind mit 1.1.1 kompatibel. Für eine vollständige
  Wiederherstellung des vorherigen Datenstands gilt der Backup-Ablauf im RUNBOOK.
- Git-Tag und GitHub-Release entstehen erst nach erfolgreicher Promotion aller Images
  durch den Release-Workflow. Der Push dieser Vorbereitung veröffentlicht noch kein Release.

### Neu

- Fotos werden nach Aufnahmedatum gruppiert und beim Upload automatisch passenden
  Terminen zugeordnet, auch innerhalb mehrtägiger Termine. Manuelle Zuordnungen haben Vorrang.
- Die Galerie trennt «Duplikate» und «Ähnliche» mit unterschiedlichen Ähnlichkeitsschwellen;
  ganze Datumsgruppen lassen sich gemeinsam auswählen.
- Im Vorlageneditor können neue Elemente direkt aus der Elementauswahl angelegt werden.
- Nach erfolgreicher Promotion aller Container-Images wird automatisch ein GitHub-Release
  mit dem Changelog der Version und einem Git-Tag auf dem getesteten Commit veröffentlicht.
- Die Versionsnummer auf der Login-Seite öffnet den zugehörigen GitHub-Release mit
  Changelog in einem neuen Tab; Entwicklungs- und Teststände verlinken die Release-Übersicht.

### Geändert

- Die Foto-Qualitätsbewertung gewichtet gute Porträts stärker.
- Galerie-ZIP-Uploads haben grosszügigere Grössenlimits statt der bisherigen 5-GiB-Grenze;
  Speicherkontingente und Schutzgrenzen für Archive bleiben wirksam.
- Der Elementdialog ist zweispaltig und breiter, die Termin-Zeitfenster sind übersichtlicher.
  Ausgewählte Terminfelder erscheinen direkt als Tabellenzeilen; Beschreibungsfelder im
  Elementdialog entfallen.
- Abgaben können Apple-Dateiformate (`.pages`, `.key`, `.numbers`, `.heic`, `.heif`) zulassen.
- Bestätigte Textabschnitt-Zuordnungen werden bei späteren Word-Importen wiederverwendet,
  auch wenn Überschrift und Elementname unterschiedlich lauten.
- Beim Nachladen von Fotos zeigt die Galerie eine dezente, auf den Fotobereich begrenzte
  Ladeanimation. Überflüssige Upload-Hinweise wurden entfernt.

### Behoben

- Die Protokollliste aktualisiert sich beim Zurücknavigieren nach einem Word-Import.
- FriendlyCaptcha-Fehlerantworten werden auch bei HTTP-Fehlerstatus ausgewertet.
- Der Link «Protokoll ansehen» und Datums-Schaltflächen im Word-Import verwenden die
  vorgesehenen Schaltflächen- und Hover-Stile.

## [1.1.1] - 2026-09-21

Wartungsrelease auf 1.1.0 mit iPhone-Foto-Support, manuellen Abgaben, Zyklusfilter für
Abgaben, Duplikaterkennung beim Upload und mehreren Fixes. Enthält die Migrationen `0079`
bis `0082`; sie laufen beim Deploy automatisch. Manuelle Schritte sind nur nötig, wenn
`FRIENDLY_CAPTCHA_VERIFY_URL` von Hand gesetzt wurde (siehe unten). Wer direkt von 1.0.x
kommt, folgt zusätzlich dem Abschnitt «Update von 1.0.x auf 1.1.0».

### Update von 1.1.0 auf 1.1.1

`HOCX_VERSION` in `.env` auf `v1.1.1` setzen, dann `./scripts/update_deploy_code.sh` und
`./scripts/deploy.sh <test|prod>`. Zu beachten:

- Das Backend-Image enthält neu `ffmpeg` und `pillow-heif`; es kommt mit dem Release-Image,
  ein lokaler Build ist nicht nötig.
- Die Abgabebox prüft das CAPTCHA jetzt gegen `https://api.friendlycaptcha.com/api/v1/siteverify`.
  Wer `FRIENDLY_CAPTCHA_VERIFY_URL` in `.env` von Hand auf den alten v2-Endpunkt gesetzt hat,
  muss die Zeile entfernen oder anpassen, sonst schlägt jede Prüfung weiterhin fehl.
- Migration `0079` gibt der eingeschränkten Rolle `hocx_abgabebox` Lesezugriff auf einzelne
  Spalten von `cycle_config` und `event_cycle` (für den Zyklusfilter der öffentlichen
  Abgabebox). Sie ergänzt nur, entzieht nichts.

### Neu

- **iPhone-Fotos (HEIC/HEIF) und Live Photos in der Galerie:** Der Upload nimmt HEIC/HEIF an
  (auch in ZIPs) und speichert sie als JPEG – Aufnahmedatum, Kamera, Ausrichtung und
  Farbprofil bleiben erhalten, das HEIC-Original wird nicht aufbewahrt. Wird zu einem Bild
  ein gleichnamiges `.mov`/`.mp4` mitgeschickt (`IMG_1234.HEIC` + `IMG_1234.MOV`, so liefert
  es der iPhone-Export), gilt es als Live Photo: der Clip wird zu einem kleinen H.264-MP4
  umgerechnet und in der Galerie beim Hovern über dem Bild abgespielt (im Viewer zusätzlich
  per «LIVE»-Knopf). Im Viewer wählt man bei «Herunterladen», ob man das Bild (JPEG), das
  Video (MP4) oder beides (ZIP mit gleichnamigen Dateien) bekommt. Der Clip ist kein eigenes Foto, zählt aber zum Speicher und wird mit dem
  Bild gelöscht (Migration `0081`). Das Backend-Image enthält dafür `ffmpeg` und
  `pillow-heif`. Nicht abgedeckt: die öffentliche Abgabebox, Android-Motion-Photos und
  ProRAW (DNG).
- **Manuelle Abgaben:** Neben «Termine» und «Liste» gibt es die Verknüpfung «Manuell» – ein
  einzelnes Abgabefeld ohne Bezug zu Terminen oder Listen, optional mit Stichtag (Migration
  `0080`). In der Abgabebox erscheint es als einzelnes Element mit dem Titel der Abgabe.
- **Abgabe erstellen/bearbeiten neu gestaltet:** Aufbau wie der Todo-Editor mit Titel im Kopf,
  Verknüpfung als Karten, Dateitypen als Chips und einer Seitenleiste mit öffentlichem Link,
  Erreichbarkeit und einer Zusammenfassung, wie sich die Abgabe verhält.
- **Zyklusfilter für Abgaben nach Terminen:** Eine Abgabe kann auf Termine eines Zyklus
  eingeschränkt werden (Zyklus-Konfiguration plus Versatz: `0` = aktueller, `-1` = voriger
  Zyklus usw., Migration `0079`). Eine Zyklus-Konfiguration, die noch von einer Abgabe
  verwendet wird, lässt sich nicht löschen; Mandanten klonen übernimmt die Zuordnung. Die
  öffentliche Abgabebox wertet den Filter selbst aus (nur lesender Zugriff auf `cycle_config`
  und `event_cycle`).
- **Leerzustände auf allen Listenseiten:** Dashboard, Protokolle, Todos, Bussen, Finanzen,
  Statistiken, Listen, Teilnehmende, Termine, Abgaben, Fotos, Dateien, Benutzer und
  Dokumentvorlagen zeigen ohne Daten eine erklärende Startansicht mit direkter Aktion.
  Neu dabei: «Busse erfassen» (damit «+ Busse» funktioniert), «Rollen erklären» in der
  Benutzerverwaltung und «Standard-Layout verwenden» bei den Dokumentvorlagen. Filter und
  Kopfzeilen-Knöpfe erscheinen erst, wenn Daten vorhanden sind.
- **Duplikaterkennung vor dem Scan** (Migration `0082`): Byteidentische Dateien werden in der
  App (Dokumente, Fotos, Word-Import) vor Virenscan und Verarbeitung als Duplikat gemeldet.
  Bei konvertierten Dateien (z. B. HEIC → JPEG) zählt der Hash des Originals. Die öffentliche
  Abgabebox überspringt Duplikate desselben Abgabe-Elements still und bestätigt den Upload
  normal. Gleichzeitige Uploads werden pro Mandant über PostgreSQL-Sperren serialisiert, so
  dass auch parallel abgeschickte Kopien nur einmal gespeichert werden.

### Geändert

- **Dokumentvorlagen-Seite neu gestaltet:** Layouts und Bausteine-Bibliothek mit Kartenlayout,
  Liste/Editor-Aufteilung, Reitern im Editor und kompakten Auswahlkarten; der Upload-Dialog
  für Bausteine ist zweispaltig mit Slot-Auswahl, Ablagefläche und Bibliotheks-Übersicht.
- Ein hochgeladenes Mandantenlogo wird in der Seitenleiste angezeigt.
- Word-Import-Assistent: Der Feldname, der eine Zeile rot hält, ist rot umrandet und mit
  Hinweistext sowie einer Zusammenfassung offener Felder markiert; nicht zugeordnete Namen
  heissen «– nicht zugeordnet –» statt «Keinen verknüpfen».
- Matrix-Designer: native Auswahlfelder sehen aus wie die übrigen Dropdowns.
- Speicher-Seite: Abstände der Kennzahlenkarten und der Aufschlüsselung korrigiert.

### Behoben

- **Abgabebox-CAPTCHA:** Die Lösung wurde gegen den v2-Endpunkt geprüft, obwohl das Widget
  FriendlyCaptcha v1 ist; jede Prüfung schlug mit 404 fehl, das Widget lud endlos neu und der
  Sicherheitscheck wurde nie abgeschlossen. Der Standard zeigt jetzt auf `/api/v1/siteverify`;
  abgelehnte Prüfungen werden mit Status, Fehlern und URL protokolliert.
- **Automatisch erzeugtes Folgeprotokoll:** Es wurden interne Zahlen-IDs statt öffentlicher
  UUIDs an die Validierung übergeben (Fehler bei `template_id` und `event_id`). Die
  konfigurierte Folgevorlage wird aus ihrer öffentlichen UUID aufgelöst (alte Zahlenwerte
  gehen weiterhin).
- Datei-Uploads, die mit einem Abgabe-Element verknüpft sind, zählen jetzt als Abgabe.
- Fotos: Ähnliche Fotos öffnen im Betrachter, das Album-Cover lässt sich nicht mehr
  versehentlich ziehen, und Albumtitel bleiben in allen Designs lesbar.
- Frontend: Runtime-Konfiguration und Theme-Skript stehen als normale `<script>`-Tags im `<head>`;
  die React-19-Warnung «Encountered a script tag while rendering React component» entfällt.
- Galerie-Upload: Ein Duplikat-Ergebnis geht auch dann genau einmal an die Oberfläche, wenn
  der Job vor der ersten Statusabfrage fertig ist.

## [1.1.0] - 2026-09-19

Zweite stabile Version. Sie enthält alle seit 1.0.0 gemergten Fixes und
Hardening-Massnahmen sowie die unten aufgeführten neuen Funktionen. Vor dem Update bitte die
mit **Achtung beim Update** markierten Punkte lesen (Migrationen `0064` bis `0078`).

### Update von 1.0.x auf 1.1.0

Ablauf auf jedem Host (Test wie Prod): `HOCX_VERSION` in `.env` auf `v1.1.0` setzen, dann
`./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` (oder
`update_deploy_code.sh --deploy`). `deploy.sh` erledigt dabei alles Weitere selbst:

- **`.env` wird migriert** (`scripts/lib/env_migrate.sh`, Sicherung als `.env.bak-<Zeitstempel>`):
  `PHOTO_WORKER_DB_PASSWORD` und `PHOTO_WORKER_DATABASE_URL` werden neu erzeugt (eigene
  DB-Rolle `hocx_photo_worker`, Migration `0067`), die entfernte Variable `TRAEFIK_WEB_DOMAIN`
  wird gelöscht. Vorhandene Werte bleiben unverändert.
- **`storage-local/thumbnails`** wird angelegt und für den Backend-Benutzer (Gruppe 5001)
  freigegeben; der neue Dienst `photo-analysis-worker` wird signaturgeprüft, gestartet und
  in Smoke-Checks und Rollback einbezogen.
- **Migration `0078` (ein Konto = ein Mandant)** bricht ab, wenn Konten mit mehr als einer
  aktiven Mandanten-Mitgliedschaft oder ganz ohne Mandant existieren; die Datenbank bleibt
  dann unverändert und die alte Version läuft weiter. Entweder vorher bereinigen oder
  `HOCX_SINGLE_TENANT_RESOLUTION=auto` in `.env` setzen (behält je Konto die Mitgliedschaft
  des Standard-Mandanten, sonst die höchste Rolle; Konten ohne jeden Mandanten werden
  **gelöscht**). Das Backup vor dem Update liegt in `backups/`.
- Nur **Test**: Nach dem Deploy wird der Demo-Mandant "Jubla Sonnenberg" neu aufgebaut.
  Optional kann `DEMO_TOTP_SEED` in `.env` gesetzt werden.
- Der Rollback startet die vorherigen Images, macht Datenbankmigrationen aber nicht rückgängig;
  ein Zurück auf 1.0.x nach erfolgreicher Migration braucht das Backup (RUNBOOK Abschnitt 5).

### Geändert

- **Ein Konto gehört genau einem Mandanten** (Migration `0078_single_tenant_users`): Die
  Mehr-Mandanten-Mitgliedschaft ist entfernt - inklusive Mandantenwechsel, Standard-Mandant
  und `POST /api/auth/select-tenant`. Mandant und Rolle stehen direkt am Benutzer
  (`app_user.tenant_id`/`role_id`); die Tabellen `user_tenant_role` und `user_role` sowie
  `app_user.default_tenant_id` entfallen. Wer in mehreren Vereinen arbeitet, braucht pro
  Verein ein eigenes Konto. Folgen:
  - Ein Mandanten-Admin hat volle Hoheit über die Konten seines Mandanten und kommt an keine
    Konten anderer Mandanten heran (löschen, Passwort/E-Mail/Rolle ändern). Das schliesst die
    Lücke, dass ein Admin über einen gemeinsam genutzten Account fremde Mandanten treffen konnte.
  - Der letzte aktive Admin eines Mandanten kann weder herabgestuft noch deaktiviert oder
    gelöscht werden (bisher nur Herabstufen/Entfernen).
  - Benutzer zusammenführen geht nur noch innerhalb eines Mandanten. Ein Teilnehmer-Login mit
    einer E-Mail-Adresse, die bereits ein Konto eines anderen Mandanten besitzt, wird mit
    Fehler 409 abgelehnt.
  - Platform-Admin-Panel: Benutzer werden beim Anlegen einem Mandanten zugeordnet, danach ist
    der Mandant fest. In den Mandanten-Einstellungen entfällt "Benutzer hinzufügen"; "Entfernen"
    heisst "Löschen" und löscht das Konto.
  - Mandanten klonen kopiert keine Benutzer mehr (der Klon startet ohne Konten, alle
    Benutzerverweise auf kopierten Zeilen werden zurückgesetzt). Export-Format Version 3
    enthält nur die Benutzer des exportierten Mandanten; der Import liest Version 2 und 3 und
    übernimmt keine E-Mail-Adresse, die auf der Zielinstallation schon in einem anderen
    Mandanten existiert (Warnung statt Verknüpfung).
  - Sitzungs-Cookies aus der Zeit davor bleiben gültig; ihr `tenant_id`-Anspruch wird ignoriert.
  - **Achtung beim Update:** Die Migration bricht ab, solange Konten mit mehr als einer aktiven
    Mandanten-Mitgliedschaft (oder ganz ohne Mandant) existieren, und listet sie auf. Entweder
    vorher bereinigen oder mit `alembic -x single_tenant_resolution=auto upgrade head` je Konto
    die Mitgliedschaft des Standard-Mandanten (sonst die höchste Rolle) behalten und die
    übrigen verwerfen. `-x seed_demo=true` (Dev/E2E/CI) löst automatisch auf.

- **Navigation neu gegliedert**: Die Seitenleiste ist in Dashboard / Arbeiten / Stammdaten /
  Konfiguration / Administration gruppiert, die Einzel-Gruppe "Tools" entfällt (`/tools`
  leitet auf die Import-Warteschlange um). Zusammengehörige Seiten (Dashboard + Statistiken,
  Konten + Bussen, Vorlagen + Elemente + Dokument-Layouts, Dokumente + Fotos) haben eine
  Tab-Leiste. Routen und Rollenprüfungen bleiben unverändert.
- **Einheitliches Design-System**: Gemeinsame Design-Tokens (`design/tokens.css`) für Hauptapp
  und Abgabebox, verbindliche Regeln in `design/DESIGN.md` und ein Prüfskript
  (`scripts/check-design-rules.py`), das in der CI läuft. Überarbeitet wurden unter anderem
  Todo-Editor, Konto-Dialog, Benutzer-Bearbeitung, Listen-Seitenleiste, Abgaben-Zuordnungen
  und alle Tabellen (gemeinsame maximale Breite).
- **Einheitliche Upload-Pipeline**: Protokollbilder, Galerie- und Word-Import-Uploads teilen
  sich Virenprüfung, Prüfsumme und Vorschaubilder sowie eine gemeinsame Nachprüfungsschleife.
  Die Lock-IDs aller Hintergrundschleifen liegen zentral in `app.core.background_loops`.
  Im Platform-Admin-Panel zeigt die neue Seite "Datei-Pipeline" den Prüfstatus je Datei.
- Dateien-, Vorschau- und Tag-URLs verwenden durchgängig die öffentliche UUID statt interner
  Zahlen-IDs.

### Hinzugefügt

- **Fotos-Galerie**: direkter Bild-Upload (einzelne Dateien oder ZIP-Archive) auf der
  "Dateien"-Seite, unabhängig von Protokoll/Word-Import/Abgabebox. Mit Tags,
  Duplikat-Warnung (Perceptual Hash) und Vorschaubildern.
- **Dateien-Upload**: Dokumente (PDF, Word/Excel/PowerPoint, OpenDocument, RTF, Text/CSV,
  ZIP) lassen sich direkt auf der "Dateien"-Seite hochladen - gleicher Upload-Dialog wie bei
  den Fotos (Drag & Drop, Warteschlange, Tags, Virenprüfung). Optionaler Bezug zu einem
  Termin, Abgabe-Element oder Zyklus, der in der Spalte "Bezug" erscheint.
  Bei einem Abgabe-Element gelten für Datei- und Foto-Uploads die Dateiregeln der Abgabe
  (erlaubte Dateitypen, maximale Dateigrösse, maximale Anzahl Dateien pro Element - inklusive
  der bereits über die Abgabebox eingereichten Dateien).
- **Speicherkontingent**: Mandanten-Speichernutzung im Adminportal einsehbar, mit pro
  Mandant konfigurierbarem Limit (Speicherkontingent-Verwaltung, eigene Storage-Seite).
- **Word-Import-Verbesserungen**: Matrix-Spalten-Zuordnung für Tabellen mit variablen
  Spalten, Unterstützung für mehrtägige Termine (Zeiträume statt Einzeldatum), sowie
  eine "zuletzt gewählte Vorlage", die beim nächsten Öffnen des Import-Assistenten
  automatisch vorausgewählt wird.
- **Tenant-Export/Import-Erweiterungen**: verifizierte Custom-Domains,
  Fotos-Galerie-Zuordnungen und die Word-Import-Vorlagen-Fremdschlüssel-Referenz
  werden jetzt mitexportiert/-importiert.
- **Tabellen-Snapshot-Funktion**: Zeilen einer "Zeile aus Liste"-Tabellenzeile können
  auf "Historische Daten verwenden" umgestellt werden - die Zeile zeigt dann die
  eingefrorenen Werte des Zyklus, in den das jeweilige Protokoll fällt, statt immer
  die aktuellen Live-Daten des verknüpften Listeneintrags.
- **Fotos/Dateien-Neugestaltung**: eigenständige "Fotos"-Seite mit nach Datum
  gruppierter Galerie (inkl. Zyklus-/Termin-/Protokoll-Kontext je Datumsgruppe),
  Mehrfachauswahl mit Sammelaktionen (Album, Tags, Best-of, Löschen), ein
  Vollbild-Fotobetrachter mit Analyse-Kennzahlen (Schärfe/Belichtung/
  Gesichtsqualität), ein mandantenweiter Analyse-Fortschrittsbalken, ein
  "Ähnliche"-Tab zur Serien-Bereinigung ("Nur beste behalten") sowie ein
  "Alben"-Tab mit Cover-Collage und Foto-/Best-of-Zahlen pro Album. Die
  "Dateien"-Seite zeigt jetzt Dokumente/Fotos/Speicher-Kennzahlen und eine
  Tabellenansicht statt der bisherigen Kachelliste.
- **Abgabe-Links**: Die öffentliche Abgabebox ist nur noch über einen Link mit zufälligem
  Schlüssel erreichbar (`<abgabebox-domain>/<schlüssel>`), nicht mehr über den
  Mandanten-Slug. Unter *Abgaben → Links* lassen sich beliebig viele Links mit Klarnamen
  anlegen, umbenennen, als Standard festlegen, mit neuem Schlüssel versehen und löschen; im
  Abgabe-Konfigurator wird gewählt, über welche Links eine Abgabe erreichbar ist. Jeder
  Mandant startet mit einem Standard-Link, der bei neuen Abgaben vorausgewählt ist.
  Die restricted DB-Rolle der Abgabebox darf dafür nur `id`, `tenant_id` und `token` der
  Links sowie die Zuordnung Abgabe↔Link lesen (Migration `0075_submission_link`).
  **Achtung beim Update:** Bestehende Mandanten erhalten automatisch einen Standard-Link, an
  dem alle bisherigen Abgaben hängen - die alten Adressen mit Mandanten-Slug funktionieren
  aber nicht mehr und müssen durch die neuen Links ersetzt werden. Die Umgebungsvariable
  `DEFAULT_TENANT_SLUG` entfällt. Beim Klonen/Importieren eines Mandanten entstehen immer
  neue Schlüssel (Tokens werden nie exportiert oder übernommen).

- **Foto-Auswahl und Qualitätsanalyse**: Schärfe und Belichtung werden bei jedem Upload
  berechnet, die Gesichtsqualität übernimmt der neue Dienst `photo-analysis-worker`
  (automatisch ausserhalb der Stosszeiten und nur bei geringer Serverlast). Ähnliche Fotos
  werden per Perceptual Hash zu Serien gruppiert (nach EXIF-Drehung und Randbeschnitt);
  "Nur beste behalten" räumt Serien auf. Migrationen `0066`-`0072`, `0076`, `0077`.
- **Automatische Foto-Alben**: Pro Zyklus, Abgabe und Abgabe-Element entsteht automatisch ein
  Album mit Best-of-Auswahl ("Stern"), die sich von Hand ergänzen oder ausschliessen lässt.
  Uploads aus der Abgabebox werden periodisch einsortiert.
- **Asynchrone Galerie-Uploads**: Bild-Uploads und ZIP-Archive bis 5 GB werden nur noch auf
  die Platte gestreamt und im Hintergrund verarbeitet; der Dialog schliesst sich sofort, ein
  Fortschrittsbalken zeigt den Stand (Migration `0073`). Dafür gibt es einen eigenen
  Traefik-Router ohne Standard-Grössenlimit. **Achtung beim Update:** Traefik-Konfiguration
  und Backend-Speicherlimit (`mem_limit`) aus den mitgelieferten Compose-Dateien übernehmen.
- **Demo-Mandant**: Jedes Test-Deployment (nie Prod) legt einen vollständig befüllten
  Demo-Mandanten "Jubla Sonnenberg" an (Teilnehmende, Termine, Protokolle, Fotos, Abgabe);
  ein fester TOTP-Seed für Demo-Konten ist konfigurierbar.

### Behoben

- Die Audit-Runde über `v1.0.0..1.1` hat 13 kritische und mehrere mittlere/niedrige Befunde
  ergeben, alle sind behoben. Wichtigste Punkte:
  - Drei Hintergrundschleifen der Foto-Funktionen starteten wegen fehlender Lock-IDs nie;
    fehlerhafte Durchläufe beenden eine Schleife nicht mehr dauerhaft und blockieren die
    Event-Loop nicht mehr.
  - Das Speicherkontingent wird jetzt beim Upload verbindlich durchgesetzt (race-frei).
  - Beim Tenant-Import wird `GalleryImage.event_id` korrekt umgeschrieben, sodass importierte
    Fotos nicht mehr fremden Terminen zugeordnet werden.
  - Ein Platform-Admin kann seinen letzten TOTP-Faktor nicht mehr löschen (Aussperr-Schutz).
  - Veraltete Antworten überschreiben in der Serien-Bereinigung und in historischen Listen
    keine neueren mehr.
  - Zyklus-Snapshots holen verpasste Zyklen nach; die Auswahl des "besten Fotos" ist in
    Serien-Bereinigung und Alben identisch.
  - Diverse Performance-Verbesserungen (Album-Sync, Hash-Abgleich, Snapshot-Rekonstruktion).
- Migration `0067`: Downgrade scheiterte, solange die Rolle noch Berechtigungen hielt.

## [1.0.0] - 2026-08-27

Erste stabile Version.

### Geändert

- Die 74 inkrementellen Alembic-Migrationen der Beta-Reihe wurden zu einer
  einzigen Baseline-Migration (`0001_initial_schema`) zusammengefasst. Neue
  Installationen erhalten direkt den aktuellen Schema-Stand; ein Upgrade-Pfad
  von einer bestehenden Beta-Installation auf 1.0.0 ist nicht vorgesehen.
