# Changelog

Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
Versionierung nach [SemVer](https://semver.org/lang/de/). Die Beta-Historie
(`v0.1.0-beta.1` bis `v0.1.1.1-beta.9.9`) wird hier nicht rekonstruiert; 1.0.0
ist der erste offiziell unterstützte Stand und muss keine älteren
Installationen aktualisieren können.

## [Unveröffentlicht]

### Geändert

- **Backups im Plattform-Admin neu (Design «hocX Backups»):** Übersicht mit Gesamtstatus, offenen
  Problemen samt passender Aktion, laufendem Auftrag mit Schrittleiste, den drei Nachweisen
  (erstellt, geprüft, Restore getestet) mit Intervall und Fälligkeit, einer 7-Tage-Leiste der
  geplanten Läufe (auch verpasste; bei mehr als 8 Läufen pro Tag als Tageszusammenfassung, mit
  Tabellenalternative), Speicher und Infrastruktur. Verlauf mit Zählern je Status, Kurzfassung je
  Auftrag (z. B. entfernte Punkte, geprüfte Inhalte) und Details als Seitenleiste;
  Wiederherstellung als Assistent mit Schrittleiste, Punkt-Auswahl mit Nachweisen und Verlauf
  inklusive Restore-Tests; Einstellungen mit Tagesleiste der Läufe in Schweizer Zeit (Sommerzeit
  berücksichtigt) und Schätzung der Aufbewahrung. Reiter, Filter und geöffneter Auftrag stehen in
  der URL. Am Navigationseintrag zeigt ein Punkt, ob ein Backup läuft oder ein Problem besteht.
- Support-Admins (nur lesen) bekommen von der Backup-API weder Adresse und Benutzer der Storage Box
  noch rohe Fehlermeldungen; die Oberfläche zeigt den übersetzten Fehlercode.

### Behoben

- **Vollständige Wiederherstellung behält das Audit-Log:** Der Datenbanktausch setzte das
  Audit-Log auf den Stand des Sicherungspunkts zurück; Einträge seit dem Punkt fehlten danach im
  laufenden System. Sie werden jetzt mitgenommen, und Ergebnis und Ende jeder Wiederherstellung
  stehen als `backup.restore.finished` im Audit-Log.

## [1.6.0] - 2026-11-24

### Hinzugefügt

- **Protokoll-Editor neu (Design «Protokoll-Editor 1a», 1.6):** Kopf mit Status, Titel,
  Speicherstatus (speichert / gespeichert / offline mit wartenden Änderungen / Fehler mit Sprung zum
  Block), Anwesenden, Suche, Export und dem Knopf für den nächsten Schritt; links eine Gliederung
  mit Kurzinfo je Punkt, rechts alle Punkte untereinander. Texte, Aufzählungen und Pendenzen werden
  gelesen, bis man einen Block mit **Bearbeiten** (oder Strg/⌘+Enter) öffnet; nur dort lädt der
  Editor. Unten ein Dock mit den Schubladen **Notizen**, **Pendenz** (neu mit «Zu Punkt»),
  **Anliegen** und **Status & Zusammenarbeit** (wer wo mitarbeitet, Anwesenheit, Tastenkürzel,
  «Status zurücksetzen»). Auf Tablets lässt sich die Gliederung einblenden.
- **Traktanden im Protokoll bearbeiten:** hinzufügen (unter der Gliederung), umbenennen und im
  Vorbereitungsmodus aus- und einblenden, sortieren per Ziehen oder Alt+Pfeil (eine Anfrage, live bei
  allen). Die Vorlage ändert sich dabei nie: beim **Protokoll abschliessen** listet die Rückfrage
  jede Abweichung einzeln und übernimmt nur die gewählten in die Vorlage (mit dem Recht zur
  Vorlagenbearbeitung, sonst nur Hinweis).
- **Dateien importieren (Datei-Import P0, 1.6):** Unter *Dateien › Importieren* übernimmt ein Verein
  eine bestehende Ablage in einem Durchgang - als ZIP-Archiv (auch mehrere Teilarchive von
  Google Takeout, der Ordner «Takeout» wird erkannt) oder als Ordner-Upload aus dem Browser (nur die
  benötigten Dateien werden übertragen). Regeln nach Ordner, Pfad-Muster und Dateiname (regulärer
  Ausdruck, ReDoS-sicher über RE2) setzen Tags, ein geschätztes Aufnahmedatum (nur wenn es fehlt),
  schliessen Dateien aus oder ordnen Bilder in Alben ein (bestehendes Album oder ein Album je
  Ordner; abschaltbar und standardmässig aus, gleichnamige Alben werden ergänzt). Bei Google Takeout
  übernimmt der Import das Aufnahmedatum aus den Metadaten-Dateien, wenn das Foto selbst keines hat.
  Bereits vorhandene Dateien bekommen Tags und Alben dazu («Duplikat, ergänzt»). Vorschau mit Treffern je Regel, Konflikten und Kontingent-Prüfung vor dem Start; der
  Import läuft im Hintergrund (job-worker, Job `cloud_import`) mit Fortschritt, Abbruch und
  Fortsetzen, danach ein Bericht je Datei. Jede Datei durchläuft die normale Upload-Pipeline
  (Virenprüfung, Inhaltstyp, Grössen, Duplikate, Kontingent). Grenzen: 50 000 Dateien und 100 GB je
  Import, ein Import je Verein gleichzeitig.
- Neue Berechtigung **Dateien importieren** (`files.import`), standardmässig nur für Administratoren.
- **Upload-Verlauf (1.6):** Jeder Upload ist ein Vorgang – über alle Pakete eines Dialogs, den
  Vorab-Abgleich und vom Browser abgelehnte Dateien hinweg. *Fotos › Uploads* und *Ablage › Uploads*
  zeigen je Upload Person, Weg (Foto, Ablage, Pendenz, Abgabebox, persönlicher Link, Word-, Datei-
  und Plattform-Import, Protokollbilder je Protokoll und Tag), Bezug und Ergebnis («48 hochgeladen ·
  3 Duplikate · 1 abgelehnt»). Im Vorgang: Fotoraster nur dieses Uploads mit «Alle dieses Uploads
  auswählen» (bis 10 000, Bulk-Aktionen in Teilen mit Fortschritt und Abbruch), Ergebnisliste je Datei
  mit Grund, Kameras (gleiche Modelle über ein verschlüsseltes Kürzel der Seriennummer getrennt,
  Vorschlag aus der GPS-Zeit) und Datumskorrekturen. Nach dem Upload «Bearbeiten» im Hinweis und ein
  ausblendbarer Hinweisstreifen; die Foto-Ansicht verlinkt den Upload. Sichtbar mit dem Recht des
  Bereichs, eigene Uploads immer. Ältere Uploads werden rekonstruiert und so gekennzeichnet.
  Vereinsexport und Datenauskunft enthalten den Verlauf mit den Einträgen je Datei (auch abgelehnte
  Dateinamen), die Datei-Importe mit Quellpfad und die Datumskorrekturen.
- **Aufnahmedatum verschieben** um Tage, Stunden und **Minuten** mit Richtung früher/später oder
  **nach Referenzfoto** (richtige Uhrzeit eingeben oder gleicher Moment einer anderen Kamera),
  **Vorschau** mit Tages- und Terminwechseln und **Rückgängig** (exakt, solange die Fotos existieren).
  Grosse Auswahlen werden in Teilen zu 500 verarbeitet. Termin-Zuordnungen werden nur für Fotos
  neu berechnet, deren Tag wechselt.
- **Datum setzen im Upload-Vorgang:** Neben dem Verschieben setzt «Datum setzen …» ein festes Datum
  (optional mit Uhrzeit) für alle Fotos eines Uploads, für die Fotos einer Kamera oder für die in der
  Ergebnisliste ausgewählten Dateien - mit Vorschau, Rückgängig im Reiter «Datumskorrekturen» (zeigt
  den gesetzten Wert) und Audit-Eintrag mit Bezug zum Upload. Dokumente haben kein Aufnahmedatum,
  bleiben unverändert und werden für Personen mit «Dateien verwalten» als solche gemeldet.
- **Kamera-Kürzel für bestehende Fotos:** Der neue Hintergrundjob «Kamera-Kürzel nachtragen»
  (`camera_serial_backfill`, job-worker) liest bei Fotos von vor 1.6 die Seriennummer aus der EXIF und
  speichert wie beim Upload nur das Kürzel je Verein (nie die Seriennummer). Er arbeitet je Verein in
  Teilen, merkt sich den Stand und setzt nach einem Neustart fort; gleiche Kameramodelle erscheinen
  danach auch in älteren Uploads getrennt. Migration `0253_camera_serial_backfill`.
- **Ablehnungs-Zeilen im Upload-Verlauf:** Dateien, die beim ZIP-Upload in Fotos (kein Bild, zu
  gross, beschädigter Eintrag, ungültiges oder leeres ZIP), bei Protokollbildern (Format, Grösse,
  Virenfund, Duplikat, Speicher voll) oder in der Abgabebox (Typ, Grösse, Inhalt, zu viele Dateien,
  Speicher, Virenfund, Duplikat) abgelehnt werden, erscheinen als Zeile mit Grund im Vorgang - bei
  ZIP-Einträgen mit dem Namen des Archivs. Die Abgabebox meldet dafür je Datei eine Zeile in ihr
  Protokoll, ohne neue Rechte; Absender sehen weiterhin keine Duplikat-Meldung. Migration
  `0254_upload_rejections`.
- Mehrfachauswahl **Termin zuordnen**: fest mit einem Termin verknüpfen oder an die automatische
  Zuordnung nach Datum zurückgeben.
- **Foto-Standorte (1.6):** Fotos mit GPS bekommen automatisch einen Ortsnamen («Nähe
  Blüemlisalphütte, Kandersteg BE») – präzise Orte wie Hütten, Gipfel, Pässe, Seen und Flurnamen in
  der Nähe, sonst die Ortschaft mit Kanton bzw. Land. Der Ort steht in der Foto-Ansicht unter dem
  Dateinamen; ein Klick zeigt Fotos aus der Umgebung. Die Fotosuche schlägt passende Orte vor
  (Treffertyp «Ort», unscharf, Umlaute egal) und filtert dann auf den Umkreis – Gipfel/Hütte ~2 km,
  Dorf ~5 km, Stadt/Region ~20 km, mit «+10 km» erweiterbar, näher steht weiter oben, kombinierbar
  mit Suchbegriffen und Tags. Ortsnamen sind auch als Suchwörter auffindbar. Fotos ohne GPS
  bekommen ihren Ort von Hand (Foto-Ansicht, Mehrfachauswahl **Ort**, *Upload › Ort für alle Fotos
  setzen*, mit Rückgängig, `photos.manage`, auditiert); echtes GPS wird nie überschrieben.
  Ortsnamen sehen alle, die das Foto sehen; Koordinaten bleiben bei der bisherigen Berechtigung.
  Freigabe-Links und Partner geteilter Alben bekommen keinen Ort. Ortsdaten liegen offline in der
  Datenbank (GeoNames CC BY 4.0, swissNAMES3D © swisstopo); keine Koordinaten gehen an Dienste.
- **Traktanden im Protokoll anpassen (Protokoll-Editor 1a, Backend):** Traktanden lassen sich im
  Protokoll hinzufügen (mit leerem Textblock, nur in diesem Protokoll), umbenennen, aus-/einblenden
  und in einem Schritt umsortieren (`PUT /api/protocols/{id}/element-order`, 409 bei veralteter
  Reihenfolge). Die Vorlage ändert sich dadurch nie; andere Teilnehmende sehen die Änderungen live.
  «Elemente aus Vorlage neu laden» behält hinzugefügte Traktanden (auch leere), eigene Titel,
  eigene Sichtbarkeit und eine eigene Reihenfolge. Folgeprotokolle entstehen weiter aus der Vorlage.
- **Abweichungen von der Vorlage beim Abschliessen:** `GET /api/protocols/{id}/template-changes`
  listet neue, umbenannte, ausgeblendete Traktanden und eine geänderte Reihenfolge mit alten und
  neuen Werten; `POST …/template-changes/apply` übernimmt eine Auswahl in die Vorlage (Recht
  «Vorlagen bearbeiten», eine Vorlagenversion, Audit-Eintrag; geteilte Bausteine werden nur für
  diese Vorlage umbenannt). Das Abschliessen selbst hängt nicht davon ab.
- **Wo ist wer:** Der Live-Kanal eines Protokolls meldet gedrosselt, welches Traktandum bzw. welchen
  Block die anderen Teilnehmenden gerade ansehen oder bearbeiten (`presence_focus`).
- **Bildunterschrift nachträglich ändern** (`PATCH /api/protocol-images/{id}`, höchstens 500 Zeichen,
  Regeln wie beim Bearbeiten des Blocks).
- Vorlagen-Traktanden haben eine Sichtbarkeit (`is_visible`), die neue Protokolle übernehmen
  (Migration `0270_protocol_agenda_edit`).

- **Konsole › Audit-Log: gespeicherte Ansichten und Token-Suche (1.6):** Ansichten «Alle Ereignisse»,
  «Fehlgeschlagen», «Anmeldungen», «Löschungen», «Plattform-Admin» und «Datenschutz» mit Zählern für
  den gewählten Zeitraum. Das Suchfeld versteht `quelle:`, `aktion:` und `vorgang:` (z. B.
  `vorgang:gelöscht`); `person:` und `mandant:` öffnen die Auswahl (Personen über die Admin-Suche,
  Mandanten über die Mandantensuche) – in der Adresse stehen nur IDs, nie Namen.
- **Konsole › Sicherheit › Alarmregeln (1.6, vorher «Warnungen»):** alle zehn Regeln mit aktuellem
  Messwert gegen die Schwelle – auch unterhalb («ruhig», «nahe Schwelle», «ausgelöst») –, Bedingung in
  Worten, Kurve der letzten 24 h je Regel (mit Tabellenalternative), Auslösungen der letzten 30 Tage
  aus dem Systemmonitor und die wirksamen Einstellungen (nur lesen, geändert wird in der
  Serverkonfiguration). Ausgelöste Warnungen lassen sich weiterhin quittieren, jetzt mit Notiz.
- **Konsole › Sicherheit › Anmeldeereignisse neu (1.6):** Filter nach Konto-, Netz- und
  Geräte-Pseudonym (Klick auf ein Pseudonym oder Eingabe wie `netz:3f9a1c07`), Land, Typ, Ergebnis
  und Mandant (Suche statt Mandantenliste); der Zeitraum ist Pflicht (1 h bis 14 Tage). Ein
  Histogramm zeigt die gefilterten Ereignisse (mit Tabellenalternative), die Ergebnis-Reiter zählen
  mit. Ansicht «Nach Netz» bzw. «Nach Konto» gruppiert die Treffer. Blättern ohne Offset
  (Keyset), Live-Aktualisierung alle 30 s. Das Detail erklärt das Risiko mit den Gewichten der
  Gründe (ab 1.6 gespeichert, ältere Ereignisse nur mit Gründen), zeigt «Spur verfolgen» (gleiches
  Netz, Konto, Land) und bietet «Quelle sperren» – sperrt das Netz des Ereignisses (/24, /48) mit
  Passkey-Bestätigung. Filter stehen in der URL, nur als Codes und Pseudonym-Präfixe.
- **Konsole › Sicherheit › Sperren neu (1.6):** Abwehrleiter mit allen fünf Stufen (Stufen 1–3 als
  Ereignisse der letzten 24 h, 4–5 als aktive Sperren), Karten je Sperre mit Countdown, Grund,
  Zähler «Abgewiesen», gesetzt von, **Verlängern** (macht die Sperre zur manuellen Sperre Stufe 5,
  Begründung Pflicht) und Aufheben – beides mit Passkey-Bestätigung und Audit-Eintrag. Verlauf der
  letzten 7 Tage als Zeitleiste je Quelle (mit Tabellenalternative). Die manuelle Sperre bietet
  Voreinstellungen (1 h bis 30 Tage) und freie Minuten. Neu kann eine Sperre auch einen
  **Netz-Fingerprint** (Pseudonym der Anmeldeereignisse, /24 bzw. /48) treffen; Plattform-Admins
  bleiben ausgenommen. `block.set`/`block.clear` tragen jetzt gekürztes Subjekt, Admin und
  (vorbereitet für 1.7) Vorfall.
- **Aufgabenpakete: Pendenz erst vor dem Termin erstellen:** Bei Wiederholung «Pro Termin» lässt
  sich optional festlegen, dass die Pendenz eines Termins erst X Tage vor dem Termin entsteht
  (`recurrence_json.create_days_before`, 0–3650, keine Migration). Der tägliche Lauf
  `task_package_rollover` und die Abgleiche nach Terminänderungen legen sie ab dem Stichtag an
  (Schweizer Datum, spätestens am Folgetag), auch für Termine kurz nach dem Zykluswechsel (die
  Pendenz gehört zum neuen Zyklus, kein Duplikat beim Wechsel); verschobene Termine zählen mit dem
  neuen Datum, schon angelegte Pendenzen bleiben und werden wie bisher nachgeführt. Die Vorschau zeigt «Entsteht am …»,
  die Übersicht «erstellt X Tage vor dem Termin»; liegt die Fälligkeit vor dem Erstelldatum, weist
  das Formular darauf hin.

### Geändert

- **Protokoll-Editor:** Akkordeon, Rad-Effekt und die beiden Profileinstellungen dazu sind
  entfernt, ebenso Schnellnavigation, Schnellmenü-Pille und die Hover-Flyouts (ersetzt durch
  Gliederung, Dock und Schublade). Jeder Statuswechsel fragt nach; arbeiten andere mit, nennt
  dieselbe Rückfrage ihre Namen. Tastenkürzel: Strg/⌘+Enter bzw. +Umschalt öffnen den nächsten bzw.
  vorherigen **Block** (nach dem letzten bleibt der Editor dort, früher schloss er das Protokoll),
  Strg/⌘+Alt+N/T/A/S öffnen die Schubladen (Pendenz auch Strg/⌘+Alt+P, weil Strg+Alt+T unter
  Ubuntu das Terminal öffnet), Esc schliesst. Strg+Alt+Buchstabe löst unter Windows jetzt auch
  aus, wenn der Browser dabei AltGr meldet; mit AltGr erzeugte Zeichen (@, [, €) bleiben Text. Pfeil auf/ab wechseln den Punkt nicht
  mehr (sie scrollen wie gewohnt).
- **Protokoll-Editor schneller:** Punkte ausserhalb des Bildes rendert der Browser nicht
  (content-visibility), der aktive Punkt kommt aus einem IntersectionObserver, Tiptap lädt erst im
  aktiven Textblock, Tippen rendert nur den eigenen Block neu, Diagramme laden erst beim Hinscrollen,
  und die Seite zeigt beim Laden sofort ein Gerüst.
- Im Protokoll ausgeblendete Traktanden erscheinen nicht mehr im PDF.
- Die Profileinstellungen «Akkordeon» und «Rad-Effekt» des Protokoll-Editors sind entfallen; ältere
  Clients dürfen sie in 1.6 noch senden, sie werden ignoriert.
- **Protokoll-Editor schneller (Performance-Audit 2026-11-22, Teil 1.6):**
  - Mitschreiben zu zweit: Sperren anderer Personen liegen nicht mehr im Zustand des ganzen Editors.
    Jeder Punkt abonniert nur die Sperren seiner eigenen Felder; ein Fokuswechsel einer anderen
    Person rendert nur noch den betroffenen Punkt neu statt aller Punkte. Sperren, Anzeige «wer
    tippt wo» und Textabgleich bleiben gleich.
  - Kleinere Seite beim Öffnen: die Seite enthält nur noch die Termine, die das Protokoll anzeigen
    kann (verwiesene Termine, Treffer der Terminfilter seiner Blöcke, kommende Termine). Ältere
    Termine für Terminauswahl, Kalender und Tag-Vorschläge lädt der Editor danach im Leerlauf nach.
    Das Personenverzeichnis zur Namensauflösung enthält nur noch verwiesene Personen und keine
    E-Mail-Adressen mehr.
  - Schnellnavigation rechts als eigene, memoisierte Komponente: rendert beim Tippen nicht mehr mit.
  - Akkordeon: der Inhalt ganz zugeklappter Punkte wird nicht mehr gerendert (`content-visibility`),
    ausser bei den direkten Nachbarn des aktiven Punkts (Tab springt wie bisher hinein) und bei
    einem Sprungziel (Autofokus). Scrollraum und Sprungziele bleiben gleich (gemessene Höhe).
  - «Nicht im PDF»: die erste Abfrage läuft im Leerlauf nach dem Laden statt sofort.
  - «Nicht im PDF»: die Abdeckung lädt Protokollinhalte und Termine nur noch einmal statt je einmal
    für den Protokollinhalt und für die Protokoll-Vorlage.
- **Weniger Datenbankabfragen je Anfrage:** Konto, Mandant, Session, zweiter Faktor und gebuchte
  Features kommen in einer Abfrage, Rollen und deren MFA-Pflicht in einer zweiten. Alle Prüfungen
  (aktiv, Login erlaubt, ausgetreten, Widerruf, Session-Register, MFA, RLS-Kontext) laufen weiter bei
  jeder Anfrage, ohne Zwischenspeicher.
- **Protokoll-Editor: Termine, Listen und Pendenzen im neuen Design** (nur Darstellung, keine Migration,
  PDF unverändert). Terminlisten zeigen das Datum als Kalender-Kachel (Monatsband in der Tag-Farbe,
  Tag, Wochentag), den Tag als farbigen Punkt unter dem Titel, eine Zusammenfassung «X kommend ·
  Y vergangen», eine Trennzeile «Ab Sitzung vom …» und – nur wenn vergangene Termine vorhanden
  sind – den Umschalter «Alle/Kommend» (reine Ansicht, Vorlage bleibt). Die Kopfzeile ist immer
  fixiert; Spaltenwahl, «Vergangene ausgrauen», Zeilen in Tag-Farbe und «Abgesagt» bleiben.
  Stammlisten-Tabellen zeigen den Status (offen/neu/geändert/entfernt) als Pille, haben ein
  Suchfeld und lassen sich per Spaltenkopf sortieren (auf, ab, zurück zur Vorlagen-Reihenfolge –
  nicht gespeichert). Pendenzen: erledigte durchgestrichen an ihrer Stelle, Fälligkeit farbig
  (rot überfällig, gelb innerhalb von 14 Tagen wie in der Pendenzen-Übersicht), Fortschritt in %,
  Zähler an den Tag-Filtern und Initialen bei den Zuständigen. Pendenzen erscheinen als Tabelle
  (Erledigt | Aufgabe | Verantwortlich | Fällig) mit «X offen · Y erledigt», Fälligkeit als
  «Überfällig · TT.MM.», «Heute» bzw. «In N Tagen»; Stammlisten zeigen «N Einträge · M brauchen
  Aufmerksamkeit», Avatare in fünf Tönen und Zahlen rechtsbündig.
- **Protokoll-Editor: neuer Kopf mit Workflow-Leiste.** Oben Zurück-Symbol, Titel und Meta-Zeile
  (Protokollnummer · Erstellt · Vorlage vN), Suchfeld-Knopf mit Tastenkürzel, Export-Menü («PDF
  öffnen», «Exportieren …») und «⋯» («Original-Dokument öffnen», «Hilfe zum Ablauf»). Darunter die
  vier Schritte (Geplant · Vorbereitung, Sitzung, Nachbearbeitung, Abgeschlossen; nur Anzeige),
  der Hinweis «Vorlage wurde geändert» mit «Neu laden», der Schalter «Nachverfolgen» (statt
  An/Aus-Menü) und der Hauptknopf. Abläufe, Bedingungen und Rückfragen beim Statuswechsel sind
  unverändert.
- **pypdf 7.1.1** (vorher 6.21.4) für die XMP-Ergänzung der Dokument-Engine. Keine Code-Änderung nötig
  (`PdfWriter(..., incremental=True)` unverändert). Neu erzeugt pypdf die zweite Datei-ID im Trailer
  zufällig statt als MD5 über den Inhalt; jeder Export hat ohnehin eine eigene Dokument-ID, der
  SHA-256 im Register gilt weiterhin für genau die ausgelieferten Bytes.
- **jsdom 31.0.1** (vorher 30.1.3) als Testumgebung für Vitest im Frontend. Die neue CSS-Engine
  serialisiert Inline-Prozentwerte wie Browser auf sechs signifikante Stellen; ein Speicherbalken-Test
  vergleicht deshalb numerisch.
- **Playwright 1.65.1** (vorher 1.64.1) für die E2E-Tests; das Docker-Image der E2E-Läufe
  (`mcr.microsoft.com/playwright:v1.65.1-noble`) ist jetzt per Digest gepinnt. Der Spec `security-devices`
  wartete nach «Gerät abmelden» nur auf den Toast und zählte die Abmelde-Knöpfe, bevor die Liste neu geladen
  war; mit 1.65 traf er dieses Fenster reproduzierbar. Er wartet jetzt, bis die abgemeldete Zeile weg ist.
- **Redis 8.10** (vorher 7.4, `redis:8-alpine` per Digest) in allen Compose-Dateien (Dev, Release, Tests)
  und den CI-Diensten. Konfiguration (`requirepass` aus dem Secret, `maxmemory` + `noeviction`), ACL des
  Standardbenutzers und RDB-Snapshots unverändert; redis-py 8.1 (Lua-Skripte der Rate-Limits und
  Kollaborations-Sperren, Pub/Sub) läuft unverändert. Das Image lädt zusätzlich die mitgelieferten Module
  (Search, JSON, TimeSeries, Bloom, Vector Sets), hocX nutzt sie nicht. Lizenz ab Redis 8: AGPLv3/RSALv2/SSPLv1
  (wahlweise); hocX betreibt das unveränderte Image nur intern.
  **Rollback auf einen Deploy-Code mit Redis 7 nur mit geleertem Redis-Volume** (Redis 7 liest das RDB-Format 15
  nicht): Login-Tickets, MFA-Flows, Rate-Limit-/Sperrzähler, temporäre Anmeldesperren und Kollaborations-Sperren
  gehen dabei verloren; Sessions und Job-Warteschlange liegen in PostgreSQL und bleiben (RUNBOOK Abschnitt 5). Der automatische App-Rollback von `deploy.sh` ist nicht betroffen.
- **Python 3.15** (3.15.2, vorher 3.13; Dokumentation vorher 3.12) für alle Python-Images: Backend inkl.
  Worker-Dienste, Abgabebox-Backend, Foto-Analyse-Worker, Dokumentationsseite (`python:3.15-slim` per Digest),
  CI (`setup-python`) entsprechend. PyYAML 6.0.4 (vorher 6.0.3, ohne Wheel für 3.15).
  **Ausnahme Backend** (inkl. storage-init, storage-, backup-, document- und job-worker aus demselben Image):
  **Python 3.14** (`python:3.14-slim` per Digest), ebenso die CI-Jobs, die `backend/requirements.txt`
  installieren. `google-re2` (Regel-Engine des Datei-Imports) hat noch kein Wheel für 3.15, und das
  schlanke Image hat keinen C++-Compiler; Wechsel auf 3.15, sobald ein cp315-Wheel erscheint.

### Behoben

- Zyklus löschen: der Löschdialog nennt vorher, was mitgelöscht wird (gespeicherte Tabellenstände,
  Zuordnungen von Aufgabenpaketen, Zyklus-Alben; die Fotos bleiben in der Galerie).
- Protokolle: Blockkonfigurationen in falscher Form (z. B. Anwesenheit als Zahl, Zahlen über dem
  Datenbankbereich) werden beim Speichern mit 400 abgelehnt, statt das Protokoll dauerhaft unladbar
  zu machen; NUL-Zeichen in Bildtitel, Legende und Dateinamen beim Protokollbild-Upload ergeben
  einen Eingabefehler statt eines Serverfehlers. Ein sehr langer Protokolltitel verhindert die
  PDF-Ablage nicht mehr (Dateiname gekürzt, der volle Titel bleibt im PDF).
- Protokoll-Editor: das Buchungsformular richtet sich nach «Finanzen verwalten», die
  Anwesenheitsbussen nach «Bussen verwalten» (vorher beide nach dem Bussenrecht).
- Dateien und Fotos: NUL-Zeichen in Tags und Dateinamen des Upload-Formulars und zu grosse
  Grössenangaben im Upload-Verlauf ergeben Eingabefehler statt 500; eine beschädigte Galerie-ZIP
  landet nicht mehr als Systemfehler im Fehlerprotokoll; abgebrochene Downloads hinterlassen keine
  Kopien mehr (Aufräumen nach 24 h).
- Öffentliche Links und Partner-Downloads: abgeschnittene JPEG- und PNG-Fotos werden ohne die
  ausgeschlossenen Metadaten ausgeliefert statt mit 500 abzubrechen; ein Bild, das sich gar nicht
  filtern lässt (z. B. beschädigtes HEIC), wird nie ungefiltert ausgeliefert (422) und fehlt im
  «Alle herunterladen»-ZIP, statt den ganzen Download abzubrechen.
- Zwei gleichzeitige Album-Einladungen an denselben Verein ergeben die normale Meldung statt 500.
- Mandant aufräumen: «Hochgeladene Dokumente» trifft keine Galeriefotos, Pendenz-Anhänge und
  archivierten Exporte mehr.

### Sicherheit

- Kassenbuch: Namen gebüsster Personen in Buchungstexten und Sperrhinweisen nur mit «Persönliche
  Auswertungen» (Kasse, Administration); sonst «Busse …: ·····» - in der Ansicht, in PDFs und
  Tabellen-Exporten, ohne Datenänderung.
- Metadatenfilter für öffentliche Links und Partner: PNG und WebP behalten nur Bilddaten,
  Farbprofil und Darstellung; C2PA-/JUMBF-Manifeste und unbekannte Chunks fallen weg.
- Kalender-Abo endet bei Austritt und entzogenem Login (auch bei einem Austrittsdatum in der Zukunft).
- Termin bzw. Listeneintrag mit Abgabe-Einreichungen nur mit «Abgaben verwalten» löschbar (die
  Einreichungen fallen mit weg).
- Nach einem Abo-Downgrade entstehen aus Termin- und Listenänderungen keine neuen Paket- und
  Abgabe-Pendenzen mehr.
- Plattform-Admin: die Identitätsprüfung zeigt die E-Mail der Antragsteller nur owner-Admins.
- Datenschutz: die Löschung eines Vereins entfernt auch fertige Vereinsexporte; «Mandant aufräumen»
  löscht Personen wie der reguläre Löschpfad (Audit-Log, Anmeldeereignisse, Löschjournal) und
  schreibt auch Protokolle, Termine, Abgaben und Dateien ins Löschjournal, löscht die Dateien der
  Einreichungen von Terminen und Listeneinträgen vollständig; ein abgelaufener Vereinsexport ist
  sofort nicht mehr herunterladbar, und ein während der Vereinslöschung fertig gewordener Export
  hinterlässt kein Archiv.
- Protokoll-PDF: Bussen- und Finanzblöcke zeigen ohne «Persönliche Auswertungen» nur die eigenen
  Bussen bzw. ohne Finanzrecht keinen Kontostand; das gemeinsame PDF (alle Bussen, Kontostand) und
  PDFs anderer Personen sind nur in der eigenen Sicht abrufbar (Liste, Download, Exportliste und
  Dateien-Tab samt Vorschau und extrahiertem Text); persönliche PDFs werden nicht mehr als Version
  des Protokoll-Dokuments übernommen.
- Metadatenfilter: ein JPEG-Kommentar übersteht die Neukodierung nicht mehr.
- Buchungen lassen sich nur mit einem lesbaren Protokoll verknüpfen.

### Update

- Abhängigkeiten: next 16.4.6 (beide Frontends), neuer Digest des ClamAV-Images.
- Migration `0230_cloud_import` (Tabellen `import_job`, `import_item` mit RLS, Berechtigung
  `files.import`, Funktion `hocx_analyze_upload_tables()` für ANALYZE nach grossen Importen). Die Revision folgt auf `0219_password_breach_check` (letzte 1.5.2-Migration).
- Neue Einstellungen (kein Secret, optional): `CLOUD_IMPORT_MAX_JOB_FILES` (50000),
  `CLOUD_IMPORT_MAX_JOB_BYTES` (100 GiB) für backend und job-worker.
- Neue Abhängigkeit `google-re2==1.1.20251105` (BSD-3) im Backend.
- Upload-Verlauf: Migrationen `0250_upload_history`, `0251_capture_change_batches`,
  `0252_upload_history_abgabebox` (Kette `0219` → `0230` → `0250`–`0254` → `0260` → `0270` → `0280`). Neue Tabellen mit RLS, Spalten `stored_file.upload_job_id`/`camera_serial_key`, Trigger
  mit SECURITY DEFINER (Aufräumen nach endgültigem Löschen, Erfassung der Abgabebox ohne neue Rechte
  für `hocx_abgabebox`). Kein neues Secret.
- **Nach dem Update einmal ausführen:** `python -m app.workers.upload_history_backfill` im
  backend-Container (rekonstruiert den Altbestand, idempotent, siehe RUNBOOK Abschnitt 25).
- Foto-Standorte: Migration `0260_photo_places` (globale Ortsdaten `geo_place`/`geo_dataset`, für
  `hocx_app` nur lesbar, Import über die Zwischenablage `geo_place_import` und
  `hocx_geo_import_apply`; Mandantentabellen `photo_location`, `place_change_batch`,
  `place_change_item` mit RLS; Trigger auf `stored_file` und `photo_location`; Suchdokument mit
  Ortsnamen). Keine neue Extension (kein PostGIS). Neue Jobs im job-worker: `geo_places_update`
  (lädt beim ersten Lauf ~70 MB aus `download.geonames.org` und `data.geo.admin.ch`, danach nur
  bei neuer Ausgabe; ~0,85 Mio. Orte, rund 300 MB in Postgres inkl. Indizes) und `photo_places_resolve` (trägt
  Ortsnamen des Altbestands in Stücken nach). **Neues Secret `GEO_DB_PASSWORD` mit
  `GEO_DATABASE_URL`** für die eigene DB-Rolle `hocx_geo` (nur Import der Ortsdaten: Zwischenablage
  und Übernahme; `hocx_app` liest die Ortsdaten nur, `hocx_geo` sieht keine Mandantendaten).
  `scripts/deploy.sh` ergänzt es bei bestehenden Installationen automatisch (RUNBOOK Abschnitt 26);
  ohne Passwort bricht die Migration ab, der job-worker startet in der Produktion nicht ohne
  `GEO_DATABASE_URL`. Optionale Einstellungen `GEO_PLACES_AUTO_UPDATE`
  (true), `GEO_PLACES_COUNTRIES` (CH,LI,AT,DE,FR,IT), `GEO_PLACES_MAX_AGE_DAYS` (30). Ohne Netz:
  `python -m scripts.import_geo_places` mit lokalen Dateien.

## [1.5.2] - 2026-11-23

Korrekturversion zu 1.5.1 mit allen Funden der Nachtläufe vom 22. und 23.11.2026: mehrere
Sicherheitskorrekturen bei Konto- und Rechteverwaltung, Anmeldung, Freigabelinks und Dateilöschung,
dazu Korrekturen bei gleichzeitigen Änderungen im Document Studio, bei Pendenzen und Bussen, beim
Benutzerlimit, bei ausgetretenen Mitgliedern und im Fehlerprotokoll der Abgabebox sowie die
überarbeitete Seitenleiste der Plattform-Konsole («hocX Konsole»). Neu prüft hocX bestehende
Passwörter bei jeder Anmeldung gegen bekannte Datenlecks. Eine Migration (0219), keine neuen
Secrets, zwei optionale Umgebungsvariablen, keine Breaking Changes.

### Update

- Von **1.5.1**: `./scripts/deploy.sh <test|prod>` wie gewohnt. Migration **0219** (drei leere
  Zeitstempel-Spalten auf `app_user` und `platform_admin`, schnell). Optional
  `PASSWORD_BREACH_RECHECK_DAYS` (Standard 30) und `PASSWORD_LEAK_FETCH_PER_MINUTE` (Standard 600).
- **Leak-Prüfung beim Login:** Nach dem Update wird jedes Passwort bei der nächsten Anmeldung
  geprüft. Konten mit geleaktem Passwort brauchen ab dann den zweiten Faktor bzw. einen E-Mail-Code
  und bekommen einmal eine Warn-Mail; ohne Mailversand und ohne zweiten Faktor ist die Anmeldung
  solcher Konten nicht möglich (Passwort über «Passwort vergessen» bzw. die Verwaltung neu setzen).
  Plattform-Admins mit geleaktem Passwort und ohne Passkey werden abgewiesen (neues Passwort über
  eine andere Owner-Person oder `admin_cli`). Neuer Job `password_breach_recheck` (täglich).
- **Abgabebox-Fehlerprotokoll:** Unerwartete Fehler der Abgabebox erscheinen ab jetzt unter
  `/admin` im Fehlerprotokoll (bisher kam dort nie ein Eintrag an). Nach dem Update können also
  erstmals Einträge mit Quelle «abgabebox-backend» auftauchen.
- **Ausgetretene Mitglieder:** Wer ein Austrittsdatum in der Vergangenheit bekommt, wird wie bei
  einer Deaktivierung abgemeldet; offene Einladungs- und Zurücksetzungslinks verfallen.
- **Einmalige Empfehlung:** öffentliche Datei-Freigabelinks unter Mandant-Einstellungen ›
  Zugangslinks sichten und Links auf Bilder oder Exporte aus noch nicht abgeschlossenen Protokollen
  widerrufen, falls solche angelegt wurden. Dasselbe für Album-Links auf Alben mit Bildern aus
  Protokollentwürfen (die neue Prüfung greift beim Erstellen, bestehende Links bleiben).

### Sicherheit

- **Leak-Prüfung bestehender Passwörter:** bei jeder erfolgreichen Passwort-Anmeldung (Konten und
  Plattform-Admins) mit der bestehenden Prüfung (HIBP, k-Anonymität: nur 5 Hex-Zeichen des SHA-1,
  Antwort je Präfix eine Stunde im Cache, Rückfall lokale Liste, höchstens 600 Abfragen je Minute).
  Ausfall blockiert die Anmeldung nie. Geleakt: Konto markiert (Audit-Eintrag), Anmeldung nur mit
  zweitem Faktor oder E-Mail-Code, einmalige Warn-Mail in allen Sprachen, roter Pflichthinweis in
  der App «Passwort ändern»; ein neues Passwort hebt die Markierung auf. Der Nachtjob merkt Konten
  vor, deren Prüfung älter als 30 Tage ist (nächste Anmeldung ohne Cache). Gespeichert werden nur
  Zeitpunkte, nie Hash, SHA-1 oder Präfix.
- Die Login-E-Mail eines Kontos (auch des eigenen) lässt sich nur noch nach einer frischen
  Bestätigung der Identität ändern, wie Passwort, Login und Rollen.
- Austrittsdatum bei Konten mit Login: setzen oder entfernen braucht dieselben Rechte wie
  Deaktivieren (Benutzerverwaltung, keine Höherberechtigten); ausgetretene oder austretende
  Administratoren zählen nicht mehr für die Regel «letzter Administrator», auch nicht über die
  Personenseite oder den Word-Import.
- Öffentliche Freigabelinks auf Dateien entstehen und erscheinen nur noch für Dateien, die das
  eigene Konto selbst öffnen darf; der Ersteller kann seinen Link widerrufen, auch wenn er die
  Datei inzwischen nicht mehr öffnen darf (die Trennung Fotos/Dokumente gilt weiter).
- Live-Photo-Clips folgen dem Recht «Fotos lesen» wie das zugehörige Foto.
- Offene Protokoll-Tabs halten eine Sitzung nicht mehr über die Inaktivitätsgrenze hinaus am Leben.
- Vorgänge zum zweiten Faktor (Passkey/Authenticator einrichten, Passkey-Anmeldung, Bestätigung)
  sind je Konto bzw. je Anmeldung begrenzt.
- Ratelimits nach IP zählen IPv6-Adressen überall je /64 (Anmeldung, Zugangslinks, Logos,
  Freigabelinks, Kalender-Abo, Abgabe-Zugang).
- Fehlerhafte Passkey-Antworten führen zu einer normalen Ablehnung statt zu einem Serverfehler.
- Gelöschte Fotos bleiben auch bei gleichzeitiger Bearbeitung des Aufnahmedatums nicht im
  Speicher zurück (auch beim Löschen oder Aufräumen eines Vereins).
- Organisations-Bestätigung: eine gleichzeitige oder zwischenzeitliche Umbenennung kann nicht mehr
  als bestätigt gelten.
- Bussen zu Protokollen folgen denselben Leserechten wie das Protokoll selbst (Entwürfe nur mit
  dem Recht, Entwürfe zu lesen), auch in der Bussenliste und der Summe offener Bussen; nicht
  lesbare Protokolle verhalten sich wie unbekannte.
- Ein als geleakt markiertes Passwort bestätigt in einer Sitzung von vor der Markierung weder eine
  Identitätsbestätigung noch einen Passwortwechsel; dafür neu anmelden oder «Passwort vergessen».
- Wiedereintritt nach einem Austritt beendet alte Sitzungen und Einmal-Links; eine Mehrfacheinladung
  mit Rolle verlangt die Bestätigung der Identität vor der ersten Änderung; die
  Organisations-Bestätigung verlangt den geprüften Namen.
- Bilder aus Protokollentwürfen: Dateiübersicht, Fotos, Zeitleiste, Zahlen, Tag-Vorschläge, Suche
  und Ähnlichkeitsgruppen zeigen Protokollbilder und -exporte nur noch, wenn das Konto das Protokoll
  lesen darf (bisher erschienen Name, Protokollnummer und Blocktitel von Entwürfen). Ein in einen
  neuen Entwurf übernommenes Bild erscheint nur mit dem Kontext des lesbaren Protokolls.
- Übernommene Protokollbilder: die Leseprüfung berücksichtigt jetzt alle Protokolle, in denen das
  Bild steckt (lesbar, sobald eines lesbar ist), statt zufällig eines davon.
- Öffentliche Album-Links: nur noch, wenn das eigene Konto jedes Foto des Albums öffnen darf
  (keine Entwurfsbilder ohne Leserecht, keine Abgabe-Fotos ausserhalb der Reichweite «nur
  zugewiesene»); Abgabe-Alben nicht lesbarer Aufträge lassen sich nicht mehr über die ID teilen.

### Geändert

- **Plattform-Admin heisst jetzt «hocX Konsole»** (en «hocX Console», fr/it «Console hocX»): Titel in der
  Seitenleiste, Browser-Tab aller /admin-Seiten und Login der Konsole. Kontobezeichnungen wie
  «Plattform-Admins» (Rollen, Audit-Akteur) bleiben.
- **Seitenleiste der Konsole mit den Massen der App:** gleicher Innenabstand, Logo, Gruppen- und
  Eintragsabstände, Eintragshöhe 40 px und Bereichsköpfe 32 px wie die Hauptnavigation der Vereins-App
  (die dichteren Sonderwerte aus 1.5.1 entfallen). Grosse Bereiche scrollen jetzt innerhalb der
  Navigation, der aktive Eintrag wird dabei sichtbar gehalten; Zähler im aktiven Eintrag mit
  ausreichendem Kontrast. Kompaktmodus und Mobilmenü unverändert bedienbar.
- **Eigenes Favicon für die Konsole:** dasselbe hX-Zeichen, hell auf dunklem Grund
  (`public/icons/console`: `favicon.ico`, `icon.svg`, `apple-touch-icon.png`), damit App und Konsole
  im Tab unterscheidbar sind. `/favicon.ico` auf der Admin-Domain liefert ebenfalls das Konsolen-Icon
  (`proxy.ts`). Das App-Favicon liegt dafür neu unter `public/favicon.ico` (statt `app/favicon.ico`,
  gleiche Datei, Link über die Metadaten), Manifest und App-Icons bleiben unverändert.

### Behoben

- **Document Studio:** Vorlage löschen während eines laufenden Exports, gleichzeitig gesetzte erste
  Standardvorlage (Fehler 500), Asset bzw. Brand-Profil löschen während gleichzeitiger Verwendung
  und Archivieren gleichzeitig mit einer Standardzuweisung verhalten sich jetzt korrekt.
- **Protokoll nach schnellem Neuladen nicht mehr veraltet:** Sitzungsnotizen und Textblöcke
  behalten einen lokalen Entwurf, der neuer ist als der Serverstand (bei Abweichung Hinweis mit
  «Meinen Entwurf übernehmen»); schon gespeicherte Entwürfe werden beim Öffnen aufgeräumt, und kein
  Entwurf wird ohne Speicherung verworfen.
- **Fett/Kursiv mit Satzzeichen am Rand** (z. B. «**B!**» direkt vor einem Buchstaben) übersteht
  das Speichern als Markdown; vorher wanderten die Begrenzer nach innen oder gingen verloren.
- **Pendenzen und Aufgabenpakete:** `null` für Aufgabe, Tags, Name oder «aktiv» sowie zu grosse
  Sortierwerte werden als ungültige Eingabe abgelehnt (vorher u. a. dauerhaft unlesbare Pendenz bei
  `tags: null`); Paketnamen werden getrimmt. Unbekannte oder zu grosse Status-IDs ergeben eine
  Validierungsmeldung statt eines Eintrags im Fehlerprotokoll.
- **Anwesenheitsbussen:** Beträge werden wie in der Datenbank auf Rappen gerundet und begrenzt
  (zu grosse oder auf 0 gerundete Beträge ergaben einen Fehler).
- **Benutzerlimit:** offene Einladungen ausgetretener Personen belegen keinen Platz mehr; ein
  Wiedereintritt (Austrittsdatum entfernt oder verschoben) prüft das Limit; «Abo & Nutzung» zieht
  offene Einladungen von den freien Plätzen ab.
- **MFA-Frist:** Wer seinen letzten Faktor ohne Pflicht entfernt und später wieder unter die
  Pflicht fällt, bekommt erneut die Frist von drei Tagen.
- **Mehrfacheinladung mit Rolle:** Die Rolle ändert sich nur noch, wenn die Einladung auch
  verschickt wird; eine nötige Bestätigung der Identität wird abgefragt statt alle Personen zu
  überspringen.
- **Ausgetretene Mitglieder** zählen in Mitgliederlisten/Präsenzlisten des Document Studio und in
  der Statistik nicht mehr als aktiv; die Mitgliederliste und Personenseite rechnen «heute» in
  Schweizer Zeit (zwischen Mitternacht und 01:00/02:00 erschienen gestern Ausgetretene als aktiv).
- **Vereins-Domain:** Passwort ändern, Faktor hinzufügen/entfernen und «Andere Geräte abmelden»
  melden auf einer eigenen Vereins-Domain nicht mehr ab.
- **Bestätigung der Identität:** Ist keine Methode nutzbar (nur Passkey auf einer Vereins-Domain),
  zeigt der Dialog einen Hinweis statt endlos zu laden.
- **Abgabebox:** Das Fehlerprotokoll schreibt wieder (fehlendes Leserecht beim Eintragen),
  `%00` im Abgabe-Link ergibt «nicht gefunden» statt eines Serverfehlers, NUL-Zeichen verhindern
  keine Protokolleinträge mehr, und eine Ablehnung wegen vollem Vereinskontingent steht im
  Upload-Protokoll.

## [1.5.1] - 2026-11-22

Folgeversion zu 1.5.0. Schwerpunkte: Rest des Plattform-Admin-Umbaus (Reset-Link statt Passwort,
Warnungen quittieren, Exporte, Admin-Tabellen), Erkennung eines gestörten Maildienstes, Ablehnung
geleakter Passwörter und Risikosignal «neues Land», eine einheitliche Update-/Wartungsseite, die neue
Foto-Ansicht, Keywords und Synonyme in der Suche, Listen in der globalen Suche, Dateiablage per
Drag-and-Drop in Pendenzen und Kundenlogos auf der Website, dazu ein schnellerer Protokoll-Editor,
Korrekturen aus dem Nachtlauf (Abgabebox, Dateien, Mitglieder) und eine schnelle Fotosuche auch in
grossen Mandanten. Update direkt von 1.5.0 mit
`./scripts/deploy.sh <test|prod>`; sieben Migrationen (0209–0218).

### Update

**Kurz für Betreiber (Update von 1.5.0):**

- `./scripts/deploy.sh <test|prod>` wie gewohnt. Neue Migrationen (lineare Kette ab `0208_platform_metrics`):
  `0209_admin_alert_ack`, `0210_email_delivery_status`, `0212_maintenance_public_update`,
  `0214_template_content_version`, `0215_auth_geo_country`, `0217_file_keywords_synonyms`,
  `0218_album_item_auto_source` (Details unten).
- **Neue Einstellungen (kein Secret):** `PASSWORD_LEAK_CHECK` (`on`/`local-only`/`off`, Standard `on`),
  `PASSWORD_LEAK_MIN_COUNT`, `GEOIP_AUTO_UPDATE` (Standard an) und optional `HOCX_STATUS_PAGE_URL`
  (https, Link auf der Update-Seite, wenn ein Update länger als 15 Minuten dauert).
- **Ausgehende Verbindungen:** das Backend braucht HTTPS zu `api.pwnedpasswords.com` (Leak-Prüfung neuer
  Passwörter), der job-worker HTTPS zu `download.db-ip.com` (Länder-Datenbank) **und zu `db-ip.com`**
  (Download-Seite mit den Prüfsummen). Ohne Zugang zur Seite übernimmt der Job `geoip_update` keine neue
  Länder-Datenbank (die vorhandene bleibt, der Job meldet einen Fehler). Ohne Internet:
  `PASSWORD_LEAK_CHECK=local-only` (lokale Liste im Image) und `GEOIP_AUTO_UPDATE=false` (RUNBOOK Abschnitt 23).
- **Neues Volume `geoip_data`** (job-worker schreibt, Backend liest); der Job `geoip_update` lädt die
  Datenbank beim ersten Tick. Fehlt sie, entfällt nur das Signal «neues Land» (Systemstatus «nicht eingerichtet»).
- **Vereinslogos:** Altlogos ohne Raster-Endung (z. B. SVG oder ohne Dateiendung) werden nicht mehr
  ausgeliefert (404) und müssen in den Mandant-Einstellungen neu hochgeladen werden (PNG/JPEG/GIF/WebP).
- **Risikosignal «neues Land» (+10 Punkte):** zusammen mit neuem Gerät und neuem Netz erreicht eine
  Anmeldung damit die Stufe, ab der Konten ohne zweiten Faktor einen Bestätigungscode per Mail bekommen.
  Nutzer im Ausland bekommen auf neuen Geräten deshalb eher einen Mailcode.
- **Plattform-Admins setzen keine Passwörter mehr für Benutzer:** die Benutzerverwaltung verschickt einen
  Zurücksetzungslink bzw. eine Einladung (funktionierender E-Mail-Versand nötig; Notweg über
  `python -m app.admin_cli`, RUNBOOK Abschnitt 22).
- **Erster Deploy auf 1.5.1 zeigt noch die alte Wartungsseite:** die neue, einheitliche Update-Seite
  liefert erst das neue Release aus; ab dem nächsten Update erscheint sie in beiden Wegen.
- **E-Mail-Versand prüfen:** ist der Versand gestört, werden Anmeldungen, die einen Mailcode brauchen,
  sofort mit «Anmeldung aktuell nicht möglich» abgewiesen; der Systemstatus zeigt die neue Prüfung
  «E-Mail-Versand» (ntfy-Alarm `email:smtp:<grund>`).
- Neue Abhängigkeit `maxminddb==3.2.0` (Apache-2.0); neuer Hintergrundjob `geoip_update` (Lock-ID 202600045).
- Traefik 3.7.19 (Patch), Python-Pakete mit Patch-/Minor-Updates (u. a. FastAPI 0.162.2, Pydantic 2.14.3,
  pypdfium2 5.15 mit PDFium-Sicherheitskorrekturen), pdfjs-dist 6.5 in der Abgabebox; Playwright bleibt 1.64.1.

**Migrationen im Detail:**

- `0209_admin_alert_ack`: quittierte Sicherheitswarnungen (Plattform-Admin).
- `0210_email_delivery_status`: Spalten für Fehler in Folge, Fehlerklasse und «gestört seit» in
  `platform_notification_settings` (Plattform-Einstellung, keine Mandantendaten).
- `0212_maintenance_public_update`: öffentlicher Wartungsstatus mit `kind` (`update`/`maintenance`),
  `from_version`, `to_version` (Funktion für die Abgabebox).
- `0214_template_content_version`: Vorlagenversion zählt inhaltliche Änderungen per Trigger hoch.
- `0215_auth_geo_country`: drei nullable Spalten mit Ländercode (`auth_event.src_country`,
  `auth_session.country`, `auth_known_device.last_country`), nie die IP.
- `0217_file_keywords_synonyms`: Spalte `stored_file.keywords` (leer, kein Backfill), Tabelle
  `search_synonym_group` (`tenant_id`, RLS); Suchdokument und Trigger der Fotosuche nehmen Keywords auf.
- `0218_album_item_auto_source`: `photo_album_item.auto_source` markiert Einträge, die nur wegen des
  Aufnahmedatums in einem Zyklus-Perioden-Album stehen (Bestand bleibt unmarkiert).

### Sicherheit

- **Geleakte Passwörter werden abgelehnt (SEC-AUTH-015):** alle Setzpfade (Einladung, Passwort
  vergessen, Profil, Verwaltung, Plattform-Admin-Konten) prüfen nach der Stärkeregel gegen die
  Pwned-Passwords-Range-API (k-Anonymität: nur 5 Hex-Zeichen des SHA-1, mit Padding), Rückfall auf
  eine lokale Liste (SecLists, MIT). Eigene Meldung «Dieses Passwort ist aus einem Datenleck bekannt»
  in allen Sprachen. Plattform-Admin-Konten bekommen dabei dieselbe Stärkeregel wie Konten.
- **Risikosignal «neues Land»:** Land der Anmeldung lokal aus DB-IP «IP to Country Lite» (CC BY 4.0);
  Land in 90 Tagen erfolgreicher Anmeldungen nie gesehen → 10 Punkte, allein nie entscheidend, ohne
  Baseline kein Signal. Gespeichert wird nur der Ländercode, nie die IP.
- **GeoIP-Datenbank nur mit passender Prüfsumme (N-1):** `geoip_update` vergleicht die entpackte MMDB-Datei
  mit dem SHA1, den DB-IP auf der offiziellen Download-Seite (`db-ip.com`) veröffentlicht (eine Signatur
  bietet DB-IP nicht an). Weicht er ab oder fehlt er, wird die Datei nicht übernommen.
- **Vereinslogo-Route `/api/tenants/{id}/profile-image` nicht mehr für alle öffentlich:** ohne Anmeldung
  nur, wo hocX das Logo ohnehin öffentlich zeigt (eigene App-Domain, Prüfseite mit Vereinsidentität),
  angemeldet nur eigener Mandant und vertraute Partner; sonst einheitlich 404. Rate-Limit, Cache nur
  für öffentliche Logos.
- **Duplikat-Orakel geschlossen:** Vorab-Abgleich, Dokument-, Protokollbild-, Word-Import-, Galerie-
  und Abgabe-Link-Uploads melden nur Duplikate, die die Person sehen darf; unsichtbare werden eigene
  Kopien ohne fremde ID. Metadaten werden nur bei verwaltbaren Dateien ergänzt.
- Sicherheitshinweis-Mails «lassen sich nicht abschalten» (Text wie im Design und in en/fr/it).

### Geändert

- **Plattform-Admins setzen keine Passwörter mehr:** statt eines Passworts verschickt die Benutzerverwaltung
  einen Zurücksetzungslink (Konto mit Login) bzw. eine Einladung (Konto ohne Login), mit eigener
  Passkey-Bestätigung (`user-credentials`), höchstens 5 Links pro Stunde und Konto, auditiert. Neue Konten
  entstehen ohne Passwort, optional mit Einladung.
- **Passkey-Bestätigung je Zweck:** neue Zwecke `user-credentials`, `tenant-import` (Mandant-Import,
  nur an Methode und Pfad gebunden), `security-block` (Sperren statt bisher `platform-settings`),
  `security-export`, `security-resolve`. Einstellungen › Sicherheit & Anmeldung listet alle Aktionen mit
  Bestätigung (aus dem Code abgeleitet).
- **Admin-Tabellen:** gemeinsamer Hook `useServerTable` (Filter/Seite/Sortierung in der URL, nur IDs und
  Codes), Spaltenwahl je Admin, Mandanten-Auswahl per Remote-Suche statt kompletter Mandantenliste
  (Audit-Log, Fehlerprotokoll, Uploads, Benutzer).
- **Audit-Log:** Filter Zeitraum, Akteur (Art, Plattform-Admin) und Entität, Details als Schlüssel-Wert-Liste.
- **Plattform-Admins:** Liste mit Anzahl Passkeys und letzter Anmeldung.
- **Gleiche Meldung während eines Updates:** Bisher wechselte die Anzeige beim Deploy zwischen der
  In-App-Wartungsseite («hocX wird gerade gewartet», Deploy-Fenster) und der statischen
  Traefik-Seite («hocX wird gerade aktualisiert», Neustart der Container). Jetzt zeigen beide Wege
  während eines Updates dieselbe Update-Meldung im neuen Design: «hocX wird aktualisiert», alte →
  neue Version, «Jetzt neu laden» (prüft sofort), automatisches Neuladen und nach 15 Minuten «Das
  Update dauert länger». Anmeldeseite und Abgabebox-Banner ziehen mit. Geplante oder manuelle
  Wartung zeigt die neue Wartungsseite mit voraussichtlichem Ende, Spanne, Fortschrittsbalken und
  Countdown bis zur nächsten Prüfung (RUNBOOK Abschnitt 20).
- Öffentlicher Wartungsstatus: neue Felder `kind` (`update`/`maintenance`), `from_version`,
  `to_version`.
- **Foto-Ansicht im neuen Design:** Kopfzeile mit Badges (LIVE, Best-of, Datum geschätzt/korrigiert),
  Teilen-Popover (Freigabelink nur für dieses Foto), Löschen-Popover (Papierkorb mit Rückgängig),
  Filmstreifen, Vergleichsmodus für Duplikat-/Ähnlich-Gruppen, Seitenleiste mit Aufnahmedatum
  (Setzen/Verschieben mit Vorschau/Zurücksetzen), Alben, Tags, Keywords, Analyse und Details;
  Tastenkürzel B (Best-of) und Entf (Löschen).
- **Aufnahmedatum verschieben ohne Uhrzeit:** Fotos ohne Uhrzeit (geschätztes Datum, Korrektur ohne
  Uhrzeit) werden nur um die ganzen Tage des Versatzes verschoben (−13 h → unverändert, −30 h → −1 Tag);
  Vorschau, Bestätigung und Ergebnis nennen sie («unverändert – keine Uhrzeit»).
- **Auto-Alben ziehen Datumskorrekturen nach:** Fotos, die nur wegen ihres Aufnahmedatums in einem
  Zyklus-Perioden-Album stehen, wandern bei Korrektur, Verschieben, Zurücksetzen oder Schätzdatum in die
  passende Periode; manuelle Zuordnungen, Abgabe- und Termin-Alben bleiben unberührt.
- **Protokolle:** Reihenfolge der Terminfelder «aus Termin/Pendenz» kommt in geplanten und vorbereiteten
  Protokollen sofort an; die Vorlagenversion zählt Änderungen, geplante Protokolle mit älterem Stand
  zeigen «Vorlage wurde geändert» mit «Aus Vorlage neu laden».
- **Vorlagen:** Einfügelinie beim Ziehen von Terminfeldern und Tabellenzeilen.
- **Pendenzen:** Escape in der Dateisuche schliesst nur die Trefferliste, nicht den Dialog.
- Ablage: mit Suchtext stehen die besten Treffer zuerst (Sortierung «Beste Treffer», auch mobil).
- **Protokoll-Editor schneller (Performance-Quick-Wins):** Das Akkordeon berechnet beim Scrollen nicht
  mehr den Stil des ganzen Dokuments neu (Akkordeon-Variablen per `@property` nicht vererbt, Neumessen
  nur des geänderten Punkts) - gemessen auf einem Protokoll mit 32 Punkten: Style-Neuberechnung
  3,5 s → 0,5 s, Frames über 16,7 ms 21 % → 8 %, keine Long Tasks mehr (vorher 24). Das Bilderraster
  lädt Vorschaubilder statt der Originale (Vollbild weiterhin Original), Diagramme (Recharts) und die
  Bild-Analyse werden erst bei Bedarf geladen (Start-JS der Protokollseite 638 → 517 KB gzip), die
  Statistik lädt beim Öffnen einmal statt zweimal, und Anliegen, Bussen und Leseposition kommen mit
  der Seite statt erst nach dem Laden. Beim Tippen schreibt der Editor Entwürfe gebündelt nach
  localStorage (spätestens nach 300 ms und sofort beim Verlassen/Schliessen des Tabs) statt bei
  jedem Tastendruck. Aussehen und Verhalten unverändert.

### Behoben

- **Fotosuche in grossen Mandanten nicht mehr minutenlang:** Nach einigen Suchen auf derselben
  Datenbankverbindung (psycopg bereitet Abfragen nach 5 Ausführungen serverseitig vor) wechselte Postgres
  auf einen generischen Plan ohne Mandantenwert. Geschätzt für einen kleinen Mandanten, las er bei einem
  Mandanten mit 10 000 Fotos die ganze Dateiübersicht je Treffer neu (über 200 s statt 0.2 s). Alle
  Verbindungen des Backends und der Worker planen jetzt immer mit den echten Werten
  (`plan_cache_mode=force_custom_plan`, `app/core/db.py`); keine Migration, keine neue Einstellung.
- **Text-Editor:** Die Toolbar zeigt Fett, Kursiv, Listen und Rückgängig/Wiederholen nach Tastenkürzeln,
  Markdown-Eingaberegeln und im formatierten Text sofort an (vorher blieb z. B. «B» nach Strg/⌘+B
  unmarkiert). Die Listen-Knöpfe nennen ihr Kürzel im Tooltip.
- **Einstellungen:** Die Karte «Suche & Synonyme» zeigt ihre Beschreibung statt des rohen Schlüssels
  (alle Sprachen).
- **Abgabebox:** Upload-Fehler und Hinweise auf ähnliche Bilder erscheinen in der gewählten Sprache statt
  auf Deutsch (stabile Fehlercodes); Fehlermeldungen werden von Screenreadern angesagt und Entfernen-Knöpfe
  nennen ihre Datei; ist das Dateikontingent eines Dokuments ausgeschöpft, erscheint «Abgabe vollständig»
  statt eines Formulars, das jede Auswahl ablehnt; eine abgeschaltete Abgabebox wird auch auf direkt geteilten
  Abgabe-Links erklärt (statt «nicht gefunden»); die Prüfseite zeigt das Erstelldatum nach Schweizer Zeit.
- **Dateien und Fotos:** Hochladen, Teilen, Tags/Stichwörter und Album-Aktionen erscheinen nur noch mit
  passendem Recht bzw. Abo (vorher endeten sie mit 403).
- **Papierkorb:** Wiederherstellen und endgültiges Löschen (auch durch den Job) sperren die Datei; eine
  gleichzeitig wiederhergestellte Datei wird nicht mehr gelöscht.
- **Aufbewahrung:** Vorschläge werden vor dem Umsetzen nach der aktuellen Regel neu geprüft; nach gelockerter
  Regel oder inzwischen verknüpftem Bild wird nichts mehr gelöscht.
- **Gesamtexport:** gleichzeitige Anfragen legen nur noch einen Auftrag an.
- **Mitglieder:** leerer Name oder `null` beim Bearbeiten wird abgelehnt (422) statt die Mitgliederliste zu
  brechen; kaputte CSV-Dateien ergeben 400 statt 500; überlange ID-Listen der Massenaktionen 422 statt 500.

### Neu

- **Maildienst-Ausfall wird erkannt:** Jeder Versandversuch (Benachrichtigungen, Login-Code,
  Test-Mail) meldet sein Ergebnis an einen zentralen Versandstatus. Ist der Versand gestört, zeigt die
  Anmeldung statt «Code versendet» sofort «Anmeldung aktuell nicht möglich, wende dich an deinen
  Administrator» (nur für Anmeldungen, die einen Mailcode brauchen; bekannte Geräte und Konten mit
  zweitem Faktor sind nicht betroffen). «Passwort vergessen» und Einladungen weisen auf die Störung hin.
- **Systemmonitoring:** neue Prüfung «E-Mail-Versand» unter `/admin/system` (letzter Erfolg, letzter
  Fehler, Fehler in Folge, Fehlerklasse) mit ntfy-Alarm `email:smtp:<grund>`; nicht eingerichteter
  Versand erscheint ruhig als eigener Zustand. Versandfehler landen gedrosselt im Fehlerprotokoll
  (ohne Empfängeradressen). Dazu Checks `password_leak` und `geoip` («nicht eingerichtet» ohne Alarm).
- «Angemeldete Geräte», Mails «neues Gerät»/Sicherheitswarnung und die Ereignisliste im Admin-Panel
  zeigen das Land (übersetzter Name, Quellenangabe DB-IP); die Ereignisliste zeigt zusätzlich die
  Risikogründe.
- Sicherheitswarnungen quittieren (gilt, solange die Warnung offen ist; zählt nicht mehr in Glocke und
  Übersicht).
- Export von Anmeldeereignissen und Audit-Log (JSONL, mit Passwort verschlüsselt, höchstens 92 Tage,
  Passkey-Bestätigung, auditiert).
- «Konto anzeigen» zu einem Anmeldeereignis: ordnet das Pseudonym einem Konto zu (nur owner,
  Passkey-Bestätigung, auditiert, nie Netz/Adresse).
- Einstellungen › Sicherheit & Anmeldung, Integrationen, Technik (read-only).
- Systemstatus: Verlauf Datenbank und Redis (24 h/7/14 Tage); Speicher: Belegung aus dem täglichen Snapshot.
- Mandanten-Detail: Tabs Features & Module, Nutzung, Sicherheit.
- Sicherheitsereignis `reset.request` (layer `device`), wenn ein Passwort-Reset über das Gerätekontingent
  läuft oder es erschöpft ist.
- **Keywords für Fotos und Dateien:** zusätzliche Suchbegriffe je Datei, «weniger verbindlich» als
  Tags – nirgends angezeigt, nur für die Suche (Gewicht wie Tags, Tippfehler-tolerant). Bearbeiten in
  der Foto-Ansicht (Seitenleiste), im Datei-Detail der Ablage und für mehrere auf einmal (Fotos:
  Auswahl › Keywords; Ablage: neue Mehrfachauswahl › Keywords bearbeiten, hinzufügen/entfernen).
  Rechte wie beim Taggen (Fotos: `photos.manage`, Dateien: `files.manage`, nur eigener Mandant).
- **Synonyme in der Suche:** jedes Suchwort wird um gleichbedeutende Wörter erweitert (Gewicht 0.8,
  auch bei Tippfehlern im Suchwort): eingebauter Grundstock mit Vereins- und Schweizer Begriffen in
  de/en/fr/it (Velo↔Fahrrad, Hock↔Sitzung, Lager↔Zeltlager, Znüni↔Zvieri …) und eigene Gruppen je
  Verein unter Einstellungen › **Suche & Synonyme** (`settings.manage`).
- **Listen in der globalen Suche (Strg/⌘+K):** strukturierte Listen erscheinen nach ihrem Namen als
  eigene Gruppe «Listen» (nur mit `meetings.edit`, wie die Listenseite; Einträge werden nicht durchsucht).
- **Dateien per Drag-and-Drop in Pendenzen:** Dropzone im Pendenz-Dialog mit Duplikat-Abgleich (nur
  sichtbare Dateien), GPS-Rückfrage wie beim Foto-Upload; Abbrechen verwirft die im Dialog
  hochgeladenen Dateien in den Papierkorb (wiederherstellbar).
- **Website:** Logos der Mandanten in der Kundenleiste «Im Einsatz bei» (nur Mandanten mit
  «auf der Website zeigen» und Logo; eigene, gehärtete Logo-Route).
- E2E: axe-Prüfung (WCAG 2.1 A/AA) aller Admin-Seiten.

## [1.5.0] - 2026-11-21

Erstes Release nach 1.4.1 (1.4.2 wurde nie veröffentlicht; alles daraus ist hier enthalten).
Schwerpunkte: Anmeldeschutz für alle Konten (bekannte Geräte, Bestätigungscode bei riskanten
Anmeldungen, «Angemeldete Geräte», Sicherheitsmails), Plattform-Admin nur noch über die Admin-Domain
und mit Passkey, ein neu gegliedertes Admin-Panel mit Sicherheitsbereich und Analysen, eine
Wartungsseite statt Fehlerseiten während Updates, durchgängige Tastaturbedienung, eine neue
Fotosuche, neu gestaltete Abgabe-, Termin- und Datei-Dialoge sowie die schnelle Pendenz im Protokoll.
Update direkt von 1.4.1 mit `./scripts/deploy.sh <test|prod>`; sieben Migrationen (0202–0208).

### Update

**Kurz für Betreiber (Update von 1.4.1):**

- `./scripts/deploy.sh <test|prod>` wie gewohnt. Migrationen `0202_submission_todo_tags`,
  `0203_capture_date_in_file`, `0204_photo_search`, `0205_admin_passkey_only`, `0206_auth_hardening`,
  `0207_security_read`, `0208_platform_metrics` (Details unten).
- **Plattform-Admin nur noch mit Passkey:** Admin-TOTP und Admin-SSO werden entfernt, alle
  Admin-Sessions beendet; beim ersten Admin-Login richtet jedes Konto einen Passkey ein. Notausgang:
  `python -m app.admin_cli reset-passkeys --email …` (RUNBOOK Abschnitt 22).
- **Plattform-Admin nur noch über die Admin-Domain (OpenZiti):** Pflicht sind `TRAEFIK_ADMIN_DOMAIN`
  und `ADMIN_GATE_SECRET` (mindestens 32 Zeichen; `deploy.sh` erzeugt das Secret beim Update). Ohne
  beides startet die API ausserhalb der Entwicklung nicht.
- **Neuer Dienst `admin-frontend`** und **neues Netz `edge`:** Traefik und die angesprochenen Dienste
  werden beim Update neu erstellt (kurze Unterbrechung). Ein lokaler 1.4.0-Hotfix
  (`docker-compose.local.yml` mit `traefik.docker.network=hocx_default`) wird nicht mehr geladen und
  nach dem Update entfernt. Hängen in einer host-eigenen `docker-compose.local.yml` Netz-Aliase für
  Traefik (z. B. `.ziti`-Namen), müssen sie vor dem Update ins Netz `edge` statt `default` – sonst lässt
  das Admin-Gate nur Anfragen über `edge` durch und Admin antwortet mit 403.
- **Host-eigene Traefik-Dateien** in `infra/traefik/dynamic/` (z. B. `test-ziti-tls.yml` für ein eigenes
  Zertifikat) müssen in `.env` freigegeben werden: `TRAEFIK_HOST_DYNAMIC_FILES="test-ziti-tls.yml"`
  (Dateinamen, Leerzeichen/Komma getrennt). Sonst bricht die Prüfung über Traefik das Update ab.
- **Kein Rollback mehr nach Migrationen:** Scheitert ein Update, nachdem seine Migrationen gelaufen sind,
  bleibt das neue Release aktiv und wird Rollback-Ziel (ein altes Release startet gegen die migrierte
  Datenbank nicht, 1.5.0 entfernt mit `0205` Admin-Spalten). Besteht es die Smoke-Checks nicht, bleibt die
  Wartungsseite aktiv. `deploy.sh` nennt das Backup dieses Laufs für einen bewussten Weg zurück.
- **`INTERNAL_API_URL`** wird automatisch auf das interne `http://backend:8000` umgeschrieben.
- **Neue optionale Variablen:** `AUTH_SECRET_PREVIOUS`, `AUTH_LEGACY_COOKIE_UNTIL`, `AUTH_NET6_FACTOR`,
  `HOCX_ADMIN_SOURCE_CIDRS`, `HOCX_VERIFY_TENANT_DOMAIN_LIMIT`, `HOCX_DEPLOY_MAINTENANCE`,
  `HOCX_IMAGE_KEEP_RELEASES`/`HOCX_IMAGE_CLEANUP`.
- **E-Mail-Versand einrichten:** Riskante Anmeldungen von Konten ohne zweiten Faktor werden mit einem
  Code per E-Mail bestätigt; ohne SMTP werden sie in Verdachtsfällen abgewiesen.
- **«Abmelden»** beendet nur noch die Session dieses Geräts; «Alle anderen Geräte abmelden» im Profil.
- Der erste Admin-Login je Gerät meldet einmal «Plattform-Anmeldung von neuem Gerät».
- Protokolle mit abgewählten Terminfeldern bekommen beim nächsten Export eine neue Dokumentversion.
- **Neue Berechtigung `security.read`** (Sicherheit & Anmeldungen): nur die Standardrolle
  «Administrator» hat sie. Eigene Rollen mit nur «Zugänge verwalten» verlieren die Anmeldeaktivität –
  im Rollen-Editor `security.read` zuteilen.

**Details:**

- **Hosts mit dem 1.4.0-Hotfix** (`docker-compose.local.yml` mit nur
  `traefik.docker.network=hocx_default` an `abgabebox-backend`): Traefik hängt ab dieser Version nur
  noch im Netz `edge`; der Hotfix würde die Abgabebox unerreichbar machen. `deploy.sh` lädt ihn
  deshalb nicht mehr (Hinweis im Log) und entfernt die Datei nach dem erfolgreichen Update
  (Kopie unter `backups/`). Steht mehr in der Datei, bleibt sie - den Eintrag dann von Hand löschen.
- Nach dem Update meldet der erste Admin-Login je Gerät einmal «Plattform-Anmeldung von neuem
  Gerät» (Warnung) - das Gerät wird erst ab dann wiedererkannt.
- **Protokolle mit abgewählten Terminfeldern** bekommen beim nächsten Export eine neue
  Dokumentversion (das PDF lässt die Felder jetzt weg). Keine Migration.
- `./scripts/deploy.sh <test|prod>` wie gewohnt. Das Update startet den neuen Dienst
  `maintenance-page` (Image `nginxinc/nginx-unprivileged`, wird beim Pull geholt) vor den
  Migrationen und setzt `infra/maintenance/` auf die Gruppe 5001 (nur lesen). Traefik wird neu
  erstellt (neues internes Netz `maintenance`, kurze Unterbrechung von wenigen Sekunden beim
  `docker compose up`); die Datei `infra/traefik/dynamic/maintenance.yml` lädt es ohne Neustart. Beim
  Update auf diese Version selbst greift die Wartungsseite erst, sobald der Dienst läuft (also für
  den Austausch der App-Container bereits).
- Ab diesem Update ist hocX während der Datenbankmigration im Wartungsmodus (Fenster «Update» im
  Admin-Portal unter System → Wartung, Audit `admin.maintenance_deploy_started/_ended`). Beim
  Update **auf** 1.4.3 selbst gilt das schon: die CLI läuft mit dem neuen Backend-Image, das alte
  Frontend zeigt dann den allgemeinen Wartungstext. Meldet das Deploy-Log «Wartungsmodus des
  Updates ist NOCH AKTIV», das Fenster im Admin-Portal freigeben oder den im Log genannten Befehl
  ausführen.
- Eigene Domains der Mandanten: das Backend schreibt `tenant-domains.yml` beim Start neu, die
  Wartungsseite gilt dort also nach dem Neustart des Backends automatisch.
- Neue, optionale Variable `HOCX_DEPLOY_MAINTENANCE` (nur Shell, Standard an; `0` = ohne
  Wartungsmodus während des Updates).
- `./scripts/deploy.sh <test|prod>` genügt. **Neues Secret `ADMIN_GATE_SECRET`** wird beim Update
  automatisch in der `.env` erzeugt; `deploy.sh` schreibt daraus `.secrets/admin_gate_secret` und die
  Traefik-Datei `infra/traefik/dynamic/admin-gate.yml` (nicht im Repo). Traefik wird wegen der
  geänderten `traefik.yml` automatisch neu erstellt.
- Wer das Admin-Panel über einen Link von einer anderen Seite (oder nach dem SSO) öffnet, sieht kurz
  die Login-Seite, die mit bestehender Sitzung sofort weiterleitet (`SameSite=Strict`).
- **Beim Update werden Admin-TOTP und Admin-SSO entfernt; beim ersten Admin-Login wird ein Passkey
  eingerichtet.** Migration `0205_admin_passkey_only`: löscht alle MFA-Faktoren der Plattform-Admins
  (auch bisherige Admin-Passkeys, deren RP-ID die Hauptdomain war), beendet alle Admin-Sessions,
  entfernt `platform_oidc_config` und `platform_admin.oidc_*`, neue CHECK-Constraint (Admin-Faktoren
  nur `webauthn`). Downgrade möglich, ohne Daten zurück. Keine neuen Umgebungsvariablen ausser
  `HOCX_ADMIN_SOURCE_CIDRS`/`HOCX_VERIFY_TENANT_DOMAIN_LIMIT` (optional, siehe unten).
- Prüfadresse des Admin-Zugangs ist jetzt `GET /api/admin/auth/health` (statt
  `/api/admin/auth/oidc/public-config`) - auch für die Wartungsseite.
- `DEMO_TOTP_SEED` gilt nur noch für Mandanten-Demokonten, nicht mehr für Plattform-Admins.
- Neuer Dienst `admin-frontend` (gleiches Frontend-Image, `HOCX_FRONTEND_ROLE=admin`); `deploy.sh`
  startet und prüft ihn mit. `admin-gate.yml` wird jetzt nach `compose up` geschrieben (enthält die
  Quelladresse); abweichende Tunnel-Endpunkte über `HOCX_ADMIN_SOURCE_CIDRS`. `INTERNAL_API_URL`
  muss intern sein (Standard `http://backend:8000`), sonst bricht `deploy.sh` ab.
- Neues Netz `edge`: Traefik ist nur noch darin (mit den Diensten, die es anspricht), nicht mehr im
  Standardnetz; `compose up` erstellt die Dienste neu. Die Datenbank läuft ohne NET_RAW (nur die
  Rechte des Postgres-Entrypoints).
- `infra/traefik/dynamic` wird beim Deploy auf 3770 (Sticky-Bit) gesetzt, versionierte Dateien und
  `admin-gate.yml` auf 0640.
- **`INTERNAL_API_URL`** wird beim Update automatisch auf `http://backend:8000` umgestellt, falls
  dort noch die öffentliche Domain steht (Hinweis im Deploy-Log); `deploy.sh` verlangt ein internes
  Ziel.
- Admin-Konten-, Mandanten-Konten- und Plattform-Einstellungen (SMTP, ntfy) sowie das Klonen eines
  Mandanten verlangen jetzt ebenfalls eine Passkey-Bestätigung.
- Die Wartungsseite (Admin-Variante) prüft künftig `/api/admin/auth/health` über das Admin-Frontend.
- Fehlerbilder und Ablauf: RUNBOOK Abschnitte 21 (Admin-Zugang) und 22 (Anmeldung, Notausgang).
- **Migration `0206_auth_hardening`:** neue Tabellen `auth_event` (ohne Fremdschlüssel, RLS mit
  nullbarem `tenant_id`), `auth_session` und `auth_known_device` (beide `tenant_id NOT NULL`, RLS).
  Rein additiv, folgt auf `0205_admin_passkey_only`.
- **Niemand muss sich neu anmelden:** bestehende Session-Cookies (ohne Session-ID, alter Cookie-Name
  `hocx_session`) gelten bis zu ihrem Ablauf (höchstens 72 h; der alte Name wird bis
  `AUTH_LEGACY_COOKIE_UNTIL`, sonst Start + 72 h, gelesen) weiter; auf eine Mandanten-Domain werden sie
  nicht mehr weitergereicht; neue Anmeldungen bekommen
  `__Host-hocx_session` mit Session-ID. Alte Sessions erscheinen nicht in «Angemeldete Geräte»;
  «Alle anderen Geräte abmelden» beendet sie trotzdem. Laufende Bridge-Tokens (v3, 120 s) werden
  weiter eingelöst. Alte Redis-Zähler laufen nach höchstens 15 min aus.
- Neues optionales Secret `AUTH_SECRET_PREVIOUS` (leer lassen; nur für Rotation, RUNBOOK Abschnitt 23) -
  `deploy.sh` schreibt die Secret-Datei auch leer. Neue optionale Variablen `AUTH_*` (RUNBOOK Abschnitt 23).
- Neuer Hintergrundjob `auth_security_maintenance` (Backend, stündlich, Lock-ID 202600036).
- Für die Prüfung riskanter Anmeldungen ohne zweiten Faktor sollte der E-Mail-Versand eingerichtet
  sein.
- Abgabebox-Backend und Backend gemeinsam ausrollen (das Deploy-Skript tut das): die Abgabebox
  braucht das Spaltenrecht aus 0203.
- **Migration `0202_submission_todo_tags`:** zwei neue Spalten in `submission_assignment`
  (`todo_tags`, leer, und `todo_own_tag`, aus). Rein additiv; die Abgabebox liest sie nicht.
- **Migration `0203_capture_date_in_file`:** neue Spalten `stored_file.capture_exif_original` (JSONB,
  ursprüngliche Datumsfelder der Datei für «Original wiederherstellen») und
  `stored_file.capture_file_state` (`pending`/`written`/`unsupported`/`failed`, CHECK und Teilindex),
  dazu `SELECT` auf die Spalte `stored_file.source_checksum_sha256` für `hocx_abgabebox`
  (Duplikatprüfung). Bestehende Korrekturen werden auf `pending` gesetzt; der neue Job
  `capture_date_file_sync` (job-worker, jede Minute, unter `/admin/jobs`) schreibt sie danach in die
  Dateien. Downgrade möglich, bereits geschriebene Dateien behalten dann aber das korrigierte Datum.
- **Migration `0204_photo_search`:** Extensions `pg_trgm`, `unaccent`, `fuzzystrmatch` (in
  `postgres:18` enthalten, «trusted», die Migration läuft wie immer mit `DATABASE_URL`), neue Tabellen
  `photo_search_doc` und `photo_search_term` (je `tenant_id NOT NULL` und RLS), Trigger auf den
  Quelltabellen halten sie aktuell (`SECURITY DEFINER` mit festem `search_path`, ohne `EXECUTE` für
  andere Rollen). Die Migration indexiert alle bestehenden Dateien: rund 100 Sekunden je
  100'000 Dateien.

### Neu

- **Plattform-Admin neu gegliedert (Admin-Redesign):** Konsole mit einmal geladener Shell und sieben
  Bereichen (Übersicht, Mandanten, Benutzer & Zugänge, Sicherheit, Betrieb, Analysen, Einstellungen),
  Kompaktmodus der Seitenleiste («[»), Brotkrumen, Glocke für offene Prüfungen/Warnungen/Probleme und
  Umgebungs-Badge (Test/Dev). Ctrl+K/⌘K durchsucht Seiten, Aktionen, Mandanten und Domains (owner
  zusätzlich Benutzer mit maskierter E-Mail, Jobs, Checks, Audit-Codes; Begriff nie in der URL).
  Neues Dashboard mit Plattformstatus, Kennzahlen, «Zu erledigen», Anmelde-/Fehlerverlauf und
  Aktivitätsfeed; es lädt keine Benutzerlisten mehr. Mandanten haben eine eigene Detailseite
  (`/admin/tenants/<id>/…`) statt des grossen Dialogs; die Liste sortiert und filtert (Status,
  Speicher ≥85 %) mit Zustand in der URL. Profil & Passkeys als Seite `/admin/account`; alte Adressen
  (`/admin/audit`, `/admin/notifications`) leiten weiter.
- **Sicherheitsbereich im Plattform-Admin:** Übersicht (Fehlversuche 48 h, Warnungen, Sperren),
  Anmeldeereignisse, Sperren (setzen/entsperren mit Passkey), Warnungen, Audit-Log, Richtlinien
  (wirksame Anmeldeschutz-Werte, ohne Geheimnisse). Das Ansehen des Audit-Logs wird protokolliert.
- **Sicherheit & Anmeldungen für Vereins-Admins:** neue Seite unter Einstellungen › Organisation mit
  Warnungen (Konto unter Angriff, privilegierte Anmeldung auf neuem Gerät, MFA entfernt, Konto
  gesperrt), Anmeldeaktivität je Konto (ohne IP) und «Sitzungen beenden». Neue Berechtigung
  `security.read`, nur für die Standardrolle «Administrator»; die Anmeldeaktivität verlangt sie jetzt
  statt «Zugänge verwalten» – eigene Rollen mit «Zugänge verwalten» sehen sie erst, wenn das neue Recht
  zugewiesen wird. «Sitzungen beenden» gilt nur für Konten mit höchstens den eigenen Rechten, nicht
  für das eigene Konto (dafür «Andere Sitzungen abmelden» im Profil). Anmeldeereignisse, Sperren und
  die Sicherheitsübersicht im Plattform-Admin sind nur noch für owner lesbar.
- **Analysen:** täglicher Rollup (Job `metrics_rollup`, 90 Tage rückwirkend) für Wachstum, Nutzung,
  Feature-Buchungen, Umsatz, Auslastung, Speicher und Fehler; Fehlerprotokoll mit Zeitraum und
  gruppierter Ansicht.
- **Tastaturbedienung:** «?» öffnet eine Übersicht aller gerade gültigen Tastenkürzel (auch im
  Benutzermenü › Tastenkürzel), erster Tab-Halt jeder Seite ist «Zum Inhalt springen». Kürzel laufen
  zentral über eine Registry (keine Auslösung beim Tippen oder in offenen Dialogen, Strg und ⌘,
  CH/DE-Layouts); Tabs und Filter wechseln mit den Pfeiltasten, Reihenfolgen (Protokoll-Schnellnavigation,
  Elementdefinitionen, Tabellen-/Matrix-Designer) lassen sich ohne Ziehen ändern. Details:
  `KEYBOARD_AUDIT.md`, Regeln: `design/KEYBOARD_ACCESSIBILITY.md`, neue Prüfung
  `scripts/check-keyboard-a11y.py` (CI, Pre-Commit).
- **Wartungsseite statt Traefik-Fehlerseite:** Während eines Updates oder wenn ein App-Container
  nicht erreichbar ist, zeigen Hauptdomain, Admin-Zugang und Abgabebox eine Wartungsseite im
  hocX-Look (Deutsch, Englisch, Französisch, Italienisch, hell/dunkel), die alle 10 Sekunden prüft,
  ob hocX wieder da ist, und sich dann selbst neu lädt. API-Aufrufe bekommen ein JSON-503 mit
  `Retry-After`; das Frontend zeigt seine normale Fehlermeldung, die Abgabebox wiederholt einen
  Upload selbst. Ein 503 des Backends (Wartungsmodus, Überlast) bleibt unverändert, und
  Healthchecks wie `/api/health` liefern während eines Ausfalls 503, nie 200. Neuer kleiner Dienst
  `maintenance-page` im Traefik-Teil des Stacks (nginx, gleiches Image wie die Docs, nur statische
  Dateien aus `infra/maintenance/`), Traefik-Konfiguration in
  `infra/traefik/dynamic/maintenance.yml`, Ablauf und Tests in RUNBOOK Abschnitt 20.
- **Wartungsmodus während des Updates:** `deploy.sh` startet vor der Datenbankmigration ein volles,
  sofort aktives Wartungsfenster «Update» (neue CLI `python -m app.maintenance_cli begin-deploy`)
  und beendet es nach den Smoke-Checks, bei jedem Rollback und bei jedem Abbruch wieder
  (`end-deploy`; Rückfall direkt per SQL, falls die CLI scheitert). Solange es aktiv ist, sperren
  die noch laufenden alten Container die API mit ihrem bestehenden Wartungsmodus: angemeldete
  Nutzer sehen die Wartungsansicht statt Fehlern gegen ein halb migriertes Schema, die Abgabebox
  ihr Wartungsbanner. Admin-API, Healthchecks und Wartungsstatus bleiben erreichbar. Von Admins
  geplante oder Speicher-Wartungsfenster fasst das Update nie an. Abschalten:
  `HOCX_DEPLOY_MAINTENANCE=0`. Neuer Wartungsgrund `deploy` in Wartungsansicht und Admin-Portal
  (alle Sprachen). Lässt sich die Wartung nach einem sonst erfolgreichen Update nicht beenden,
  bricht das Update ohne Rollback mit Anleitung ab. Neue Systemprüfung «Wartungsmodus des
  Updates» (Warnung nach 30 Minuten, kritisch nach 2 Stunden, auch per ntfy).
- **Verlauf der Partner-Organisationen** im Reiter Partner-Organisationen, filterbar je Partner:
  Album-Einladungen, angenommene/abgelehnte Freigaben und öffentliche Links, die Partner auf eigene
  Alben erstellt haben. Neue Lese-Route `GET /api/public-links/partner-history`
  (`settings.manage`, nur Alben des eigenen Mandanten, Partner nur als Organisationsname, ohne IP-
  und E-Mail-Adressen). Keine Migration.
- **Pendenz «Abgabe einsammeln»:** Im Pendenz-Dialog (auch mobil) lässt sich zu einer Pendenz
  direkt eine Abgabe mit Datei einsammeln; Stand und Link stehen in der Pendenz, das Einsammeln
  lässt sich wieder beenden. Neue Routen `GET /api/protocol-todos/{id}/submission` und
  `POST /api/protocol-todos/{id}/stop-submission` (Rechte wie beim Anlegen einer Abgabe aus einer
  Pendenz).
- **Schnelle Pendenz im Protokoll:** Fälligkeit mit Smart-Daten-Vorschlägen («morgen», «nächste
  Sitzung» …), Personen mit Profil-Badge, optional direkt «Als Abgabe einsammeln» (Alt+A, Mac ⌥A,
  steht in der Tastenkürzel-Hilfe). Enter legt an, Escape legt eine angefangene Pendenz an und
  schliesst das Menü.
- Risk Engine v1 (deterministisch, versioniert, Score 0-100 mit Gründen) und Stufenmodell der
  IP-Sperren mit Entsperren über CLI (`python -m app.auth_security.cli`) und Admin-API
  (`/api/admin/auth-security/*`).
- Bestätigungscode per E-Mail für riskante Anmeldungen von Konten ohne zweiten Faktor (Mail im
  neuen Design, in der Sprache der Person).
- Sicherheitsmails: Anmeldung von neuem Gerät (abschaltbar, Kategorie «Anmeldung von neuem Gerät»),
  verdächtige Anmeldung, viele Fehlversuche, Anmeldung nach Sperre (Pflicht), jeweils mit «Warst du
  das nicht?» und Link auf Profil › Sicherheit; auch die bestehenden Hinweise zu Passwort/MFA haben
  den Link.
- Profil › Sicherheit › «Angemeldete Geräte»; Step-up-Dialog in der ganzen App.
- **Fotosuche:** sucht in allem, was hocX zu einem Foto weiss – Dateiname, Tags, Album, Termin
  (Titel, Tag, Datum), Abgabe und Element, Protokoll, Word-Import, hochgeladen von, Kamera,
  Aufnahmedatum (inkl. Korrektur). Reihenfolge der Wörter egal, Tippfehler toleriert («somerlager»,
  «zlet»), Umlaute/Akzente egal («braeteln» = «Brätel»), Wortanfänge reichen, Datumsangaben in allen
  Sprachen («2026», «Mai 2026», «02.05.2026», «2.5.», «juin»). Bei aktiver Suche sortiert «Beste
  Treffer» (alle Wörter vor einigen, Tags/Abgabe/Termin vor Dateiname). Auch die globale Suche nutzt
  das Ranking. Nur Fotos des eigenen Vereins; Papierkorb und fremde Partnerfotos bleiben draussen
  (Partnerfotos in geteilten Alben nur über den Dateinamen).
- **Aufnahmedatum in der Datei:** Korrigieren, Verschieben und «Original wiederherstellen» schreiben
  das Datum auch in die Bilddatei (EXIF), Downloads und Originale enthalten es. Das ursprüngliche
  Datum bleibt in hocX; Wiederherstellen macht die Datumsfelder byte-genau wie vorher. Die Anzeige
  in hocX ändert sich wie bisher sofort, die Datei folgt im Hintergrund (ohne Neukodierung, Pixel
  unverändert). JPEG, HEIC/HEIF, PNG, WebP und TIFF mit Aufnahmedatum werden an Ort und Stelle
  geändert, ein JPEG ohne Datum bekommt eines; andere Formate ohne Datum und Bilder über 50 MB
  behalten die Korrektur nur in hocX. Die ursprünglich hochgeladene Datei gilt weiter als Duplikat.
  Der Foto-Viewer zeigt dezent, ob die Datei schon aktualisiert ist; die Bestätigung erklärt es.
- **Pendenz als Abgabe einsammeln:** Im Pendenz-Dialog («Quelle») und im ⋮-Menü der Pendenzen im
  Protokoll legt «Als Abgabe einsammeln» mit einem Klick eine Einzelabgabe an: Titel = Aufgabe,
  Stichtag = Fälligkeit, Verantwortliche = Zugewiesene. Die Pendenz selbst wird die Pendenz der
  Abgabe (keine zweite) und schliesst sich nach dem Upload; Notizen, Dateien und Tags bleiben. Toast
  mit «Link kopieren» und «Anpassen». Nur mit «Abgaben verwalten» und «Sitzungen bearbeiten».
  Pendenzen aus Protokollen werden nie mit einer Abgabe gelöscht, sie verlieren nur den Bezug.
- **Tags für Abgabe-Pendenzen:** Im Abgabe-Assistenten (Schritt «Verantwortlich») gewählte Tags
  bekommt jede Pendenz der Abgabe; «Abgabe-Tag erstellen» (standardmässig aus) gibt zusätzlich ein
  Tag mit dem Titel der Abgabe. Änderungen ziehen nach, von Hand gesetzte Tags bleiben.

### Geändert

- **Status-Token der Uptime-Überwachung** wird nur noch einmal direkt nach dem Erzeugen angezeigt.
- **Eigene Domains der Mandanten** bekommen dieselbe Wartungsseite: die generierten Router in
  `tenant-domains.yml` tragen die errors-Middleware (App-Domains: hocX-Seite, Abgabebox- und
  Prüf-Domains: Abgabebox-Seite, APIs: JSON), dazu je Domain Ausweich-Router (Priorität 1 bzw. 50)
  mit genau den Pfaden der Domain. Fehlt `maintenance.yml`, bleibt die Datei wie bisher.
- Die Wartungsseite läuft in einem eigenen internen Netz nur mit Traefik und antwortet auch auf
  grosse Uploads mit 503 (statt 413).
- **Zugangslinks neu gestaltet** (Mandanten-Einstellungen › Zugangslinks, Design «hocX Zugangslinks»):
  ein einziger Lead-Text statt der doppelten Beschreibung, gelber Hinweis «n Links laufen nicht von
  selbst ab» mit Filter «Nur diese zeigen», Unterstrich-Reiter mit Zählern und eine kompakte
  Zeilenliste statt der Tabelle (Name, farbige Art · Grund, Gültigkeit mit «genutzt TT.MM.»,
  Aktionen «Verlauf», «Widerrufen», «Verwalten →»). Erstellt/von steht als Tooltip am Namen.
  Widerrufen bestätigt man direkt unter der Zeile statt im Dialog; der Knopf erscheint nur mit
  dem Recht «Öffentlich teilen». Partner-Links auf eigene Alben stehen jetzt im Reiter
  Partner-Organisationen und lassen sich dort vom Album-Besitzer ebenfalls widerrufen.
- **Abgabe-Formular v6:** Anlegen und Bearbeiten einer Abgabe nach Design v6 mit neuen Bausteinen
  Segment-Umschalter, Zahlenfeld mit −/+ und Schalter (alle per Tastatur bedienbar). Als
  Verantwortliche lassen sich jetzt alle Personenfelder eines Termins bzw. einer Liste wählen.
  «Tags für die Pendenzen» schlägt die vorhandenen Pendenz-Tags vor (neue Lese-Route
  `GET /api/todos/tags`, `meetings.read`); ein Komma trennt Tags. Höchstens 999 Dateien je Element.
- **Bausteine-Liste und Element-Dialog** (Vorlagen › Elemente) nach Design: Liste der
  Elementdefinitionen, eigener Dialog mit nummerierten Bausteinen (Ziehen oder Alt+Pfeil),
  Löschen mit Rückfrage in der Zeile. Termin- und Pendenzzeilen im Tabellen-Baustein sind
  sortierbar. Im Element abgewählte Terminfelder erscheinen nicht mehr im Protokoll-PDF.
  Aktionsmenüs können Einträge mit einer Trennlinie absetzen.
- Daten für die kommenden Sicherheits-Dashboards: `/api/admin/auth-security/summary|events|blocks`
  (Plattform) und `/api/auth-security/activity` (Verein, `access.manage`, datensparsam).
- «Abmelden» beendet nur noch die Session dieses Geräts (bisher alle); «Alle anderen Geräte abmelden»
  im Profil bzw. `POST /api/auth/logout-all`.
- Kontoweite Sperre: ab 30 Fehlversuchen/15 min brauchen unbekannte Geräte nach korrektem Passwort eine
  zusätzliche Prüfung (zweiter Faktor oder E-Mail-Code); bekannte Geräte sind ausgenommen. Ohne
  E-Mail-Versand werden Konten ohne Faktor auf unbekannten Geräten nur bei auffälliger Quelle oder über
  100 Fehlversuchen abgewiesen; Konten mit Faktor nie.
- «Passwort vergessen»: höchstens 3 Mails je Adresse und Stunde, weitere Anfragen ohne Versand (202).
- TOTP: nach 10 Fehlversuchen in 15 min noch ein Versuch je Minute.
- `SECURITY_ALERT_ADMIN_LOGINS` ist neu standardmässig `true`.
- **Fotos-Seite (Design «Fotos Header 1a»):** Titel mit Anzahl, «Papierkorb» und «Bilder hochladen»
  oben rechts, Werkzeugkasten mit Alle Fotos/Alben/Duplikate/Ähnliche, Suchfeld mit Leeren-Knopf,
  Sortierung und Tag-Filter; bei Suche oder Filter eine Zeile «N von M Fotos» mit Filter-Chips und
  «Filter zurücksetzen», eigener Leerzustand «Keine Fotos für „…“».
- **Datei-Detail (Design «Datei-Detail Popup v2»):** Kopf mit Typ-Icon, Name (mit Recht per Klick
  umbenennbar, die Endung bleibt), Quelle, Verarbeitungsstatus, «hochgeladen von» und Version;
  links PDF-Ansicht oder extrahierter Text (kopierbar), ältere Versionen ansehbar; rechts «Details &
  Tags» (Herkunft, Tags mit «neu erstellen» und häufigen Tags, Verarbeitungsschritte mit «Erneut
  verarbeiten», Details mit MIME-Typ) und «Verlauf» mit allen Versionen; im Fuss «In den Papierkorb»
  mit Bestätigung direkt im Fuss, danach «Wiederherstellen» oder «Nächste Datei →», sowie «Link
  teilen», «In neuem Tab» und Herunterladen. Blättern mit ← / → bleibt.
- **Termin-Dialog (Design «Termin Dialog v3»):** ein Dialog für Anlegen und Bearbeiten überall
  (Terminliste, Kalender, Protokoll-Planung, Mobile): Kalenderblatt und Titel oben, Reiter
  «Übersicht» (Beschreibung, Programm, Zeitraum, Standort, Tag, Zyklen), «Teilnehmer & Status»
  (Absage, Teilnehmerzahl, Personen je Rolle) und «Weitere Felder» (Spezialfelder). Bearbeiten
  speichert automatisch («✓ Alle Änderungen gespeichert»); beim Anlegen erst «Termin erstellen»,
  danach ebenso. Löschen und Absagen im ⋮-Menü.
- **Verlauf:** Die erste Seite aktualisiert sich live (neue Einträge kurz hervorgehoben).
  Datensparsamer: erfolgreiche Anmeldungen sind für den Verein nur 30 Tage sichtbar (Fehlversuche
  und Änderungen länger, die Plattform-Administration sieht alles bis zur Aufbewahrungsfrist); wer
  den Verlauf öffnet, steht selbst darin; ein Hinweis erinnert an die Datenschutzerklärung.
- **E-Mail-Link zu den Benachrichtigungs-Einstellungen:** Der Link im Fuss jeder
  Benachrichtigungs-Mail führt jetzt direkt in die persönlichen Einstellungen (Profil, Reiter
  «Benachrichtigungen»; Direktlink `/?profile=notifications`, auch nach der Anmeldung) statt auf die
  Organisations-Einstellungen. Linktext «Benachrichtigungs-Einstellungen».
- **Strg+K:** Der Eintrag «In dieser Liste suchen» entfällt, der erste Treffer ist wieder die Seite.
  Strg+F (⌘F) im Suchfenster übernimmt den Begriff in die Listensuche.
- **Update räumt alte Images auf:** `deploy.sh` entfernt nach einem erfolgreichen Update alte
  hocX-App-Images. Behalten werden laufende, das aktuelle Release und die letzten 3 Releases
  (`HOCX_IMAGE_KEEP_RELEASES`, abschaltbar mit `HOCX_IMAGE_CLEANUP=0`); fremde Images und
  andere Projekte auf dem Host bleiben unberührt.
- **«Meine Aufgaben»** hat denselben Schalter «Alle/Meine» wie Aufgaben › Pendenzen; Abgabe-Pendenzen
  mit Fälligkeit zeigen in der Herkunftszeile «· erledigt sich mit der Abgabe».
- **Fotos, Datei-Detail und Termin-Dialog:** Die Fotoseite nutzt die volle Breite. Im Datei-Detail
  sind «PDF-Ansicht» und «Extrahierter Text» gleich hoch, und der Termin-Dialog behält auf dem Desktop
  in allen Reitern dieselbe Höhe (nur der Inhalt scrollt), sodass beim Wechseln nichts springt.
- **Aufgabenpakete bei Terminabsage:** Wird ein Termin abgesagt, werden noch offene Paket-Instanzen
  dieses Termins abgebrochen (keine Erinnerungen und Bussen mehr); wird er wieder aktiviert, gehen genau
  diese Instanzen auf ihren vorherigen Status zurück. Von Hand abgebrochene bleiben abgebrochen.

### Behoben

- **Ohne Maus nicht bedienbar:** Einträge von Aktions-, Status- und Benutzermenüs (Fokus springt
  jetzt ins Menü, Pfeiltasten, Fokus zurück zum Auslöser), Tag-Vorschläge und Tag-Farben, Werkzeugleiste
  des Texteditors, Pendenz aus der Liste öffnen, Mandanten und Protokolldetails im Plattform-Admin.
  Rückfragen und Vollbild-Ansichten halten den Fokus, nach dem Schliessen landet er wieder am
  Auslöser (bzw. im Inhalt, wenn der Auslöser gelöscht wurde). Strg+Enter und Pfeiltasten im
  Protokoll lösen in Dialogen und Listen nicht mehr den Editor aus; Strg+Alt+T/N funktionieren auf
  dem Mac. Die eingeklappte Seitenleiste ist kein unsichtbares Tab-Ziel mehr.
- **Abgabe-Assistent übersprang den letzten Schritt:** Ein Klick auf «Weiter» im vorletzten Schritt
  (Dateien) legte die Abgabe sofort an, statt den Schritt «Zugriff» zu zeigen - der Knopf wurde noch
  im selben Klick zum Erstellen-Knopf. Jetzt erstellt nur «Abgabe erstellen» im letzten Schritt.
- **«Endgültig löschen» im Papierkorb scheiterte gelegentlich** («Dateien konnten nicht endgültig
  gelöscht werden»): lief für ein Dokument gerade die PDF-Erzeugung, sperrten Löschen und
  Dokument-Worker dieselben Zeilen in umgekehrter Reihenfolge, die Datenbank brach mit einem
  Deadlock ab. Das Löschen wartet jetzt auf den Worker.
- **Foto-Viewer:** Die Knöpfe oben hatten keinen Hover-Effekt, «Original öffnen» war beim Überfahren
  unlesbar (weiss auf weiss) und «Best-of» nie hervorgehoben. Jetzt reagieren alle auf Hover und
  Tastaturfokus, «Best-of» ist gelb, wenn das Foto markiert ist.
- **Bussen aus Pendenzen:** Der Buchungstext steht jetzt in der Dokumentsprache des Vereins statt
  immer auf Deutsch.
- **Statistik:** Pendenzen ohne Protokolldatum zählen nach dem Schweizer Kalendertag (eine Pendenz
  vom 1.1. um 00:30 fiel bisher ins Vorjahr).
- **Word-Import:** «Neu analysieren?» fragt nur noch nach, wenn wirklich schon etwas geprüft wurde.

### Sicherheit

- **Plattform-Admin nur noch über die Admin-Domain (Auth-Audit SEC-AUTH-001):** Die Admin-API war über
  jede aktive Mandanten-Domain aus dem Internet erreichbar. Jetzt mehrfach abgesichert: Mandanten-
  und alle öffentlichen Router schliessen `/admin` und `/api/admin` aus, ein Sperr-Router mit höchster
  Priorität beantwortet diese Pfade auf dem öffentlichen Entrypoint für jede Domain mit 404, die
  Admin-Router setzen einen geheimen Gate-Header (öffentliche Entrypoints entfernen ihn), das Backend
  nimmt `/api/admin` nur damit und auf der Admin-Domain an (sonst 404), das Frontend liefert `/admin`
  nur auf der Admin-Domain aus. Mandanten-Domains, die einer Systemdomain gleichen oder Subdomain der
  Admin-Domain sind, werden abgelehnt. Das Admin-Session-Cookie ist jetzt `SameSite=Strict`.
- **Plattform-Admins nur noch mit Passwort + Passkey:** TOTP und das Admin-SSO (OIDC) sind
  vollständig entfernt. Passkeys sind Pflicht (RP-ID = Admin-Domain, Nutzerverifikation, jede
  Challenge einmalig), ein Konto ohne Passkey richtet nach dem Passwort zwingend einen ein und
  erhält erst danach eine Session. Mehrere Passkeys je Admin, der letzte ist nicht entfernbar. Die
  Backup-Wiederherstellung verlangt eine frische Passkey-Bestätigung statt eines TOTP-Codes.
  Notausgang: `python -m app.admin_cli reset-passkeys --email …` im Backend-Container.
- **Security-Review der Abschottung:** Der Admin-Entrypoint nimmt nur noch die Quelle des
  Ziti-Tunnels an (Gateway des Compose-Netzes; ein Container im selben Netz bekommt 403).
  Das Admin-Panel läuft als eigener Dienst `admin-frontend`; das öffentliche Frontend liefert `/admin`
  nie aus und sieht nie den Gate-Header, der nur an ein internes `INTERNAL_API_URL` geht. Kritische
  Admin-Aktionen (Passkeys, Admins, Mandant löschen/exportieren, Speicher, Backups, Katalog,
  MFA-Reset) verlangen eine an genau diese Anfrage gebundene Passkey-Bestätigung. Ohne Admin-Domain
  und Gate-Secret startet die API ausserhalb der Entwicklung nicht. Ein Passkey mit rückläufigem
  Zähler wird gesperrt (Systemcheck «Admin-Passkeys»). Notausgang zusätzlich `reset-password`.
  Der Sperr-Router kennzeichnet seine 404 (`X-Hocx-Admin-Block`), die Deploy-Prüfung verlangt das
  Kennzeichen, prüft Pfad-Varianten, POST und alle Mandanten-Domains (höchstens 20) und lässt im
  Traefik-Dateiprovider nur bekannte Dateien zu. PyJWT entfernt (nicht mehr verwendet).
- Deploy und `verify_release.sh` prüfen von aussen, dass die Admin-Pfade auf Haupt-, Abgabebox-,
  Admin-, Docs-, Website- und einer Mandanten-Domain über den öffentlichen Entrypoint nicht
  erreichbar sind; sonst Rollback.
- **SEC-AUTH-002:** Längenlimits für E-Mail (320), Passwort (1024), Tickets und Codes in allen
  Anmelde-Schemas; 16 KiB Body-Limit für `/api/auth/*` und `/api/admin/auth/*`; Zählerschlüssel in
  Redis nur noch als HMAC-Pseudonym (keine E-Mail, keine IP, Länge fix). Redis voll/weg: definierte
  Fail-Closed-Regeln (503 `rate_limiter_unavailable`/`auth_temporarily_unavailable`), bekannte Geräte
  melden sich mit lokaler Notgrenze weiter an.
- **SEC-AUTH-003/-005:** gemeinsame atomare Zähler-Primitive (Lua: Zählen und Ablauf in einem Schritt,
  gleitendes Fenster, GCRA); Versuche werden **vor** der Passwort-/Code-Prüfung gezählt. Wartungsjob
  repariert Zähler ohne Ablauf.
- **SEC-AUTH-004:** TOTP-Code wird atomar beansprucht (`UPDATE … WHERE totp_last_counter < :c`),
  derselbe Code gilt nie zweimal.
- **SEC-AUTH-006:** bekannte Geräte (signiertes Cookie, serverseitig widerrufbar) sind von der
  kontoweiten Sperre ausgenommen - Lockout-DoS gegen fremde Konten wirkt nicht mehr auf die Inhaberin.
- **SEC-AUTH-007:** App-seitige Schichten je Quelle (IPv4 /32, IPv6 /64), Netz (IPv4 /24, IPv6 /48,
  IPv6 /32 für Versuchsrate und Alarm), Konto+Quelle, Konto, Gerät, global (Angriffsmodus) und je
  Mandant (Alarm); Versuchsrate je Quelle auch auf Mandanten-Domains; IP-Sperren für IPv6 je /48.
- **SEC-AUTH-010:** Step-up (frische Bestätigung mit Faktor bzw. Passwort) für Faktor-Änderungen,
  Passwortwechsel mit Faktor, Rollen/Rechte, Passwort/Login anderer Konten, fremde MFA-Resets,
  Einladung von Admin-Konten, MFA-Pflicht abschalten, Vier-Augen-Einstellung, eigene Domains,
  Gesamt- und Personendaten-Exporte.
- **SEC-AUTH-011:** Session-Register (`auth_session`): Inaktivität 8 h, absolut 14 Tage, Einzel-
  Widerruf, «Nur dieses Gerät» vs. «Überall abmelden», Logout-Kaskade über die Domain-Bridge,
  Passwort-/MFA-Änderung beendet die anderen Sessions, Schlüsselrotation über `AUTH_SECRET_PREVIOUS`,
  Widerruf in Millisekunden (Token aus derselben Sekunde wie der Widerruf gilt nicht mehr).
- **SEC-AUTH-012:** einheitliches Ereignisschema `auth_event` für alle Anmeldephasen inkl. gesperrter
  Versuche, Passkey-Fehlschlägen, eigener Faktor-Löschung, Logout; Alarmregeln (Stuffing, Spraying,
  Konto unter Beschuss, Admin-MFA, Mandanten-übergreifend, IP-Sperren, Limiter-Ausfall) über ntfy;
  Check `auth_protection` (Redis-Speicher, Limiter, private Quelladressen).
- **SEC-AUTH-014:** WebSocket nutzt dieselbe Kontoprüfung wie REST (ausgetretene Mitglieder werden
  abgewiesen).
- **SEC-AUTH-015:** Passwortregel bei allen Setzpfaden (eigener Wechsel, Anlegen/Setzen durch Admins,
  Plattform), erweitert um Folgen, Leetspeak und eine kleine Offline-Liste häufiger Passwörter.
- **SEC-AUTH-016/017/018/020:** ausgetretene Konten erhalten die generische 401; Reset-Kontingent je
  Adresse und Quelle getrennt; Session- und Geräte-Cookies mit `__Host-`-Präfix; Bridge-Tokens werden
  je Session wiederverwendet; WebAuthn prüft Algorithmus, Kurve und RSA-Länge.
- **Plattform-Admins im Anmeldeschutz:** Die Passwortphase des Admin-Logins läuft über denselben
  Anmeldeschutz wie bei Konten (Zählen vor dem Prüfen, Scope `login-admin`), ohne IP-Sperren der
  Stufen 4/5 (Ziti-Notzugang). Passkey-Versuche werden vor der Prüfung gezählt (danach 1/min).
  Admin-Logins, Passkey-Bestätigungen, Passkey einrichten/entfernen und Abmelden erscheinen als
  Sicherheitsereignisse; die Alarme «Fehlgeschlagene Admin-MFA» und «Plattform-Anmeldung von neuem
  Gerät» greifen. Der Notausgang (`admin_cli`) setzt die Zähler jetzt wirklich zurück.
- **Mandanten-Domains:** TOTP-Prüfung und Domain-Auflösung haben dort dieselben Ratelimits wie auf
  der Hauptdomain (SEC-AUTH-007). Widerruf von Sessions (Konten und Admins) mit Mikrosekunden-
  Auflösung: ein vor dem Widerruf ausgestelltes Token ist sicher ungültig, eine direkt danach neu
  ausgestellte Session gilt.
- **Passwort vergessen:** Ist das Kontingent je Adresse erschöpft (z. B. weil Fremde Anfragen
  auslösen), bekommt die Inhaberin auf einem ihr bekannten Gerät trotzdem eine Mail (höchstens 3/h je
  Gerät, 6/h je Konto). Die Antwort bleibt für alle gleich (kein Rückschluss auf Konten).
- **Listenstand rekonstruieren:** übernimmt aus einem Entwurf nur noch Name, Beschreibung und
  Aktiv-Status, keine System- oder Identitätsfelder.

## [1.4.1] - 2026-11-20

Die Übersicht der Abgaben und das Abgabe-Detail folgen jetzt vollständig dem Design «Abgaben v4»
(in 1.4.0 war nur der Dialog zum Anlegen und Bearbeiten umgesetzt). Einzelabgaben haben neu
beliebig viele, von Hand angelegte Abgabeelemente mit eigenem Stichtag und eigenen Verantwortlichen.
Dazu ein Papierkorb für Dateien und Fotos, ein korrigierbares Aufnahmedatum (einzeln und als
Mehrfachauswahl), die Seite «Kasse» mit Konten und Bussen nach Design «Kasse und Bussen v2»,
Blättern im Datei-Detail, Prüfungen aller Dienste von aussen beim Update und die
Behebung des 504 auf Prüfseite und Abgabebox. Dazu alle Funde des Nachtlaufs vom 20.11.2026
(Abgabebox, Bussen und Pendenzen, Fotos und Freigaben, Termine und Zyklen, Rechte im Protokoll).
Vier Migrationen (0198, 0199, 0200, 0201), keine neuen Secrets oder Umgebungsvariablen, keine
Breaking Changes.

### Update

- Von **1.4.0**: `./scripts/deploy.sh <test|prod>`.
- Wer den Hotfix für die Prüfseite (`docker-compose.local.yml` nur mit
  `traefik.docker.network=hocx_default` für `abgabebox-backend`) angelegt hat: das Update verschiebt
  die Datei automatisch nach `backups/`, die Korrektur ist im Release enthalten. Enthält die Datei
  weitere eigene Einstellungen, bleibt sie unverändert (Hinweis im Deploy-Log).
- **Migration 0198 (`0198_submission_manual_elements`):** neue Tabelle `submission_manual_element`
  (Elemente der Einzelabgaben, `tenant_id NOT NULL`, RLS für `hocx_app`, für `hocx_abgabebox` nur
  lesend und nur für den Mandanten des Upload-Links, ohne Verantwortliche) und die Spalte
  `submission_upload.manual_element_id` (Fremdschlüssel nur auf Elemente derselben Abgabe). Jede
  bestehende Einzelabgabe bekommt genau ein Standard-Element: Name = Titel der Abgabe, Stichtag =
  bisheriger Stichtag (der Stichtag der Abgabe selbst wird geleert). Das Element behält die
  Referenz `manual`, bestehende Einreichungen, verknüpfte Dateien, Pendenzen und persönliche Links
  gehören weiter dazu. Trigger und Zählfunktionen der Abgabebox kennen die neuen Elemente.
  Downgrade möglich: Einreichungen zusätzlicher Elemente gehen im einen Element der Einzelabgabe
  auf, deren persönliche Links werden widerrufen, der Stichtag kommt vom Standard-Element zurück.
  Abgabebox-Backend und Backend gemeinsam ausrollen (das Deploy-Skript tut das).
- **Migration `0199_stored_file_soft_delete`** (Papierkorb): neue Spalten `stored_file.deleted_at`
  und `deleted_by`, ein Teilindex und eine RESTRICTIVE-Policy, die Papierkorb-Dateien vor den
  Rollen `hocx_abgabebox` und `hocx_photo_worker` verbirgt. Läuft beim Deploy automatisch, ohne
  Datenänderung. Ein Downgrade holt alle Dateien aus dem Papierkorb zurück (nichts wird gelöscht).
  Neuer Hintergrundjob `file_trash_purge` im job-worker (stündlich, unter `/admin/jobs`).

- **Migration `0200_photo_capture_override`** (Aufnahmedatum korrigieren): neue, leere Spalten in
  `stored_file` (`capture_corrected_at`, `capture_corrected_has_time`, `capture_corrected_set_at`,
  `capture_corrected_set_by`). Rein additiv, EXIF-Datum und Dateien bleiben unverändert; Rücknahme
  mit `alembic downgrade` entfernt die Korrekturen.
- **Migration `0201_abgabebox_scan_status`:** die Rolle `hocx_abgabebox` darf zusätzlich die Spalte
  `stored_file.scan_status` lesen (nur `SELECT` auf diese eine Spalte, Zeilen weiter per RLS auf den
  Link-Mandanten begrenzt). Keine Datenänderung; Downgrade nimmt das Recht wieder weg.

### Geändert

- **Papierkorb für Dateien und Fotos:** Löschen auf der Dateien-Seite, in der Foto-Ansicht, in der
  Mehrfachauswahl und bei «Nur beste behalten» legt Direkt-Uploads in den Papierkorb, statt sie
  sofort zu entfernen. Gelöschte Dateien verschwinden überall (Listen, Galerie, Zeitstrahl, Suche,
  Alben, Freigabelinks, Pendenzen, Exporte, Statistik); ein Freigabelink nur auf gelöschte Dateien
  liefert «Link ungültig». «Papierkorb» auf der Dateien- und der Fotos-Seite zeigt Name, Datum und
  Person der Löschung sowie die verbleibenden Tage; «Wiederherstellen» bringt Alben, Tags,
  Termin-/Abgabe-Bezug, Pendenz-Verknüpfungen und Freigaben zurück, «Endgültig löschen» und
  «Papierkorb leeren» löschen sofort. Nach 30 Tagen löscht der Job `file_trash_purge` endgültig.
  Papierkorb-Dateien zählen bis dahin zum Speicherkontingent (eigene Kategorie «Papierkorb» in der
  Speicherbelegung). Wer Fotos bzw. Dateien verwalten darf, sieht und bedient den Papierkorb.
  Löschungen nach Datenschutzrecht, beim Offboarding, durch Aufbewahrungsfristen und bei
  Virenfunden bleiben sofort und endgültig und schliessen den Papierkorb ein. Ein erneuter Upload
  einer Datei aus dem Papierkorb wird normal gespeichert statt als Duplikat abgelehnt.
- **Abgaben-Übersicht (Design «Abgaben v4»):** Jede Abgabe ist eine Karte mit Titel, Quelle und
  Zeitfenster, Fortschrittsbalken samt Status («7 von 9 erledigt · 1 geschlossen · 1 in Prüfung»)
  sowie Bearbeiten und Löschen. Die Reiter «Offen» und «Abgeschlossen» sind unterstrichen, im Kopf
  stehen «Virenprüfung aktiv» als Chip, «Links» mit Anzahl und «+ Abgabe».
- **Abgabe-Detail:** Filter «Alle / Abgegeben / Ausstehend» mit Anzahl, die Termine bzw. Einträge
  als Kacheln mit Statuspunkt und Kurzinfo, unten der Hinweis zur ClamAV-Prüfung neben «Alle Dateien
  (.zip)». Ein einzelner Termin oder Eintrag öffnet sich im selben Fenster, «← Termine» führt
  zurück. Der Links-Dialog erklärt kurz, wie Links und Abgaben zusammenhängen.
- **Pendenz erstellen** sieht aus wie «Pendenz bearbeiten»: Aufgabe gross oben, links Status, Tags,
  Notizen und Dateien, rechts Zuweisung (auch mehrere Personen), Fälligkeit und Protokoll.
- **Mitglied erfassen:** Der Anzeigename füllt sich beim Tippen aus Vor- und Nachname und lässt sich
  danach von Hand ändern; eine eigene Eingabe bleibt stehen.
- **Datei-Details:** Bei Dateien aus einer Abgabe steht unter «Element», aus welchem Termin (mit
  Datum) bzw. Listeneintrag sie stammt. Mit ← / → (oder den Knöpfen oben) blättert man wie bei den
  Fotos durch die Dateien der Liste; offene Tag-Änderungen werden vorher gespeichert.

- **Kasse (Design «Kasse und Bussen v2»):** Konten und Bussen sind eine Seite «Kasse» mit den
  Reitern «Konten» und «Bussen» (Zähler der offenen Bussen am Reiter); `/finances` und `/fines`
  bleiben die Adressen der Reiter, Links, Suche und Seitenleiste funktionieren unverändert.
  - **Bussen:** Kennzahlen (offen, kassiert im laufenden Jahr, Personen mit offenen Bussen), ein
    Hinweis auf Pendenzen-Bussen mit Regel-Konflikt samt «Anzeigen», Filter Offen/Kassiert/Gelöscht/
    Alle mit Suche und die Ansichten «Nach Person» (Karte je Person mit Tarif, offener Summe und
    «Kassieren» bzw. «Alle kassieren») und «Liste» (sortierbare Tabelle). Jede Zeile hat Haken,
    Status («Offen», «Läuft», «Konflikt», «Kassiert», «Gelöscht») und ihre Aktion (Löschen, Erlassen,
    Wieder öffnen, Wiederherstellen, Regel wählen). Nach Kassieren, Löschen, Erlassen und Wieder
    öffnen bietet der Hinweis «Rückgängig» an (führt die Gegenaktion aus). «+ Busse» steht im Kopf.
  - **Konten:** Kontenliste mit Anzahl Buchungen, Saldo und offenen Bussen je Konto, das erste Konto
    ist gleich geöffnet; Jahres-Chips statt Auswahlliste, «+ Buchung» als Hauptaktion, neue Buchungen
    werden kurz hervorgehoben und Buchungen aus Bussen tragen «Aus Busse · nur über Bussen änderbar».

- **Fotos: Aufnahmedatum korrigieren:** Stimmt das Aufnahmedatum eines Bildes nicht (z. B. falsch
  gestellte Kamera), lässt es sich im Foto-Viewer korrigieren (Datum, optional Uhrzeit) oder in der
  Galerie per Mehrfachauswahl «Aufnahmedatum» für bis zu 500 Bilder ändern: alle auf dasselbe Datum
  setzen, um Tage/Stunden verschieben (Bilder ohne Aufnahmedatum werden übersprungen und gemeldet)
  oder das Original wiederherstellen. Jede Änderung braucht eine Bestätigung, die erklärt, was sie
  bewirkt. Das korrigierte Datum gilt überall vor EXIF und Schätzung (Zeitstrahl, Sortierung,
  Monatsgruppen, Datumsfilter, Termin-Zuordnung, Metadaten, Teilen-Seite, Downloads/Exporte); das
  EXIF-Datum bleibt gespeichert und wird als «ursprünglich» angezeigt, die Datei selbst wird nicht
  verändert. Nur mit `photos.manage`, nur Bilder des eigenen Vereins, ein Audit-Eintrag pro Aktion.
  Migration `0200_photo_capture_override` (neue Spalten in `stored_file`).
- **Einzelabgaben mit mehreren Abgabeelementen:** Im Assistenten legt man bei «Einzelabgabe» in
  Schritt 2 («Elemente») beliebig viele Elemente an («+ Element», Entfernen per Icon), je mit Name,
  optionalem Start und Stichtag; in Schritt 3 wählt man je Element eine oder mehrere verantwortliche
  Personen. Jedes Element verhält sich wie ein Termin oder Listeneintrag: eigene Kachel im Detail,
  einzeln wählbar und hochladbar in der Abgabebox, eigene Pendenz für die Verantwortlichen (fällig am
  Stichtag, nachgeführt bei Änderung und Entfernen), Fortschritt, ZIP-Download und Datenexport je
  Element. Bestehende Einzelabgaben behalten ihr eines Element und verhalten sich wie bisher. Die
  Datenauskunft listet die Elemente, für die eine Person verantwortlich ist.

### Behoben

- **Prüfseite und Abgabebox antworteten live mit 504:** Die Abgabebox hängt in zwei Docker-Netzen;
  ohne Angabe wählte Traefik je nach Neustart die IP im internen Speicher-Netz, das es nicht erreicht.
  Jetzt ist das Netz fest vorgegeben (wie beim Backend), ein Test prüft das für alle Dienste.
- **Update prüft alle Dienste von aussen:** `deploy.sh` ruft nach dem Start jeden Traefik-Router über
  die echte Domain auf (Frontend, Backend-API, Abgabebox-Seite und -API samt Prüfseite, Admin, Docs,
  Website). Ist ein Dienst nicht erreichbar, geht das Update automatisch auf das vorherige Release
  zurück. `verify_release.sh` nutzt dieselben Prüfungen.
- **Fotos, Zeitstrahl rechts:** Ganz oben lag die Monatsangabe («Okt. 2026») über der Jahreszahl
  und ragte aus der Leiste. Sie steht dort jetzt unter der Linie, die Jahreszahl am Cursor entfällt.
- **Pendenzen und Bussen (Nachtlauf):**
  - Geteilte Regel-Bussen gehen auf den Rappen auf (5.– für 3 Personen: 1.67 + 1.67 + 1.66 statt
    3 × 1.67 = 5.01).
  - Eine Pendenz, die von «abgebrochen» auf «erledigt» wechselt, bekommt das Erledigungsdatum neu;
    bisher galt der Abbruchzeitpunkt, und eine verspätete Pendenz blieb ohne Busse.
  - Keine Mail «Busse droht» mehr an Personen, die für die Pendenz schon gebüsst sind.
  - Kasse: «kassiert im Jahr» zählt nach Schweizer Zeit (eine Busse vom 31.12. abends zählte ins
    neue Jahr).
  - Anwesenheit: erneut «Verspätet» nach einer bereits kassierten Busse legt keine zweite an (bisher
    409, der Status sprang zurück). Wer keine Bussen verwalten darf (z. B. «Schreiber»), kann in
    Blöcken mit Bussen trotzdem Abwesenheit erfassen; die Bussen bleiben dann Sache der Kasse.
- **Abgabebox (Nachtlauf):**
  - Ein Zeitfenster am Rand des Kalenders (Altbestand mit riesigem Abstand) brachte die öffentliche
    Abgabe mit 500 zum Absturz.
  - Der Dateiname einer Abgabe trägt das Schweizer Datum (kurz nach Mitternacht stand der Vortag).
  - Nach dem automatischen Schliessen eines Elements bietet die Erfolgsseite keinen weiteren Upload
    mehr an, der sonst scheiterte.
  - Termine und Abgaben stehen in derselben Reihenfolge wie in der Verwaltung.
  - Eine Datei, deren frühere Abgabe einen Scanfehler oder Schadware-Befund hatte, gilt nicht mehr
    als Duplikat und wird nicht still verworfen, sondern normal geprüft.
- **Fotos und Freigaben (Nachtlauf):**
  - Bilder ohne Aufnahmedatum zählen mit dem Schweizer Upload-Tag (Uploads zwischen 00:00 und
    01:00/02:00 fielen auf den Vortag).
  - Das Ablaufdatum eines öffentlichen Links gilt bis zum Ende dieses Tages in Schweizer Zeit (bisher
    lief er schon um 00:00 UTC ab).
  - Der Aufnahmezeitraum auf der Teilen-Seite springt nicht mehr um einen Tag.
  - Die Linkübersicht zählt bei Album-Links nur, was der Link wirklich zeigt (ohne ausgeblendete
    Partnerfotos).
  - Ein abgesagter Termin bekommt keine Fotos mehr automatisch zugeordnet, beim Absagen lösen sich
    die automatischen Zuordnungen (manuelle bleiben).
- **Termine und Zyklen (Nachtlauf):** Eingaben, die bisher mit 500 oder einem Eintrag im
  Fehlerprotokoll scheiterten, werden jetzt als Eingabefehler abgelehnt bzw. abgefangen:
  NUL-Zeichen in Terminen, Zyklen, Kalender-Abo und CSV-Import; ausdrückliches `null` beim Ändern
  eines Zyklus; Protokolldatum ausserhalb 1900–2999 (Altbestand legt die Zyklenliste nicht mehr
  lahm); zu grosse Teilnehmerzahl (auch im CSV-Import, mit eigener Meldung); Terminfilter-Fenster
  über ±100 Jahre; derselbe Zyklus doppelt in einem Termin; zu grosses `skip` in Terminlisten.
- **NUL-Zeichen und Seiten-Offset in allen Routen:** Eine neue Middleware lehnt NUL-Zeichen in
  Pfad, Query und JSON-Body zentral mit 422 ab, bevor eine Route sie sieht (bisher je nach Route
  500 oder 400 mit Eintrag im Fehlerprotokoll). `skip`/`offset` sind in allen Listen begrenzt
  (bisher «bigint out of range»); ein Test hält das für neue Routen fest.
- **Entschuldigen ohne Bussenrecht:** Das Dashboard sagt jetzt, dass offene Bussen der
  entschuldigten Person stehen bleiben und nur entfernen kann, wer Bussen verwalten darf.
- **Rechte-Übersicht:** Prüfungen, die nur in einem Zweig laufen, stehen als «je nach Fall»
  (`requires_if`) statt als Pflicht, z. B. `meetings.approve` beim Ändern des Protokollstatus (nur
  beim Zurückholen aus «abgeschlossen») oder `access.manage` bei Personen (nur mit Login). Muster
  «`user.can(A)` sonst `require_permission(B)`» erscheint als «A oder B». Die Rollen-Matrix zeigt
  dadurch korrekt, dass «Schreiber» Personen ohne Login ändern und löschen darf.
- **Bussen-Regeln › Pendenzen-Regeln:** Ein Klick irgendwo in die Zeile öffnet «Bearbeiten».
- **Personenseite:** Texte genau nach Design «Mitglied Profil» (Kartenbeschreibungen, Hinweis bei «Aktives Mitglied» je nach Zustand, einziger Tarif).
- **Abgeschlossene Protokolle:** «PDF öffnen» zeigt das finale PDF sofort. Bisher lief jedes Öffnen
  über den PDF-Auftrag im Hintergrund (Ladeseite «Ihr PDF wird erstellt»), obwohl am Ende dasselbe
  PDF mit derselben Dokument-ID zurückkam.

### Sicherheit

- **Protokoll zurückstufen:** Aus «abgeschlossen» zurück (auch per `PATCH` des Status) verlangt
  jetzt `meetings.approve`, wie das Abschliessen selbst.
- **«Entschuldigen» (Dashboard):** entfernt offene Anwesenheitsbussen nur noch mit `fines.manage`
  (und schreibendem Modul «Finanzen»), alle offenen Bussen der Person und mit Audit-Eintrag
  `fine.deleted` in derselben Transaktion. Protokolle, die die Person nicht lesen darf, antworten
  mit 404.
- **Protokoll löschen:** Hat das Protokoll Anwesenheitsbussen, braucht Löschen `fines.manage`
  (sonst Meldung «zuerst in der Kasse entfernen»). Einkassierte Bussen sperren das Löschen für alle,
  bis sie in der Kasse wieder geöffnet oder gelöscht sind (sonst bliebe die Buchung ohne Busse). Das
  Audit `protocol.deleted` listet die mitgelöschten Bussen.

## [1.4.0] - 2026-11-19

Eine neu eingeteilte Seitenleiste nach Tätigkeiten mit «Meine Aufgaben» und gesammelten
Einstellungen, eine Fotogalerie mit Zeitstrahl und ruhigem Scrollen, gesperrte und ausgeblendete
ausgetretene Personen, ein Versandprotokoll aller E-Mails im Admin-Portal, neutrale Begriffe
(«Organisation» statt «Verein») in allen Sprachen sowie 15 Sicherheits- und Datenschutz-Fixes aus
den Nachtläufen. Dazu Termine mit Uhrzeiten, Programm und Markdown-Texten, ein neu gestalteter
Tabellenblock mit Assistent, ein einheitliches, tolerantes Uhrzeitfeld, Dateien als Kacheln mit
PDF-Vorschau, gekennzeichnete Entwürfe, wenn einem Export Berechtigungen fehlen, und eine
Prüfseite, die veränderte Dateien über die Dokument-ID zuordnet und Seite für Seite vergleicht.
Ausserdem Listen mit beliebig vielen Spalten, ein neues Dashboard und eine neue Statistik, alles zu
einer Person auf einer Personenseite, MFA-Pflicht für ganze Organisationen, ein geführter
Erstlogin über die Einladung und eine neu gestaltete öffentliche Teilen-Seite.
Neu gestaltet sind ausserdem die Einstellungen (eigene Übersicht, Rahmen und Seitenleiste nur
noch mit Arbeitsbereichen), Abo & Rechnungen, die Personenseite, der Pendenzen-Kalender und das
Anlegen von Abgaben; das Protokoll scrollt ohne Sprung, die Suche (Ctrl+K) versteht alle Sprachen.
Dazu alle Funde des Nachtlaufs vom 19.11. samt Härtungen und den Major-Updates auf Node 26 und
TypeScript 7.
Keine neuen Secrets oder Umgebungsvariablen, keine Breaking Changes.

### Neu und geändert am 19.11.: Designs, Navigation und Suche

- **Sitzungsvorlagen:** Duplizieren, Archivieren und Löschen stehen im ⋮-Menü der Zeile; die
  Tabelle passt so auch neben die Einstellungs-Navigation.
- **Personenseite im neuen Profil-Design:** Der Kopf zeigt Initialen, Name, Status (Aktiv,
  Inaktiv oder Austritt mit Datum), «Mitglied seit …» und den Tarif; rechts führt «Login und
  Rolle» zum Abschnitt «Login & Rollen», das ⋯-Menü bündelt «Ansehen als …», Datenauskunft und
  «Login entziehen». Stammdaten, Mitgliedschaft, Bussentarif und Login & Rollen stehen als Karten
  mit Beschreibung links. Neu: «Aus Vor- und Nachname» für den Anzeigenamen, ein Hinweis bei
  geänderter Login-Adresse, ein Schalter «Aktives Mitglied», die Anwesenheitslisten als
  Checkliste mit Zähler und der Tarif als Kachel, Karten oder Liste je nach Anzahl Tarife.
  Unten stehen Erfasst-/Änderungsdatum und «Mitglied löschen»; die schwebende Leiste zählt die
  ungespeicherten Änderungen und bestätigt mit «✓ Gespeichert».
- **Abo und Rechnungen (Mandant-Einstellungen › Abo):** Die Seite hat zwei Reiter. «Abo &
  Nutzung» zeigt Plan und Rhythmus, das Total pro Monat bzw. Jahr und die offenen Rechnungen als
  Kennzahlen, darunter die Kostenaufstellung «Plan & Module» (Grundplan mit den enthaltenen
  Funktionen, Zusatzmodule nach Bereich mit Preisen, Rabatt, Total) sowie Nutzer und Speicher.
  «Rechnungen» (`?tab=invoices`, Zähler rot bei Überfälligem) zeigt Offenes, die nächste Rechnung
  und das im Jahr Bezahlte, die Liste mit Filter Alle/Offen/Erledigt und pro Rechnung ein
  Seitenpanel mit Periode, Fälligkeit, Zahlung und Positionen. Der Überfällig-Hinweis öffnet die
  Rechnung direkt.
- **Einstellungen an einem Ort (Design «hocX Einstellungen»):** Die Seitenleiste zeigt nur noch
  die Arbeitsbereiche – Übersicht und Meine Aufgaben, Sitzungen (Protokolle, Kalender, Anliegen),
  Aufgaben (Pendenzen, Abgaben), Kasse (Konten, Bussen) und Ablage (Mitglieder, Dateien, Fotos,
  Listen). Alle Einstellungen öffnet der neue Knopf «Einstellungen» über der Benutzerkarte: eine
  Übersicht mit Suchfeld, Hinweis «Braucht Aufmerksamkeit» (Zugangslinks ohne Ablaufdatum) und
  Karten in den Gruppen Bereiche, Auftritt und Organisation, je mit Beschreibung und – wo bekannt –
  Status. Jede Einstellungsseite hat denselben Rahmen: Kopfzeile «Einstellungen / Seite», links die
  Unternavigation und bei Einstellungen eines Bereichs der Weg «← Zurück zu …». Das Profil der
  Organisation ist neu in Stammdaten, Finanzen und Spezialfelder der Termine gegliedert. Die
  globale Suche findet weiterhin jede Einstellung; auf dem Handy steht unter «Mehr» der Eintrag
  «Einstellungen».
- **Protokoll scrollen ohne Sprung:** Mit eingeklappten Punkten öffnet sich der nächste Punkt
  schon beim Hinscrollen schrittweise, der vorherige schliesst sich im gleichen Mass. Der Inhalt
  in der Bildmitte läuft genau mit dem Mausrad mit; kein schlagartiges Auf-/Zuklappen und kein
  Nachrücken der Ansicht mehr. Scrollbalken und Sprünge (Schnellzugriff, Suche) rechnen mit dem
  ganz offenen Dokument und landen dadurch exakt.
- **Menü «Sitzungen»:** «Protokolle» steht zuoberst, vor Kalender und Anliegen.
- **Links teilen ohne Namen:** Der Name eines Freigabe-Links ist freiwillig. Ohne Eingabe gilt
  der Vorschlag im Feld bzw. heisst der Link wie die Datei, das Album oder «N Dateien».
- **Foto-Angaben nur bei Bildern:** Aufnahmedatum, Standort und Kamera werden beim Teilen nur
  angeboten, wenn auch Bilder geteilt werden; Dokumente gehen ohne diese Auswahl.
- **Dateien:** Die Liste nutzt die volle Breite wie die Fotos-Seite.
- **Abgabe anlegen und bearbeiten (Design «Abgaben v4»):** Eine neue Abgabe entsteht in fünf
  Schritten – Grundlage, Zeitraum, Verantwortlich, Dateien, Zugriff – mit anklickbarer
  Schrittleiste; rechts steht laufend, wie sich die Abgabe verhält. Beim Bearbeiten fasst je eine
  Karte die Abschnitte zusammen (fehlender Tag oder Link in Warnfarbe), «Ändern» öffnet jeweils
  einen Abschnitt. Tags, Listen, Zyklus, Verantwortliche, Sortierung, Prüfer und Sichtbarkeit
  werden als Chips gewählt (bei sehr vielen Einträgen weiter mit Suche). Im Detail einer Abgabe
  gibt es «Bearbeiten» direkt im Kopf.
- **Suche (Ctrl+K) in allen Sprachen:** Menüs und Einstellungen werden auch mit Begriffen der
  anderen Sprachen gefunden («logs», «settings», «paramètres» auf Deutsch und umgekehrt), dazu
  mehr Synonyme je Eintrag. Ein Tippfehler je Wort (ab 5 Buchstaben) wird verziehen; solche
  Treffer stehen zuunterst.
- **Pendenzen-Kalender neu gestaltet:** Monat gross im Kopf, daneben ‹ / Heute / ›, rechts das
  Feld «Anzeigen» mit den Umschaltern «Pendenzen» und «Termine». Tage anderer Monate sind grau
  hinterlegt, Einträge stehen als einzeilige Chips (Pendenzen mit Kästchen, überfällige rot,
  Termine grün mit Uhrzeit). Die rechte Spalte mit «Überfällig», «Ohne festes Datum», Legende und
  Abo-Link scrollt eigenständig; auf schmalen Bildschirmen steht sie unter dem Raster.

### Sicherheit (Nachtlauf 19.11., Härtungen und geklärte Verdachte)

- Fixes aus dem Nachtlauf 2026-11-19: Live-Updates melden keine Änderungen fremder Listen mehr;
  Listeneinträge werden nur aus der verknüpften Liste übernommen (auch bei Verantwortlichen);
  Support-Admins sehen die Objektliste einer Speicher-Migration nicht mehr; Mail «Abgabe
  zurückgezogen» nur an Konten mit Abgaben-Verwaltung; Katalog-Import gleicht die Module der
  Mandanten an; Abgabebox-Links erscheinen nicht mehr im Fehlerprotokoll; ICS-Export entfernt
  Steuerzeichen; Bildrouten antworten bei fremden Protokollen mit 404; Termin- und
  Listeneintrag-Löschen lassen bei gleichzeitigem Upload keine Datei zurück.
- pydantic-Update mit Sicherheitsfix (GHSA-qpmf-fgh3-ff25, GHSA-3r8g-cqwr-jr29).
- Härtungen aus dem Nachtlauf-Review: Protokolle (Entwürfe, nicht zugeordnete), die man nicht
  lesen darf, antworten überall wie unbekannte (404 statt 403, auch Aufgaben, Dateien,
  Dokumente und Document-Studio-Referenzen); Hilfsabfragen der Live-Zusammenarbeit laufen an den
  Mandanten gebunden (RLS); Kalender-Abo und ICS-Export entfernen auch U+0085/U+2028/U+2029 und
  DEL; Fehlertexte einer Speicher-Migration (auch für Support-Admins sichtbar) enthalten keine
  Objektschlüssel, Pfade oder SQL-Parameter mehr.
- Offene Verdachte aus dem Nachtlauf 2026-11-19 geklärt: Anwesenheitslisten übernehmen und zeigen
  nur Personen des eigenen Vereins; Vorlagen nehmen Listeneinträge nur aus der genannten Liste des
  eigenen Vereins an; der Foto-Worker darf an Analyseaufträgen nur noch Status, Zeiten und Fehler
  ändern (Migration 0197); Logos, Bilder und Schriften des Document Studio zählen zum
  Speicherkontingent und werden bei vollem Kontingent abgelehnt.
- Nachbesserungen aus dem Security-Review: auch nicht zugewiesene Vorlagen und nicht lesbare Dateien
  antworten mit 404 wie unbekannte; Fehlertexte der Speicher-Bereinigung zeigen Support-Admins keine
  Objektschlüssel mehr; ersetzt man eine Rollenliste nach einer Einzeländerung ganz, gilt die
  Ersetzung; Termin löschen und gleichzeitig einen Zyklus anlegen scheitert nicht mehr.

### Behoben (Nachtlauf 19.11. und Restpunkte)

- Aus dem Nachtlauf: Termindaten auf 1900–2999 begrenzt (Kalender-Abo übersteht Altdaten), Tags
  höchstens 100 Zeichen, Terminsuche behandelt % und _ als Text, kaputte CSV ergibt 400 statt
  500; parallele Abgleiche (Aufgabenpakete, Abgabe-Pendenzen, Termin bearbeiten, erstes
  Kalender-Abo) warten statt zu scheitern; Fehler in Dokumentverarbeitung, Mail-Aufbau, ntfy
  und Speicher-Bereinigung landen im Fehlerprotokoll bzw. blockieren nicht mehr; übersetzte
  Texte im Revisionsvergleich, auf der Prüfseite und im Word-Import, Exportdialog bleibt nach
  Wechsel auf Kalender nicht hängen, Word-Import-Dateiauswahl per Tastatur.
- Restpunkte aus dem Nachtlauf 2026-11-19: eine scheiternde Bereinigung alter Speichergenerationen
  wird mit wachsendem Abstand (30 s bis 1 h) statt alle 5 s wiederholt; unbekannte Generation ergibt
  404 statt 409. Hinweise der Word-Import-Analyse und des Imports erscheinen in der UI-Sprache.
  CSV-Importe von Terminen und Personen nehmen höchstens 2000 Zeilen an (übersetzte Meldung statt
  langer Verarbeitung). Das Zeitfenster einer Abgabe ist auf 3650 Tage vor/nach dem Termin begrenzt;
  Altbestände mit grösserem Wert gleichen wieder ab. Ein Termin, der gleichzeitig mit einem neuen
  Zyklus (oder einer Stichtag-Änderung) angelegt wird, landet jetzt zuverlässig im richtigen Zyklus.
  Weitere fest deutsche Texte (Vorlagen-Teilnehmerauswahl, Verantwortliche, Matrix-Löschfragen,
  Word-Import-Feldabgleich, Rückfrage beim Teilen von Fotos) übersetzt; der Hardcoded-Text-Check
  erkennt jetzt auch Text neben `{Ausdrücken}` und Template-Literale.
- ICS-Export im Document Studio übersteht Termine mit Enddatum 9999-12-31 (wie das Kalender-Abo);
  der Katalog-Import vermerkt den importierenden Admin bei neu gebuchten Modulen.
- Suchen behandeln % und _ überall als Text (Vorlagen, Protokolle, Dateien, Pendenzen-Termine,
  Plattform-Admin: Mandanten, Domains, Rechnungen, Mail-Protokoll, Audit-Log); im Mail-Protokoll
  findet «max_muster» die Adresse wieder.
- Termine: Wählen zwei Personen gleichzeitig jemanden in eine Rolle (Teilnehmende, Leitung …),
  bleiben beide Änderungen erhalten - gespeichert wird nur noch die Differenz zum Ausgangsstand.

### Abhängigkeiten (Node 26, TypeScript 7, msoffcrypto-tool 6)

- Frontend und Abgabebox-Frontend laufen auf Node.js 26 (`node:26-bookworm` bzw.
  `node:26-bookworm-slim`, per Digest gepinnt; CI-Jobs mit `setup-node` ebenfalls auf 26).
- TypeScript 7.0.2 (nativer Compiler) und `@types/node` 26.6.6 in beiden Frontends; Typprüfung,
  Tests und `next build` (Next.js 16.4.5) laufen ohne Codeänderungen.
- `msoffcrypto-tool` 6.0.0 (Excel-Verschlüsselung der Document-Studio-Exporte), API unverändert.

### Update

- Von **1.3.0**: `./scripts/deploy.sh <test|prod>`. Von älteren Ständen gelten zusätzlich die
  Hinweise von 1.3.0.
- Migration `0183_abgabebox_link_scope`: Die Datenbankrolle der Abgabebox liest Speicherbelegung,
  Objektregister und Kontingent nur noch für den Mandanten ihres Links; das Spaltenrecht auf
  `tenant` entfällt. Zwischen Migration und Neustart (wenige Sekunden in `deploy.sh`) kann die noch
  laufende alte Abgabebox Uploads mit einem Kontingentfehler ablehnen - wie beim Update auf 1.2.x
  (`0147`). Rücknahme mit `alembic downgrade` stellt die alten Rechte wieder her.
- Migration `0184_event_times_program`: vier neue, leere Spalten an `event` (`end_time`,
  `spezial_time1`, `spezial_time2`, `program`). Bestehende Termintexte sind gültiges Markdown und
  bleiben unverändert.
- Migration `0185_document_page_fingerprints`: neue, leere Spalte `page_fingerprints` im
  Dokumentenregister und die Funktion `verify_document_pages` (nur `EXECUTE` für die
  Abgabebox-Rolle). Seiten-Fingerabdrücke entstehen nur für PDFs ab dem Update.
- Migration `0186_list_columns`: neue Tabelle `list_column` (Spalten je Liste, RLS wie
  `list_entry`) und `list_entry.values_json`; die zwei bisherigen festen Spalten samt Werten und den
  Rollen «Bezeichnung»/«Verantwortlich» werden übernommen. Die alten Spalten bleiben (leer
  beschreibbar) in der Datenbank, damit `alembic downgrade` sie wieder füllen kann – Werte ab der
  dritten Spalte gehen dabei verloren, der sichere Rückweg ist das Backup vor dem Update.
- Migration `0187_list_column_config_keys`: schreibt Spalten-Verweise in Elementen, Vorlagen,
  offenen Protokollen, Dokumentvorlagen, Abgaben und Word-Import-Entwürfen auf die neuen
  Spalten-Keys um (stapelweise). Wer während des Updates ein Protokoll offen hat, lädt danach neu.
  Abgeschlossene Protokolle bleiben unverändert (alte Snapshots liest ein Adapter).
- Migration `0188_tenant_require_mfa`: neue Spalte `tenant.require_mfa` (Standard aus).
- Gesamtexporte haben jetzt Format 10 (Listen-Spalten); ältere Exporte lassen sich weiter
  importieren.
- Alle Adressen bleiben gleich, Lesezeichen und Links in Mails funktionieren weiter. Neu sind
  `/my-tasks` («Meine Aufgaben») und `/participants/<id>` (Personenseite).
- Ausgetretene Personen (Austrittsdatum vor heute) können sich ab dem Update nicht mehr anmelden,
  auch wenn ihr Login eingeschaltet ist; laufende Sitzungen enden. Wer das Austrittsdatum entfernt,
  gibt den Login wieder frei.
- Migration `0189_stored_file_context`: jede Datei bekommt einen Kontext (Abgabe, Protokoll, Album,
  Ablage), nachgetragen aus den Verknüpfungen; Trigger halten ihn aktuell. Keine Verhaltensänderung.
- Migration `0190_permission_catalog_v2`: zwölf neue Berechtigungen. Bestehende Rollen bekommen sie
  so, dass **niemand ein Recht verliert** (z. B. «Dateien verwalten» → zusätzlich «Dateien ansehen»,
  «Fotos ansehen/verwalten», «Öffentlich teilen»; «Kassen verwalten» → «Bussen verwalten»;
  «Daten exportieren» → «Personendaten exportieren»). Alle Rollen bekommen «Eigene Pendenzen
  erledigen»; wer nur lesen soll, dem nimmt man dieses Recht.
- Migration `0191_tenant_four_eyes`: Vier-Augen-Prinzip für Protokolle je Organisation (Standard aus).
- Migration `0192_mfa_role_and_grace`: MFA-Pflicht je Rolle (Standard aus), erste Anmeldung und
  MFA-Frist je Konto; die erste Anmeldung wird aus dem Verlauf nachgetragen.
- Migration `0193_drop_slug_and_member_rule`: der **Kurzname** der Organisation und die
  Aufbewahrungsregel «Ehemalige Mitglieder deaktivieren» entfallen samt Daten (Ausgetretene sind
  ohnehin ab dem Austritt gesperrt). Partner findet man beim Album-Teilen über den Namen.
- Migration `0195_scope_and_reviewers`: Spalte `tenant_role_permission.scope` (leer = alle, wie
  bisher) und Tabelle `resource_assignment` (Prüfer je Abgabe-Auftrag, RLS je Mandant). Keine
  Verhaltensänderung für bestehende Rollen. Rücknahme mit `alembic downgrade` entfernt Prüfer und
  Reichweiten; «nur zugewiesene» wirkt danach wieder auf alle Abgaben.
- Migration `0196_context_visibility`: Tabelle `context_visibility` (Kontext-Freigaben je
  Organisation und Abgabe-Auftrag, RLS je Mandant). Alle Organisationen starten mit «nur Rolle» –
  nach dem Update sieht niemand eine Datei, die er vorher nicht sah. Rücknahme mit
  `alembic downgrade` entfernt die Freigaben; danach gelten nur noch die Rollenrechte.
- Migration `0197_photo_worker_columns`: Die Datenbankrolle des Foto-Workers darf an
  `photo_analysis_job` nur noch `status`, `started_at`, `finished_at` und `error` ändern (vorher die
  ganze Zeile). Kein Verhalten ändert sich; Rücknahme mit `alembic downgrade` stellt das alte Recht
  wieder her.
- Die Frontend-Images laufen auf **Node 26** (vorher 24) und bauen mit TypeScript 7. Nach dem Update
  auf dem Test-Host die Abnahme ausführen.

### Neu: Server aus dem Backup wiederherstellen

- `./scripts/deploy.sh <test|prod> --restore-from-backup` richtet einen neuen, leeren Server direkt
  aus dem Borg-Backup ein: `.env` aus der Notfallmappe, neuer SSH-Schlüssel für die Storage Box mit
  fertiger `authorized_keys`-Zeile, Host-Key-Prüfung, Wahl des Wiederherstellungspunkts, Restore von
  Datenbank und Dateien ins lokale S3, danach der normale Deploy und eine Checkliste. Abgebrochene
  Läufe lassen sich mit demselben Befehl fortsetzen. Auf einem Server mit Daten verweigert er den Start.
- Recovery-CLI: `restore-full --local-s3` (Ziel lokales Garage, das Profil «Lokales S3» der
  Sicherung bleibt), `list --tsv` und `show --schema-state` für Skripte.

### Behoben: PDFs entstehen nur noch bei Änderungen

- Bisher erzeugte jedes «PDF öffnen» ein neues PDF mit neuer Dokument-ID, auch ohne Änderung (nur
  die Versionsnummer blieb gleich). Jetzt liefert hocX bei offenen Protokollen das letzte PDF,
  solange Inhalt, Gestaltung, Status, Sprache und Optionen gleich sind; jede Änderung ergibt wie
  bisher ein neues PDF mit neuer Version.
- Abgeschlossene Protokolle erzeugten ebenfalls bei jedem Öffnen ein neues PDF. Jetzt liefert hocX immer das finale PDF (gleiche Dokument-ID, gleicher Prüf-Hash),
  auch bei anderer Oberflächensprache. Ein neues finales PDF entsteht erst nach Zurückstufen und
  erneutem Abschliessen, oder wenn im Export-Dialog ausdrücklich eine andere Sprache, Vorlage,
  andere Optionen oder ein anderer Titel gewählt werden.

### Neu: Termine mit Uhrzeiten, Programm und Markdown

- Termine haben **Beginn** und **Ende** (Uhrzeit), zwei frei benennbare **Spezial-Uhrzeiten**
  (Name und Sichtbarkeit unter Mandant-Einstellungen › Spezialfelder) und ein Textfeld **Programm**.
- **Beschreibung, Programm und Spezial-Texte** sind Markdown: im Terminformular, beim Anlegen, auf
  dem Handy und in Tabellenblöcken formatiert bearbeitet und angezeigt, im PDF formatiert
  ausgegeben, in Listen als Kurztext.
- Spezialfelder tragen im Terminformular den Hinweis **Spezialfeld** mit Link direkt zu den
  Einstellungen, wo sie umbenannt oder ausgeblendet werden.
- Der Tabellenblock kann die neuen Felder aus dem Termin übernehmen («+ Feld aus Termin»), ein
  Textblock kann ins Programm zurückschreiben, und das Kalender-Abo übernimmt die Endzeit.

### Neu: Uhrzeitfeld als Standard

- Jede Uhrzeit-Eingabe versteht freie Schreibweisen und korrigiert sie beim Verlassen oder mit
  Enter: `1130` und `11:30` → 11:30, `230` → 02:30, `9h30`, `9.30`, `14 Uhr`, `7pm` usw. Auch die
  Wartungsfenster im Admin-Portal nutzen jetzt dieses Feld.
- Für Entwicklung und Agents verbindlich (`design/DESIGN.md` Abschnitt 6, `CLAUDE.md`); der
  Design-Checker meldet Zeitfelder ohne den Standard.

### Neu: Tabellenblock bearbeiten

- Zeilen werden direkt im Block-Dialog aufgeklappt und bearbeitet: Terminfelder als eigene Gruppe
  zuoberst, eigene Zeilen mit Zeilentyp, Vorbelegung, Sperre und Sortieren per Ziehen.
- Umschalter «Eigene Zeilen» / «Globale Liste», Vorschau als Editor- oder PDF-Ansicht, bei «Pro
  Termin» für einen der aktuell passenden Termine; «Welche Termine?» zeigt, wie viele Blöcke
  entstehen.
- Bei «Pro Pendenz» übernimmt der Block Felder der Pendenz («+ Feld aus Pendenz»: Aufgabe,
  Beschreibung, Zugewiesen an, Fällig, Status, Herkunft). Sie stehen zuoberst, im Protokoll nur
  lesend und live aus der Pendenz, im PDF ohne leere Zeilen.
- Der Block-Dialog ist in Reiter gegliedert (Inhalt, Wiederholung, Grundlagen, Verhalten). Ein
  neuer Tabellenblock startet mit einem Assistenten: wiederholen, filtern, Quelle, Vorlage.

### Neu: Exporte ohne alle Berechtigungen sind gekennzeichnete Entwürfe

- Fehlen einer Person Berechtigungen für Teile eines Protokolls (z. B. Pendenzen anderer, Bussen,
  Entwürfe), warnt der Export-Dialog und nennt die fehlenden Berechtigungen genau.
- Solche PDFs sind immer Entwürfe ohne Versionsnummer, mit Banner und Platzhaltern dort, wo Daten
  fehlen - es fällt nichts unbemerkt weg. Die Prüfseite weist sie als eingeschränkte Fassung aus.
- Entwürfe tragen jetzt immer das Wasserzeichen «Entwurf»; das Abschalten entfällt.
- Tabellen- und Textexporte bleiben sauber (keine Platzhalter in Zellen), sind aber gekennzeichnet:
  Excel bekommt vorne ein Blatt «Hinweis» mit den fehlenden Daten, Markdown einen Hinweis zuoberst,
  jeder Dateiname den Zusatz `-eingeschraenkt`. Der Export-Dialog erklärt das je Format.

### Neu: Prüfseite erkennt veränderte Dateien

- Ist eine Datei nicht mehr byte-genau das Original (z. B. auf dem Handy neu gespeichert oder mit
  «Drucken als PDF» erzeugt), ordnet die Prüfseite sie über die Dokument-ID zu, statt nur «Nicht
  gefunden» zu melden: «Neu gespeichert – Text unverändert» oder «Verändert: Seite 2, 5 weichen
  ab», dazu eine abweichende Seitenzahl.
- Dafür speichert hocX je Seite einen gesalzenen Fingerabdruck des Texts, nie Text oder PDF. Der
  Browser liest Dokument-ID und Seitentext selbst (pdf.js, nur bei unbekanntem Hash geladen) und
  schickt nur Fingerabdrücke; der Server antwortet je Seite nur mit «stimmt / stimmt nicht».
- «Original» bleibt dem exakten Vergleich vorbehalten. Ohne freigegebene Anzeige der Organisation
  zeigt die Prüfseite bei veränderten Dateien keinen Titel. PDFs von vor dem Update werden nur
  zugeordnet, ohne Seitenvergleich.

### Neu: Dateien als Kacheln mit PDF-Vorschau

- Der Dateien-Tab zeigt Dateien standardmässig als Kacheln mit der ersten PDF-Seite, wahlweise als
  Liste (pro Gerät gemerkt). Ohne Vorschau zeigt die Kachel, ob die Datei noch verarbeitet wird,
  die Verarbeitung fehlgeschlagen ist oder es keine PDF-Ansicht gibt.
- Ein Menü «···» bündelt: PDF öffnen und herunterladen, Originaldatei, Link teilen, Details & Tags,
  Versionen und - bei Fehlern - erneut verarbeiten.
- Hat eine hochgeladene Word-Datei eine automatisch erzeugte PDF-Ansicht, zeigt hocX überall diese:
  Name mit `.pdf`, PDF-Symbol, Öffnen öffnet das PDF. Das Original bleibt über das Menü und die
  Details erreichbar.

### Geändert: Tastenkürzel auf dem Mac

- Auf Mac, iPhone und iPad zeigt hocX Kürzel mit ⌘ (z. B. ⌘K für die Suche), sonst mit Strg/Ctrl.

### Neu: Suche findet einzelne Einstellungen, Rollen, Elemente und Blöcke

- Ctrl+K/⌘K: Das Suchfeld ist sofort aktiv, auch Zeichen, die schon beim Öffnen getippt werden,
  kommen an.
- Neben Menüs, Personen und Dateien findet die Suche jetzt einzelne Einstellungen (z. B.
  «Vereinsname», «Löschfristen», «Tarif je Person») und springt direkt in den Abschnitt bzw.
  Reiter, dazu Rollen (auch Standardrollen über ihren Namen in der eigenen Sprache) und Elemente
  der Bibliothek samt ihrer Blöcke (öffnet Element bzw. Block im Editor). Jede Gruppe erscheint nur
  mit dem Recht, die Zielseite zu öffnen (Elemente: `templates.edit`, Rollen: `access.manage`).

### Neu: Listen mit beliebig vielen Spalten

- Listen haben bis zu 20 Spalten (Text, Person, Personen, Termin) statt zwei fester; Spalten lassen
  sich anlegen, umbenennen, umsortieren und löschen. Die Rolle «Bezeichnung» benennt Einträge (in
  Abgaben, Matrix, Gruppenstatistik), «Verantwortlich» liefert die Personen für Abgaben und
  Aufgaben.
- Tabellenblöcke, Matrix, Protokoll-Editor, Word-Import, Document Studio, Mobile und die Abgabebox
  arbeiten mit allen Spalten; Tabellenblöcke können sichtbare Spalten wählen.

### Neu: Dashboard und Statistik

- Startseite mit Kennzahlen (Anwesenheit im Jahr, offene Pendenzen, offene Bussen), nächster Sitzung,
  «Termine & Fristen» nach Wochen, eigenen Pendenzen, offenen Bussen und Kontoständen – auch mobil.
- Statistik mit Jahresauswahl und Vorjahresvergleich: Anwesenheit pro Monat, Pendenzen
  (Erledigungsquote, überfällig, Ø Tage bis erledigt, offen je Person), Bussen (nach Art,
  bezahlt/offen), Finanzen je Monat und Konto, Gruppen. Bussen erscheinen nur mit Finanzmodul,
  Werte je Person nur mit «Personenbezogene Daten» (sonst nur die eigenen).

### Neu: Personen an einem Ort und MFA-Pflicht

- **Personen an einem Ort:** Personenseite `/participants/<id>` mit Stammdaten, Mitgliedschaft,
  Bussentarif, Login & Rollen (Einladen, Passwort setzen, Rollen, MFA, Login entziehen),
  Datenauskunft und Löschen; Änderungen sammelt eine gemeinsame Leiste «Ungespeicherte
  Änderungen». Die Mitgliederliste ist der einzige Ort zum Anlegen («Neues Mitglied» mit Einladung,
  Rolle und Tarif), zeigt Login, Rollen und Tarif, filtert danach (`?tariff=<id>` vorbelegt) und
  kann mehrere Personen einladen, Rollen hinzufügen/entfernen, Tarif setzen und löschen.
- **Zugriff** (vormals «Logins & Rollen»): Reiter Rollen (Deep-Link `/users/roles?role=<id>`),
  «Wer hat Zugriff» (Übersicht mit Filter «MFA fehlt») und Sicherheit.
- **MFA für alle Logins:** Admins mit «Benutzer & Rollen verwalten» können MFA für alle Logins der
  Organisation verlangen (Migration `0188_tenant_require_mfa`, auditiert). Konten ohne Faktor
  werden abgemeldet (API: 403 `mfa_setup_required`) und beim nächsten Login direkt in die
  Einrichtung geführt.
- **MFA je Rolle:** Im Rollen-Editor «MFA für diese Rolle verlangen» (Migration `0192`).
- **3 Tage Frist:** Wird MFA für ein bestehendes Konto neu Pflicht (Rolle oder Organisation), hat es
  3 Tage Zeit: die Einrichtung erscheint bei jeder Anmeldung mit «Später einrichten», in der App
  erinnert ein Hinweis. Danach ist sie Pflicht. Keine Frist bei Administrationsrechten und für neue
  Konten – die richten den Faktor beim ersten Login ein.

### Neu: Feinere Berechtigungen und Vier-Augen-Prinzip

- Neue Rechte: Protokolle freigeben, eigene Pendenzen erledigen, Personen ansehen /
  Kontaktdaten sehen / Personendaten exportieren (mit MFA), Bussen verwalten, Dateien ansehen,
  Fotos ansehen / verwalten, öffentlich teilen, Abgaben prüfen, Verlauf ansehen.
- **Nur-Lese-Zugang:** Ohne «Eigene Pendenzen erledigen» kann ein Konto nichts mehr ändern.
  Mit dem Recht darf es nur Status und Erledigt-Datum der eigenen Pendenzen setzen.
- **Personen ansehen** ohne Kontaktdaten: E-Mail nur mit «Kontaktdaten sehen», Login und Rollen
  nur für Verwaltende.
- **Dateien und Fotos getrennt:** Wer nur Fotos sehen darf, sieht keine Dokumente und umgekehrt.
- **Vier-Augen-Prinzip** (Zugriff › Sicherheit, je Organisation): Wer ein Protokoll verfasst hat,
  kann es nicht selbst abschliessen; abschliessen braucht «Protokolle freigeben».
- **Zugangslinks:** Freigabelinks für Dateien und Alben lassen sich direkt in der Übersicht
  (Organisation › Zugangslinks) widerrufen.
- **Nachvollziehbar:** Rollen-Zuweisungen stehen mit vorher/nachher im Verlauf – egal ob über
  Zugriff, Konto anlegen oder Mehrfachauswahl; Erstellen, Erneuern und Widerrufen öffentlicher
  Links ebenso.
- **Prüfer je Abgabe:** Im Abgabe-Auftrag lassen sich Prüfer (Personen mit Login) zuweisen. Im
  Rollen-Editor gibt es für «Abgaben ansehen» und «Abgaben prüfen» die Reichweite «Alle» oder «Nur
  zugewiesene»; mit «Nur zugewiesene» sieht und prüft man nur die Aufträge, denen man als Prüfer
  zugewiesen ist (Liste, Dateien, ZIP, Tags, Statistik, Album-Übersicht; automatische Alben fremder
  Aufträge fehlen). «Abgaben verwalten» gilt immer für alle.
- **Abgaben für Leser:** Die Seite Abgaben ist mit «Abgaben ansehen» erreichbar (nur lesen);
  Verwalten braucht weiterhin «Abgaben verwalten», Schliessen/Öffnen «Abgaben prüfen».
- **Rollen-Dialog:** Implizierte Berechtigungen sind automatisch angehakt und ausgegraut, mit dem
  Hinweis «Ergibt sich aus …»; die effektiven Berechtigungen auf der Personenseite zeigen «Nur
  zugewiesene», wo keine Rolle das Recht für alle gibt.
- **Rollen-Vorlagen:** Zugriff › Rollen › «Aus Vorlage» füllt das Formular mit Präsident, Aktuar,
  Kassier, Revisor, Abgabe-Prüfer (Reichweite «Nur zugewiesene») oder Mitglied vor. Gespeichert
  wird eine normale eigene Rolle, nicht mit der Vorlage verknüpft; Rechte, die man selbst nicht hat,
  werden weggelassen und genannt.
- **Ansehen als …:** Auf der Personenseite zeigt eine Vorschau Menüpunkte, Berechtigungen mit
  Reichweite, MFA-Pflicht und sichtbare Abgaben eines Kontos – nur lesend, ohne Sitzung des Kontos,
  nur für Konten ohne mehr Rechte als man selbst, im Verlauf vermerkt.
- **Sichtbarkeit von Dateien** (Organisation › Datenschutz): Abgaben und die Fotogalerie lassen
  sich zusätzlich für alle Teilnehmenden mit Login freigeben, wahlweise nur Bilder – nur zum
  Ansehen, nie zum Ändern oder öffentlich Teilen. Jeder Abgabe-Auftrag kann das überschreiben
  («Wer darf eingereichte Dateien sehen?», auch «nur die eigene Einreichung»). Freigegebene Bilder
  erscheinen unter Ablage › «Fotos aus Abgaben». Protokoll-Dateien folgen immer dem Protokoll.
  Standard: nichts zusätzlich freigegeben. Änderungen stehen mit vorher/nachher im Verlauf.
- **Prüfer «nur zugewiesene»** sehen Dateien aus anderen Abgaben auch in Fotogalerie, Ablage, Suche
  und beim direkten Abruf nicht mehr.
- Für Entwickler: Rechte-Inventar `docs/permissions-inventory.md` und Berechtigungsmatrix
  (`permissions/permission-matrix.json`) werden generiert; ein Laufzeittest ruft jede GET-Route mit
  jeder Standardrolle auf. Abweichungen zum Plan: `docs/permissions-plan-deviations.md`.

### Neu: Pendenzen v2

- Liste nach Fälligkeit gruppiert (Überfällig, Nächste 14 Tage, Später, Bis nächste Sitzung,
  Schliesst mit Abgabe, Ohne Fälligkeit, Erledigt), Filter Alle/Meine und Offen/Erledigt mit
  Zählern, Tags und Suche.
- Board mit einer Spalte je Person; Ziehen weist neu zu (Tastatur: «Zuweisen an …»).
- Kalender mit Pendenzen und Terminen, Seitenleiste «Überfällig» und «Ohne festes Datum».

### Neu: Verlauf mit Filtern in jeder Spalte

- Organisation › Verlauf: Bereich als durchsuchbare Auswahl; Zeitpunkt (von/bis), Vorgang, Person
  und Ergebnis lassen sich direkt im Spaltenkopf filtern, aktive Filter stehen als Chips darüber.

### Geändert: Benutzerlimit zählt offene Einladungen

- Offene Einladungen belegen schon beim Einladen einen Platz im Benutzerlimit des Abos. So scheitert
  niemand erst beim Annehmen; eine zurückgezogene oder abgelaufene Einladung gibt den Platz frei.

### Geändert: Kurzname entfällt, Partnersuche verzeiht Tippfehler

- Der Kurzname der Organisation ist weg (Profil, Plattform-Admin, Teilen-Dialog). Die Suche nach
  Partner-Organisationen beim Album-Teilen läuft über den Namen und ignoriert Gross/klein,
  Umlaute (ä = ae), Satzzeichen und Wortreihenfolge, findet Wortanfänge, Kürzel («JW Sachseln»)
  und einzelne Tippfehler.
- Aufbewahrung: Die Regel «Ehemalige Mitglieder nach dem Austritt deaktivieren» entfällt –
  Ausgetretene sind seit 1.4.0 ab dem Tag nach dem Austritt gesperrt.

### Neu: Erstlogin über die Einladung

- Die Einladung führt durch Passwort, zweiten Faktor (Passkey oder Authenticator-App, mobil mit
  «In Authenticator-App öffnen») und «Alles bereit» – danach ist die Person direkt angemeldet.
- Passwortstärke live; mindestens 12 Zeichen und Stufe «Mittel», Name, E-Mail und häufige Wörter
  zählen als schwach (gilt auch beim Passwort-Reset, serverseitig geprüft).
- Ist MFA Pflicht (Rolle oder Organisation), lässt sich der zweite Faktor nicht überspringen.
- Eigene Seiten für ungültige Einladungen und für zu viele Versuche.

### Geändert: Öffentliche Teilen-Seite

- Neu gestaltet: Kopf mit «Auswählen» und «Alle herunterladen (ZIP)», Kacheln mit echter
  Vorschau (Fotos, erste Dokumentseite) oder Liste, Fotoalben als Masonry, Vollbild-Ansicht mit
  Pfeiltasten und Filmstreifen, Auswahl herunterladen.

### Geändert: Pendenzen aus Abgaben folgen dem Abgabefenster

- Fällig ist eine Abgabe-Pendenz am letzten Tag des Abgabefensters (z. B. 14 Tage nach dem
  Termin) bzw. am Stichtag; ab dann rechnen die Pendenzen-Bussen.
- Läuft das Fenster ab, ohne dass «nach dem Ende offen halten» gesetzt ist, und ist nichts
  eingegangen, wird die Pendenz wie beim Schliessen von Hand abgebrochen (keine weitere Busse).
  Mit «offen halten» bleibt sie offen und überfällig, die Busse läuft weiter.
- Wird die Frist verlängert (oder das Element von Hand wieder geöffnet), geht die Pendenz wieder
  auf – samt Busse, falls eine Regel greift.

### Geändert: Bussen-Regeln neu gestaltet

- Reiter mit Zählern, Übersicht des Bussentarifs mit Warnung, wenn kein Bussenkonto gesetzt ist,
  Tarifkarten mit Betrags-Chips («Standard» für Beträge aus dem Bussentarif), Einstieg ohne Tarife,
  Löschrückfrage mit der Zahl der betroffenen Personen und Betragsfelder mit Währung.
- «Tarif je Person» ist aus den Bussen-Regeln zu den Mitgliedern gezogen (Personenseite und
  Mehrfachauswahl in der Mitgliederliste); jede Tarifkarte verlinkt mit «N Personen →» auf die
  danach gefilterte Mitgliederliste. Mehrere Personen bekommen ihren Tarif in einer Anfrage
  (`PUT /api/todo-fines/tariff-members`, nur Personen der eigenen Organisation).

### Geändert: Admin-Panel und Buttons

- Die Seitenleiste des Admin-Panels hat zuklappbare Abschnitte wie die App.
- Buttons nebeneinander sind überall gleich hoch, Nebenaktionen nie mehr dunkel im hellen Design
  (z. B. «Auswählen» auf geteilten Seiten, «CSV-Import» neben «Neues Mitglied»). Eine Höhe für alle
  Text-Buttons (40 px, Smartphone 44 px); der Design-Checker und ein Browser-Test auf 13 Seiten in
  Hell/Dunkel verhindern Rückfälle.

### Neu: Seitenleiste nach Tätigkeiten

- Gruppen **Sitzungen** (Kalender, Anliegen, Protokolle), **Aufgaben** (Pendenzen, Abgaben),
  **Mitglieder**, **Kasse** (Konten, Bussen), **Ablage** (Listen, Dateien, Fotos, Freigaben) und
  **Auftritt** (Dokumentvorlagen, Erscheinungsbild).
- **Meine Aufgaben** unter Start: die eigenen offenen Pendenzen und Abgaben nach Fälligkeit, mit
  Link auf alle Pendenzen.
- **Einstellungen** gesammelt: Sitzungsvorlagen (mit Bausteinen und Arbeitsjahr, vorher «Zyklen»),
  Aufgabenpakete, Logins & Rollen, Bussen-Regeln, Domains & Echtheit. Auf den Seiten eines
  Bereichs führt ein Zahnrad oben rechts direkt zur passenden Einstellung, von dort ein Link zurück.
- **Organisation** für alles, was den ganzen Mandanten betrifft: Profil, Abo & Nutzung, Datenschutz
  (mit Aufbewahrung), Zugangslinks, Verlauf, Import.
- Die Suche (Ctrl+K) findet Seiten auch unter ihren bisherigen Namen.

### Neu: Fotogalerie mit Zeitstrahl

- Rechts neben den Fotos ein Zeitstrahl mit Jahren, Monaten und der aktuellen Position: Klicken
  oder Ziehen springt direkt zu einem Jahr oder Monat, auch per Tastatur.
- Kein Springen mehr beim Scrollen: Die Galerie kennt die Anzahl Fotos je Tag, bevor sie Bilder
  lädt, und lädt nur die sichtbaren Tage. Die Kacheln in der Datumsansicht sind dafür
  quadratisch; die Bildansicht zeigt weiterhin das ganze Foto. Alben und die Sortierungen nach
  Bewertung behalten das bisherige Raster.

### Neu: Versandprotokoll der E-Mails

- Unter `/admin/notifications` stehen alle E-Mails der letzten 90 Tage: Zeitpunkt, Organisation,
  Empfänger, Art, Ergebnis mit Grund fürs Überspringen, letzter Fehler und Anzahl Versuche -
  filterbar nach Status, durchsuchbar nach Organisation, Name oder E-Mail. Ohne Mailinhalt; jeder
  Abruf wird im Audit-Log festgehalten. Nur für Admin-Owner.

### Geändert

- **Ausgetretene Personen** sind überall ausgeblendet, wo jemand ausgewählt wird (Verantwortliche,
  Bussen, Abgaben, Termine), und unter «Logins & Rollen». In alten Protokollen, Importen und in der
  Mitgliederliste (Filter «Ausgetreten», jetzt auch mobil) bleiben sie sichtbar. Sie zählen nicht
  mehr zum Benutzerlimit, bekommen keine Mails und lassen sich nicht einladen.
- **Begriffe:** «Verein» und Ableitungen (Vereinsexport, Vereinstarif, Vereinsjahr …) heissen jetzt
  Organisation, Gesamtexport, Standardtarif, Arbeitsjahr usw. - in allen Sprachen, Mails, PDF-
  Beispielen und der Dokumentation. Umbenannt sind auch Stammlisten → Listen, Geteilte Links →
  Freigaben und Bussen-Konfiguration → Bussen-Regeln.

### Behoben

- Erinnerungs-Mails: Lagen Erinnerungen in der Warteschlange (Versand noch aus, SMTP-Störung),
  stand dieselbe Aufgabe beim Einschalten als «in 3 Tagen fällig» und «seit gestern überfällig» in
  einer Mail. Erinnerungen mit festem Text gehen nur noch an dem Tag raus, für den der Text stimmt.
- E-Mail-Einstellungen: Ein einmaliger Versandfehler (z. B. `535` direkt nach dem Einrichten) blieb
  als «Letzter Fehler» stehen, obwohl die Wiederholung zugestellt war.
- E-Mails in Apple Mail: «In 3 Tagen», Daten und Adressen erscheinen nicht mehr als blau
  unterstrichene Kalender- bzw. Karten-Links.
- Excel-Exporte scheitern nicht mehr an Steuerzeichen in Eingaben (#46).
- Protokolleditor: geschlossene Schnellmenü-Flyouts sind nicht mehr per Tab erreichbar (#48), der
  Hinweis auf ein ähnliches Bild erscheint in der UI-Sprache (#49), Termindetails in der
  Terminübersicht sind per Tastatur erreichbar (#50), Sitzungsnotizen sind mobil im
  abgeschlossenen Protokoll schreibgeschützt (#51), «heute» ist das lokale Datum statt UTC (#52)
  und Fehler erscheinen als Fehler-Toast statt als Info (#53).

### Sicherheit und Datenschutz (Nachtläufe 16.–18.11.)

- **Mandantentrennung:** Kalender-Abo und persönlicher Abgabe-Link binden die Sitzung nach der
  Token-Prüfung an ihren Mandanten (Row-Level-Security). Die Abgabebox-Rolle sieht über
  Speicherfunktionen keine fremden Mandanten mehr (`0183`). Fremde Bussen- und Pendenzenblock-IDs
  antworten wie unbekannte (kein Existenz-Orakel).
- **Rechte:** Die Anwesenheitsmatrix im Document Studio zeigt ohne «Persönliche Auswertungen» nur
  die eigene Zeile; das Dashboard zeigt Mitgliedern ohne Entwurfsrecht keine Sitzungsnotizen
  geplanter Sitzungen; die Bildquelle im Document Studio braucht Datei- oder Entwurfsrecht; die
  Exportliste zeigt Lesern keine Exporte von Protokollentwürfen; der Word-Import legt neue
  Personen nur mit «Mitglieder verwalten» an.
- **Fotos:** GPS und Metadaten werden auch aus HEIC/HEIF entfernt (auch ohne «Exif»-Kennung und
  aus der Abgabebox); Partner sehen in geteilten Alben keine Titel, Tags und Herkunft des
  Besitzers; Fotos eines Partners verlassen Album und öffentliche Links mit dem Ende der Freigabe.
- **Exporte:** CSV- und Excel-Exporte speichern Zellinhalte nie als Formel (Formel-Injection).
- **Fehlerprotokoll:** Zugangstoken in Pfaden (Kalender-Abo, Freigabe-Link) werden maskiert.

### Sicherheit und Abhängigkeiten

- next 16.4.3 → 16.4.5 (GHSA-mfr8-8qww-v76h, GHSA-vc7v-qv4w-wrv8) (#44), vitest 5.1.0 (#45),
  SQLAlchemy 2.1.8 (#47), starlette ≥ 1.10 (#30, #32), httpx2 ≥ 2.16 (nur Tests, #31), Traefik
  3.7.18 und ClamAV (#38, ohne den Major-Sprung auf Redis 8), GitHub Actions login/cosign (#22).
- `npm audit` blockiert weiterhin ab «high»; picomatch GHSA-fc5q-39xc-vjpf (nur in
  Entwicklungswerkzeugen, noch kein Fix) ist bis 18.12. begründet ausgenommen
  (`.github/npm-audit-allowlist.json`).

## [1.3.0] - 2026-11-16

Konto und Sicherheit per E-Mail («Passwort vergessen», Einladung, Sicherheitshinweise), globale
Suche (Ctrl+K), ein persönlicher Abgabe-Link für Verantwortliche, Abgaben, die abgeschlossen oder
nach dem Enddatum offen gehalten werden, eine Bussenliste mit eigener Konfiguration, eine Währung je
Verein, Zugangslinks im Überblick, Hilfe und Doku in allen Bereichen sowie ein neues Mail-Design.
Enthält die nie einzeln veröffentlichte Version 1.2.6. Zwölf neue Migrationen, keine neuen Secrets,
eine neue optionale Umgebungsvariable (`TRAEFIK_DOCS_DOMAIN`), keine Breaking Changes.

### Update

- Von **1.2.5**: `./scripts/deploy.sh <test|prod>`. Vor dem Update legt `deploy.sh` ein
  Offsite-Backup an, wenn das Borg-Backup eingerichtet ist. Von älteren Ständen gelten zusätzlich
  die Hinweise von 1.2.5 und 1.2.4.
- Migrationen `0171_account_tokens`,
  `0172_fine_tariff_attendance` und `0173_submission_keep_open` legen nur eine neue Tabelle und
  Spalten mit Standardwerten an und lassen sich zurückrollen. `0174_umlaut_session_label` ersetzt
  den gespeicherten Titel «Naechste Sitzung» durch «Nächste Sitzung» (Vorlagen und nicht
  abgeschlossene Protokolle; abgeschlossene bleiben unverändert).
- «Passwort vergessen» und «Per E-Mail einladen» erscheinen erst, wenn der E-Mail-Versand unter
  `/admin/notifications` eingerichtet ist. Für die Links in den Mails muss die Basis-URL stimmen
  («Basis-URL für Links», sonst `https://<TRAEFIK_DOMAIN>`).
- Migrationen `0175`–`0182`: `0175_submission_clean_files` erledigt Abgabe-Pendenzen erst mit
  geprüften Dateien, `0176_list_group_source` markiert bestehende Listen «Gruppen» als Quelle der
  Gruppenstatistik (Statistik unverändert), `0177_todo_fine_evaluated` und
  `0179_domain_pending_replacement` ergänzen Spalten bzw. Regeln, `0180_tenant_finance_currency`
  übernimmt je Verein die häufigste Kontowährung (nur Bezeichnung, keine Umrechnung),
  `0181_submission_owner_access` und `0182_submission_completion` legen den persönlichen
  Abgabe-Link (Standard «aus» für bestehende Abgaben) und den Abschluss von Abgaben an.
  `0178_event_cycle_backfill` trägt Zyklus-Zuordnungen für Termine ganz ohne Zuordnung nach; ein
  Rückrollen entfernt diese Zuordnungen nicht wieder.
- `TRAEFIK_DOCS_DOMAIN` (optional, bereits in `.env.prod.example`): Domain der Doku-Seite für die
  Hilfe-Links in der App; leer = keine Links.
- Release-Ablauf: Die Version kommt jetzt aus diesem Changelog. «Promote tested release images»
  fragt keinen `release_tag` mehr ab, sondern liest die Version aus dem obersten
  Versionsabschnitt des getesteten Commits und prüft, dass jedes Image dieselbe Version als Label
  trägt (siehe RUNBOOK Abschnitt 3).

### Neu: Konto und Sicherheit per E-Mail

- **Passwort vergessen:** Auf der Anmeldeseite fordert man einen Link an (60 Minuten gültig,
  einmal verwendbar). Die Antwort verrät nicht, ob es das Konto gibt. Das neue Passwort beendet
  alle Sitzungen; ein eingerichteter zweiter Faktor bleibt und wird weiter verlangt.
- **Einladung per E-Mail:** Im Personen-Dialog lädt die Verwaltung (`access.manage`) eine Person
  ohne Login ein, statt ihr ein Passwort zu setzen. Die Person legt ihr Passwort selbst fest; der
  Login wird erst dann aktiv (Benutzerlimit und E-Mail werden dabei erneut geprüft). Offene
  Einladungen sind in der Liste markiert und lassen sich erneut senden oder zurückziehen. Der
  Link ist 7 Tage gültig.
- Links stehen nur im URL-Fragment der Mail; gespeichert wird nur ein Hash. Öffentliche Endpunkte
  mit Rate-Limit, Einträge im Audit-Log, im Datenschutz-Export Zweck und Zeitpunkte der Links.
- **Sicherheitshinweise** (immer, nicht abbestellbar): Passwort geändert, auch durch die
  Verwaltung, sowie zweiter Faktor hinzugefügt oder entfernt.
- **Datenexport fertig:** Mail an die Person, die den Vereins-Datenexport bestellt hat, sobald er
  bereitliegt oder fehlgeschlagen ist (im Profil abschaltbar).
- Migration `0171_account_tokens`.

### Neu: Eine Bussenliste und Bussen-Konfiguration

- **Alle Bussen in einer Liste** unter Finanzen > Bussen: Verspätung und Absenz aus den
  Protokollen sowie Pendenzen-Bussen (laufend, strittig, fixiert) mit ihren Aktionen
  (einkassieren, erlassen, wieder öffnen, Konflikt zuweisen), auch in der mobilen Ansicht. Der
  eigene Reiter «Pendenzen-Bussen» entfällt, alte Links leiten auf die Liste um.
- **Bussen-Konfiguration** als eigener Eintrag unter Konfiguration (mit `finances.read`, ändern
  mit `finances.manage`): Vereinstarif für Verspätung und Absenz (Konto, Beträge; bisher in der
  Bussenliste), Tarife mit Personenzuordnung und die Pendenzen-Regeln.
- **Tarife auch für Anwesenheitsbussen:** Jeder Tarif kann eigene Beträge für Verspätung und
  Absenz haben (leer = Vereinstarif). Die Busse im Protokoll richtet sich nach dem Tarif der
  Person; den Betrag bestimmt der Server, die Tarife einzelner Personen gelangen nicht in den
  Browser. Ergibt der Tarif 0, entsteht keine Busse. Eine Protokollvorlage mit eigenem Tarif gilt
  weiterhin für alle gleich. Die Tarife
  brauchen dafür nur noch das Feature `finance`, nicht mehr `todo_fines`.
- **Neuer Regel-Dialog** (Design «Bussenregel Dialog»): Abschnitte «Für welche Pendenzen?» mit
  Filter-Chips und Zusammenfassung und «Wie wird gebüsst?» mit Zuschlag-Stepper, Konto,
  Umschalter für mehrere Verantwortliche und Beträgen je Tarif samt Vorschau nach 1, 3, 7 und 14
  Tagen; «Regel aktiv» als Schalter unten.
- **Neue Tarif-Ansicht** (Design «Pendenzen-Bussen Tarife»): Karten je Tarif mit Anzahl Personen
  (Standardtarif inkl. Personen ohne eigenen Tarif), «Tarif je Person» mit Filter-Chips,
  Umschalter je Person und Mehrfachauswahl («Tarif setzen» für alle ausgewählten).
- Migration `0172_fine_tariff_attendance`.

### Neu: Abgaben nach dem Enddatum offen halten

- Neue Option in der Abgabe: **«Nach dem Enddatum offen halten»**. Das Abgabefeld schliesst dann
  nicht mehr am Ende des Zeitfensters bzw. am Stichtag, sondern erst nach den normalen Regeln
  (automatisch nach der ersten Abgabe bzw. bei maximaler Dateizahl, oder von Hand). Die Pendenz
  bleibt am Enddatum fällig und wird danach überfällig (Pendenzen-Bussen laufen wie gewohnt).
- Die Pendenz einer Abgabe war schon bisher am Enddatum der Abgabe fällig (Termin-Abgaben:
  letzter Tag des Termins plus «Tage danach», Listen- und Einzelabgaben: Stichtag).
- Migration `0173_submission_keep_open`.

### Hinzugefügt

- **Alben verwalten.** Alben lassen sich umbenennen und löschen (die Fotos bleiben erhalten),
  Fotos lassen sich aus einem Album nehmen, ohne sie zu löschen.
- **Pendenzen** zeigen in der Liste (auch mobil) den Hinweis «Busse läuft»; neue Bussenregeln
  lassen sich aus Vorlagen anlegen, Filter und Konto stehen unter «Erweitert». In der Oberfläche
  heisst es einheitlich «Pendenz».
- **Sicherheitshinweis** an die bisherige Adresse, wenn die Login-E-Mail geändert wird.
- **Passwort ändern** im Profil unter «Sicherheit»; andere Sitzungen enden, die aktuelle bleibt.
- **Finanzen:** Jahressicht mit Einnahmen, Ausgaben, Anfangs- und Endsaldo und «Exportieren».
- **Stammlisten:** Eine Liste lässt sich als Quelle der Gruppenstatistik markieren; die Statistik
  hängt nicht mehr am Listennamen «Gruppen».
- **Hilfe und Doku in allen Bereichen.** Neue Anleitungen zu Bussen, Aufgabenpaketen,
  Benachrichtigungen, Konto, Fotos und Alben, Statistik und Dashboard, Zyklen sowie Einstellungen
  und Domains; Protokolle, Termine, Mitglieder, Finanzen und Stammlisten neu geschrieben. «?»-Hilfen
  und Doku-Links in Protokollen, Terminen, Bussen, Finanzen, Mitgliedern, Fotos, Listen, Anliegen,
  Statistik, Document Studio und Einstellungen.
- **Mail «Abgabe eingegangen».** Erledigt eine Einreichung in der Abgabebox eine Abgabe-Aufgabe,
  bekommen alle Verantwortlichen der Aufgabe eine Mail (mehrere Abgaben kurz nacheinander in einer
  Mail). Abschaltbar im Profil unter «Benachrichtigungen» («Abgabe eingegangen», Standard ein). Von
  Hand erledigte Aufgaben lösen keine Mail aus. Beim ersten Lauf nach dem Update werden Abgaben der
  letzten 24 Stunden noch gemeldet.
- **Abgaben einfacher einrichten.** Vorlagen zum Schnellstart («Berichte pro Termin», «Formular
  bis Stichtag», «Fotos nach Anlass»), selten gebrauchte Einstellungen unter «Erweitert», ein
  Beispiel mit echtem Datum zum Zeitfenster, ein Hinweis neben dem gesperrten «Speichern», was
  noch fehlt, und nach dem Anlegen ein Fenster mit dem Link zum Kopieren. Der Link steht auch in
  der Detailansicht. Auf dem Handy stehen Zusammenfassung und Link oben.
- **Hilfe im Formular.** Kleine «?»-Knöpfe erklären Quelle, Zeitfenster, Stichtag, Zyklus,
  Dateien, automatisches Schliessen, Verantwortliche und Links und führen zum passenden Abschnitt
  der neu geschriebenen Anleitung «Abgabebox». Der Link braucht `TRAEFIK_DOCS_DOMAIN` (bereits
  vorhanden, wird neu auch ans Frontend gegeben); ohne Wert erscheinen keine Doku-Links.
- **Abgabebox:** Fortschrittsbalken beim Hochladen, die Beschreibung der Abgabe auch auf der
  Upload-Seite, bei nur einem Dokument direkt das Upload-Formular und eine genauere Meldung bei
  nicht erlaubten Dateitypen.

### Geändert

- **Begriffe:** «Mitglieder» und «Logins & Rollen» sind klar getrennt; in der Login-Liste wird nur
  noch der Login entzogen. Logins werden standardmässig per E-Mail-Einladung vergeben.
- Termine sind mit reinem Leserecht als Leseansicht sichtbar; Sitzungen mit Uhrzeit erscheinen im
  Kalender-Abo mit Uhrzeit.
- Plan-Änderungen gelten sofort für alle Organisationen auf dem Plan; «Abo & Nutzung» zeigt Module
  im Zustand «Nur lesen».
- **Eine Währung je Verein.** Die Währung der Konten und Bussen wird unter *Mandant-Einstellungen →
  Allgemein → Finanzen* gesetzt und gilt für alle Konten; das Feld «Währungsbezeichnung» je Konto
  entfällt. Migration `0180_tenant_finance_currency` übernimmt je Verein die häufigste
  Kontowährung und gleicht alle Konten daran an (nur die Bezeichnung, keine Umrechnung). Die
  Anwesenheitsbusse im Protokoll zeigt die Vereinswährung statt fest «CHF».
- **CSV- und Excel-Exporte aus dem Document Studio sind standardmässig verschlüsselt.** Sie
  enthalten Personendaten und kommen als Excel-Datei mit Passwort (Office-Verschlüsselung, AES;
  Passwort im Export-Dialog, mindestens 12 Zeichen) – auch bei CSV. Excel, Numbers und LibreOffice
  öffnen sie ohne Zusatzsoftware. Wahlweise gibt es eine AES-256-ZIP-Datei, in der CSV eine
  CSV-Datei bleibt (braucht 7-Zip, Keka oder WinRAR; `encryption: "zip"`). Die Verschlüsselung
  lässt sich im Dialog bewusst abwählen
  (auditiert als `encrypted: false`, Ausnahme in SECURITY-RULES §4.4). Kalender (ICS, ohne
  Personendaten) und Text (nur Zwischenablage) bleiben unverschlüsselt. `POST /api/documents/export`
  verlangt für `csv`/`xlsx` das Feld `password` oder `encrypt: false`. Neue Abhängigkeit
  `msoffcrypto-tool` (mit `olefile`).
- **Bussenliste nur mit Finanzzugriff.** Den Baustein «Bussenliste» anlegen, seine Bussen-Einstellungen
  ändern oder ihn aus der Bibliothek in eine Vorlage einfügen geht nur mit «Kassenbuch ansehen»
  (`finances.read`), sonst 403 `fine_list_requires_finance`. Titel, Darstellung und Entfernen bleiben
  mit «Vorlagen bearbeiten» möglich.
- **Von Hand geschlossene Abgabefelder zählen als erledigt.** Der Fortschrittsbalken zeigt sie
  als eigenes Segment («4 von 5 erledigt · 1 geschlossen»). Die Aufgabe des Elements wird beim
  Schliessen ohne geprüfte Datei «abgebrochen» (keine Verspätungsbusse), mit Datei bleibt sie
  «erledigt»; eine von Hand erledigte oder abgebrochene Aufgabe bleibt unverändert. Wiederöffnen
  öffnet eine abgebrochene Aufgabe wieder. Bereits geschlossene Elemente gleicht der Abgleich-Job nach dem
  Update nach.

### Behoben

- Protokoll, Rad-Effekt bzw. Akkordeon: Beim Scrollen mit dem Mausrad sprang der Editor zurück
  und öffnete immer wieder denselben Punkt, statt zum nächsten zu wechseln (vor allem bei Punkten
  mit Bildern). Ursache: das Ende des Verankerungssprungs beendete die Pause des Mitlesens zu früh,
  bevor der neue Punkt in Position war. Jetzt zählt das Ende erst, wenn das Ziel erreicht ist.
  Geprüft mit Mausrad (einzeln, schnell, mit Schwung) und Touchpad, mit und ohne Rad-Effekt, in
  Protokollen mit 2, 6 und 22 Punkten.
- **Umlaute überall:** Sichtbare Texte mit «ae/oe/ue» statt Umlaut korrigiert, u. a. «Nächste
  Sitzung» (Editor und PDF), «nächste Sitzung» als Fälligkeit, «Verspätet», Meldungen beim
  Löschen von Listen, Abgaben und Einträgen, Fehlermeldungen der Abgaben und der Abgabebox sowie
  die Demodaten. Technisch bedingt bleibt nur der ASCII-Kommentar in exportierten Bildern (EXIF).
- Abgabebox: Bei mehrtägigen Terminen schloss das Abgabefeld schon «Tage danach» nach dem
  *ersten* Tag des Termins, die Pendenz war aber erst nach dem *letzten* Tag fällig. Beide rechnen
  jetzt ab dem letzten Tag.
- **Pendenzen-Bussen.** Nachträgliches Bearbeiten einer erledigten Pendenz verschiebt das
  Erledigungsdatum nicht mehr und löst keine falsche Busse mehr aus. Eingefrorene Bussen bleiben
  bestehen, auch beim Wiedereröffnen, Verschieben oder Löschen der Pendenz; ändern oder erlassen
  kann sie nur, wer Finanzen verwaltet (mit Audit-Eintrag). Die gebüsste Person kann ihre laufende
  Busse nicht mehr durch Verschieben, Umverteilen, Abbrechen oder Löschen loswerden. Abgabe-
  Pendenzen werden auch nach längerem Ausfall des Abgleichs korrekt bewertet.
- **Protokoll abschliessen** fragt nach und erklärt die Folgen; vorher wird alles noch Getippte
  gespeichert, der letzte Satz fehlt nicht mehr im PDF. Abgeschlossene Protokolle lassen sich nicht
  mehr umbenennen oder umdatieren, lokale Entwürfe überschreiben keine neuere fremde Fassung.
- **Termin-Formular** speichert nicht mehr bei jedem Tastendruck, sondern nach einer kurzen Pause,
  der Reihe nach und mit Statusanzeige; beim Schliessen geht nichts verloren. Per CSV importierte
  Termine und neue Zyklen ordnen Termine dem Zyklus zu, fehlende Zuordnungen werden nachgetragen.
  Der Löschdialog nennt die mitgelöschten Abgabe-Einreichungen und Dateien.
- **Datenschutz:** Bussen-Exporte im Document Studio enthalten ohne «Personenbezogene Daten aller»
  nur noch die eigenen Bussen. Pendenzen-Routen antworten bei fremden Pendenzen mit 404.
- **Finanzen:** Buchungen aus Pendenzen-Bussen sind gesperrt (Schloss mit Erklärung). Nach einem
  Abo-Downgrade bleiben die Bussen lesbar. Das Dashboard summiert offene Bussen korrekt je Währung.
- **Domains:** Eine neue eigene Domain ersetzt die laufende erst nach erfolgreicher DNS-Prüfung; ein
  Tippfehler legt die Vereinsadresse nicht mehr lahm. Prüfen und Löschen haben eigene Kontingente.
- **Mitglieder:** «E-Mail-Benachrichtigungen ohne Login» bleibt beim Speichern durch Admins
  erhalten. Der CSV-Import erkennt Duplikate über alle Mitglieder (auch per E-Mail).
- **Fotos:** «Löschen» nimmt Fotos, die nicht gelöscht werden dürfen, nicht mehr still aus Alben.
  Fehler beim Galerie-Upload landen im Fehlerprotokoll statt als Rohtext beim Benutzer.
- «Rückgängig» bei einer einkassierten Busse fragt nach, weil die Buchung gelöscht wird.
- **Systemalarme** gehen bei einem ntfy-Ausfall nicht mehr verloren und werden nachgesendet;
  fehlschlagende Systemprüfungen und Fehler der PDF-Aufträge werden gemeldet.
- **Schweizer Zeit:** «Heute» gilt in Terminen, Anliegen, Statistik, Protokollen, Finanzen und
  Document Studio nach Schweizer Datum statt UTC.
- **Statistik:** Bussenarten in der gewählten Sprache, Diagramme in der Kontowährung, «Protokolle»
  zählt nur durchgeführte und abgeschlossene; Leser mit zugewiesenen Vorlagen sehen nur deren Zahlen.
- **Verspätungsbussen bei Abgaben über die Abgabebox.** Eine Einreichung erledigte die Pendenz
  in der Datenbank ohne die Pendenzen-Busse festzuschreiben. Der Abgleich-Job friert sie jetzt für
  Abschlüsse der letzten zwei Tage nach (fehlende ältere werden bewusst nicht nachgerechnet).
- **Dateien im Virenscan erledigten die Pendenz.** Erst eine sauber geprüfte Datei erledigt sie
  (Migration `0175_submission_clean_files`); was der erneute Scan freigibt, erledigt der Scan bzw.
  der Abgleich-Job, inklusive Busse und Mail. Erledigt-Zeitpunkt ist die Einreichung.
- **«Alle Dateien (.zip)»** enthielt nur die Dateien der letzten Einreichung und nach dem
  Schliessen gar nichts; jetzt alle geprüften Dateien aller Einreichungen und der in der App
  verknüpften, ein Ordner je Abgabefeld.
- **Schliessen/Wiederöffnen** mit einer fremden oder unbekannten Element-Referenz legte erst eine
  Zeile an und endete dann mit Serverfehler; jetzt 400 ohne Änderung.
- **Schliessen während eines Uploads**: Ein laufender Upload konnte ein eben geschlossenes
  Abgabefeld wieder öffnen. Beide laufen jetzt unter einem gemeinsamen Lock je Abgabe; die
  Abgabebox prüft das Schliessen von Hand nicht mehr nur bei automatischem Schliessen.
- **Höchstzahl Dateien**: Die Abgabebox zählt in der App verknüpfte Dateien jetzt mit, wie die App.
- **Fortschritt** zählt jedes Abgabefeld nur einmal und nur, wenn es noch zur Abgabe gehört
  (nie mehr als 100 %). Die Abgaben-Liste lädt ihn in einer Anfrage
  (`GET /api/submission-assignments/summaries`) statt einer je Abgabe.
- Ein Fehler beim Nachtragen der Mails «Abgabe eingegangen» hielt den ganzen Mailversand an.
- Datumsangaben im Abgabefeld-Fenster formatiert, uneinheitliche Begriffe (Abgabefeld, Stichtag,
  Einzelabgabe) und fehlende Mehrzahlformen vereinheitlicht, Dauer-Animationen respektieren
  «Bewegung reduzieren».
- **«Nächste Sitzung» im Folgeprotokoll** verschiebt nicht mehr die eigene Sitzung: Setzt ein
  Folgeprotokoll die übernächste Sitzung, entsteht ein neuer Termin, statt dass der Termin des
  Folgeprotokolls (samt Kalender-Abo und Pendenzen «bis nächste Sitzung») wandert. Das Datum ist im
  Folgeprotokoll nicht mehr mit dem eigenen Datum vorbelegt. Ändert man den Block in einem älteren
  Protokoll, nachdem schon ein späteres derselben Vorlage existiert, bleiben die Termine unverändert
  (die Änderung gilt nur für dieses Protokoll und sein PDF); speichert ein Folgeprotokoll den Block
  ohne Datum, behalten offene Pendenzen «bis nächste Sitzung» ihr Datum.
- **Tag umbenennen** zieht Aufgabenpakete («pro Termin») und den Fälligkeits-Tag der Vorlagen mit.
- **Listen:** Die Terminauswahl lädt alle Termine statt nur die 100 neusten.
- **Zyklusjahr im Frontend** bei einem Stichtag, den es im Jahr nicht gibt (z. B. 29.02.), wie im
  Backend (letzter Tag des Monats).

## [1.2.5] - 2026-11-11

Zwei neue Bereiche: Pendenzen-Bussen als eigenes, buchbares Modul unter Finanzen und
E-Mail-Benachrichtigungen für Aufgaben (Sammelmails für neue Aufgaben und Erinnerungen). Dazu als
Hotfix: Felder aus dem Termin erscheinen wieder im PDF. Zwei neue Migrationen, keine neuen Secrets
oder Umgebungsvariablen, keine Breaking Changes.

### Update

- Von **1.2.4**: `./scripts/deploy.sh <test|prod>`. Von älteren Ständen gelten die Hinweise
  von 1.2.4 (und das Upgrade-Tor `0168_s3_only`).
- Migrationen `0169_todo_fines` und `0170_notifications` legen nur neue Tabellen und Spalten mit
  Standardwerten an (bestehende Daten werden nicht umgeschrieben) und lassen sich zurückrollen.
- Nach dem Update ist nichts automatisch aktiv: Das Modul `todo_fines` ist für bestehende
  Mandanten aus, der Mailversand bleibt aus, bis er unter `/admin/notifications` mit SMTP
  eingerichtet und eingeschaltet wird. Bis dahin vorgemerkte Benachrichtigungen verfallen nach
  7 Tagen. Erinnerungen gelten nur für Aufgaben, die genau in 3 Tagen fällig oder seit gestern
  überfällig sind; alte überfällige Aufgaben lösen beim Einschalten keine Mailflut aus.
- Der job-worker übernimmt zwei neue Hintergrundjobs (`notification_dispatch`,
  `todo_reminders`); für den SMTP-Versand muss der Server ausgehend den konfigurierten
  SMTP-Port erreichen.

### Neu: Pendenzen-Bussen (eigenes Modul `todo_fines`)

- Bussen für Pendenzen, die zu spät erledigt werden. Das Modul ist ein eigenes buchbares
  Feature (Modul Finanzen, braucht `finance`). Die Plattform-Administration schaltet es je
  Mandant im Feature-Tab ein oder aus. Bei bestehenden Mandanten ist es aus. Ausgeschaltet
  bleibt alles lesbar, es entstehen aber keine neuen Bussen.
- **Regeln** wirken per Filter automatisch: Tags, Aufgabenpakete, Verantwortliche und Rollen.
  Jede Regel hat einen Grundbetrag und einen Zusatz pro N Tage Verspätung (pro Tag, alle 2 Tage
  usw.), dazu ein Startdatum, ein Konto und eine Einstellung für mehrere Verantwortliche: jede
  Person zahlt voll, oder der Betrag wird aufgeteilt.
- **Tarife** (z. B. Lernende, Nicht-Verdiener, Vollverdiener) werden je Person eingetragen.
  Jede Regel hat pro Tarif eigene Beträge. Personen ohne Tarif zahlen nach dem Standardtarif.
- Am Todo legt die Kasse die Busse von Hand fest: automatisch, eine bestimmte Regel, ein fixer
  Betrag oder keine Busse. Passen mehrere Regeln, zeigen Todo-Popup und Bussenliste eine Warnung,
  und die Busse muss von Hand zugewiesen werden.
- Solange ein Todo offen ist, läuft die Busse und wächst. Beim Erledigen (auch automatisch über
  die Abgabebox) wird der Betrag je Person fixiert und kann einkassiert (Buchung aufs Konto) oder
  mit Begründung erlassen werden. Wird das Todo wieder geöffnet, verschwinden die offenen
  fixierten Bussen.
- Neue Seite «Pendenzen-Bussen» unter Finanzen mit den Bereichen Bussen, Regeln und Tarife.
  Ohne `reports.personal` sieht man nur die eigenen Bussen. Den Tarif je Person sieht nur, wer
  `finances.manage` hat.
- Mandanten-Export, -Import und -Klon übernehmen Tarife, Regeln und Bussen. Der
  Datenschutz-Export enthält die eigenen Bussen und den Tarif der Person, der Datenexport des
  Mandanten ein eigenes Blatt.
- Migration `0169_todo_fines`.

### Neu: E-Mail-Benachrichtigungen

- Zentraler Weg für Benachrichtigungen an Personen (`backend/app/notifications/`, Doku
  `docs/NOTIFICATIONS.md`). Zuerst nur E-Mail über SMTP. Die Konfiguration liegt unter
  `/admin/notifications` (Passwort verschlüsselt, Test-Mail, Anzeige von Warteschlange und Fehlern).
- Neue Aufgaben als Sammelmail: Aufgaben aus einem Protokoll erst beim Abschluss des Protokolls,
  Aufgaben ohne Protokoll (auch aus Aufgabenpaketen und der Abgabebox) beim Erstellen. Wer sich
  selbst eine Aufgabe gibt, bekommt keine Mail.
- Erinnerungen als tägliche Sammelmail ab 07:00: «fällig in 3 Tagen» und «seit gestern
  überfällig», je Aufgabe nur einmal.
- Im Profil (Reiter «Benachrichtigungen») schaltet jede Person beide Arten ein oder aus.
  Personen ohne Login bekommen nur Mails, wenn ein Admin das im Personen-Dialog einschaltet.
- Neue Hintergrundjobs `notification_dispatch` und `todo_reminders` (job-worker). Der
  Datenschutz-Export enthält das Versandprotokoll (90 Tage aufbewahrt).
- Migration `0170_notifications`.

### Behoben

- **PDF: Felder aus dem Termin fehlten.** In Formularblöcken «Pro Termin» kamen die mit dem
  Termin verknüpften Felder («aus Termin» im Editor, z. B. Organisatoren, Leitungsteam,
  Teilnehmende, Spezialfelder) nicht ins PDF, nur die eingetippten Zeilen. Jetzt stehen sie wie im
  Editor vor den übrigen Zeilen, mit dem Namen aus dem Block bzw. dem Alias der Spezialfelder;
  leere und ausgeblendete Felder fehlen weiterhin. Gilt für neu erzeugte PDFs.
- Fotos, «Ähnliche»: Wer direkt nach dem Laden ein weiteres Bild zum Behalten anhakte, verlor
  diese Auswahl unter Umständen wieder, und «Auswahl löschen» hätte auch dieses Bild gelöscht.
  Das beste Bild gilt jetzt auch in diesem Moment als behalten, der Haken bleibt stehen.

## [1.2.4] - 2026-11-11

Rückmeldungen aus dem Testbetrieb von 1.2.3: flüssigeres Scrollen im Protokoll mit einem neuen
Rad-Effekt, eine Ladeanimation beim Öffnen von PDFs, klickbare Links und mehrere Korrekturen am
PDF (Abstände zwischen Traktanden, entfernte Termine). Dazu Lehren aus dem Deploy von 1.2.3:
`deploy.sh` aktualisiert sich vor jedem Lauf selbst, und das Upgrade-Tor prüft die Schreibrechte
im Dateispeicher. Neu sichert ein Integritäts-Audit, dass Editor und PDF übereinstimmen (nichts
fehlt, nichts zu viel); der Editor markiert, was nicht ins PDF kommt. Die PDF-Erzeugung braucht
unabhängig von der Länge des Protokolls gleich viele Datenbankabfragen, und die CI prüft
Bundle-Grössen und Abfragezahlen. Keine neuen Migrationen, keine Breaking Changes.

### Update

- Von **1.2.3** wie gewohnt: `./scripts/update_deploy_code.sh --deploy` (der Code von 1.2.3
  aktualisiert sich noch nicht selbst). Ab 1.2.4 reicht `./scripts/deploy.sh <test|prod>`.
- Von **1.2.0 bis 1.2.2** gelten dieselben Voraussetzungen wie für 1.2.3 (abgeschlossene
  Erstmigration auf S3, siehe dort); das Upgrade-Tor `0168_s3_only` prüft das weiterhin.
- Nach dem Update sehen neu erzeugte PDFs anders aus, wo «Abstand vor Abschnitten» bisher
  ignoriert wurde (siehe «Behoben»); bereits erstellte PDFs bleiben unverändert.

### Hinzugefügt

- **hocX als App installieren (PWA), ohne App Store.** iPhone/iPad: in Safari «Teilen» →
  «Zum Home-Bildschirm»; Android und Desktop-Chrome/Edge: «App installieren». Auf iPhone, iPad
  und Android schlägt hocX die Installation selbst vor (Android mit dem Installationsdialog des
  Browsers, iOS mit kurzer Anleitung; nach «Schliessen» 30 Tage Ruhe, nie im Protokoll-Editor).
  hocX startet dann mit eigenem Icon im Vollbild, Updates kommen mit jedem Deploy. Bewusst ohne Service Worker:
  keine Protokolldaten im Gerätespeicher. In der installierten App muss man sich einmal neu
  anmelden (iOS trennt die Anmeldung von Safari).
- **Protokoll: «Nicht im PDF».** Hat ein Punkt oder Baustein Inhalt, der nicht im PDF erscheint,
  markiert der Editor das dezent; der Grund steht im Tooltip (in der Sitzungsvorlage vom Export
  ausgenommen, Sitzungsnotizen, von der PDF-Vorlage weggelassen, Bild noch im Virenscan).
  Grundlage ist dieselbe Prüfung wie beim Export (`GET /api/protocols/{id}/pdf-coverage`).
- **CI: PDF-Integrität.** Bei jeder Änderung an Editor oder PDF-Erzeugung prüft ein eigener
  Workflow, dass jede Zeile aus dem Editor im gerenderten PDF ankommt: das Markdown des
  Rich-Text-Editors wird gegen einen Korpus geprüft, den das Backend echt als PDF rendert und
  im PDF-Text wiederfinden muss. Ebenso geprüft wird, dass nichts zu viel im PDF steht: im
  Editor weggefilterte Termine, entfernte oder ausgeschlossene Inhalte; Aufgaben im PDF sind
  genau die des Editors. Editor und PDF filtern Termine über einen gemeinsamen Prüfkatalog.
- **CI: Performance-Audit (nur Erkennung).** Grössenbudget für JS und CSS je Route nach dem
  Frontend-Build (`frontend/bundle-budget.json`) und ein Abfragebudget für die wichtigsten
  Endpunkte (`backend/tests/query_budget.json`, gemessen bei 1 und 20 Einträgen). Mehr als
  erlaubt lässt die CI scheitern.

### Geändert

- **PDF-Erzeugung mit fester Zahl Datenbankabfragen.** Blöcke, Texte, Aufgaben und Bilder eines
  Protokolls und die Termine des Mandanten werden je Export gesammelt geladen statt je
  Traktandum und Block: ein Protokoll mit 20 Traktanden braucht für den Inhalt 13 statt 147
  Abfragen, die Markierung «Nicht im PDF» 44 statt 314. Das PDF selbst bleibt unverändert.
- **Protokoll: neuer Rad-Effekt.** Statt bei jedem Scroll-Bild zu rechnen, liegen die
  eingeklappten Punkte wie auf einer Walze um den aktiven Punkt und drehen beim Wechsel
  flüssig weiter (CSS-Animation auf der Grafik, Sprünge über das sanfte Scrollen des
  Browsers). Der Effekt ersetzt den bisherigen und bleibt im Profil ein- und ausschaltbar;
  er setzt die eingeklappten Punkte (Akkordeon) voraus.
- **PDF öffnen mit Ladeanimation.** Der neue Tab bleibt nicht mehr leer und weiss, sondern
  zeigt sofort «Ihr PDF wird erstellt» mit einer Presse, die das Dokument zusammensetzt und
  stempelt, bis das PDF erscheint.
- **Links im Text.** Webadressen und E-Mail-Adressen werden erkannt: im Editor als Link
  dargestellt (Strg/Cmd+Klick öffnet sie), im PDF klickbar.
- **Matrix: vergangene Termine ausgegraut.** Terminzeilen haben im Matrix-Dialog den Schalter
  «Vergangene Termine ausgegraut» (Standard an); im PDF erscheinen sie grau wie im Editor.

### Deploy

- **`deploy.sh` aktualisiert zuerst den Deploy-Code.** Vor jedem Lauf holt es den neuesten
  signierten Stand von `origin/main` (`update_deploy_code.sh`, Signatur- und Hash-Prüfung wie
  bisher) und startet sich damit neu. Beim Update auf 1.2.3 hatte ein veraltetes `deploy.sh` das
  neue Release ausgerollt. Scheitert das Update, bricht der Deploy ab und das bisherige Release
  läuft weiter; bewusst mit dem vorhandenen Code: `HOCX_SKIP_DEPLOY_CODE_UPDATE=1`.
- **`update_deploy_code.sh` nimmt den neuesten signierten Stand.** Hat der neueste Commit auf
  `origin/main` keinen eigenen Testimage-Build (z. B. ein reiner Changelog-Commit), gilt der
  neueste signierte Vorgänger statt eines Abbruchs - nie ein älterer Stand als der aktuelle.
- **Upgrade-Tor prüft die Schreibrechte vor der Rückfrage.** Muss der Dateisystem-Bestand
  bereinigt werden, prüft `deploy.sh` zuerst im laufenden `storage-worker`, ob er überall im
  Dateispeicher schreiben darf. Sonst bricht es sofort ab, nennt die betroffenen Verzeichnisse
  und den root-Befehl (`chgrp -R 5001 …`); bisher hing die Bereinigung bis zum Timeout an
  «Permission denied» (Dateien von vor 1.2.0). Läuft der `storage-worker` nicht, bricht es
  ebenfalls sofort ab.

### Behoben

- **PDF: entfernte Termine erscheinen nicht mehr.** Termine, die im Editor aus einer
  Termin-Serie entfernt wurden, standen mit ihren leeren Vorgaben weiterhin im PDF.
- **PDF: «Abstand vor Abschnitten» wirkt.** Der Wert aus dem Corporate Design kam nie im PDF an:
  Nach jedem Traktandum stand ein fester Abstand von 12 pt, der den eingestellten Abstand vor dem
  nächsten Traktandum übersteuerte. Jetzt gilt zwischen Traktanden genau der eingestellte Wert,
  vor anderen Abschnitten mit Titel (z. B. Todos) mindestens 12 pt. Dokumente mit dem
  Standardwert (8 mm) werden dadurch sichtbar luftiger.
- **Terminlisten: PDF und Editor gleich sortiert.** Bei Terminen am selben Tag sortierte das
  PDF anders als der Editor; mit «höchstens N Termine» konnten so im PDF andere Termine stehen.
  Beide sortieren jetzt nach Datum und dann gleich. Bestehende PDFs ändern sich nur, wenn
  mehrere Termine am selben Tag in einer Liste stehen.
- **Editor: getippte HTML-Entitäten.** Ein wörtlich getipptes `&amp;` oder `&lt;` wurde nach
  dem Speichern und Neuladen zu `&` bzw. `<`.

## [1.2.3] - 2026-11-10

Rückmeldungen aus dem Testbetrieb von 1.2.2 (Protokoll-Editor und PDF-Gestaltung) und **nur noch
S3**: hocX speichert Dateien ausschliesslich in einem S3-kompatiblen Objektspeicher. Zwei neue
Migrationen (`0167`, `0168`). **Breaking Changes** - vor dem Update die Voraussetzungen unten
prüfen; das Update läuft wie gewohnt über `deploy.sh`.

### Breaking Changes

- **Nur noch S3.** Der Dateisystem-Speicher bis 1.2.2 (Generation 0), die Erstmigration
  Dateisystem → lokales S3 und die Rückfallfrist der Dateisystem-Generation entfallen. Dateien
  liegen ausschliesslich in einem S3-kompatiblen Objektspeicher (lokales Garage oder externer
  Anbieter); ein Weg zurück auf das Dateisystem existiert nicht.
- **Update nur von 1.2.0 bis 1.2.2 mit abgeschlossener Erstmigration** und ohne offene Storage-Migration.
  Sonst bricht `deploy.sh` vor dem Update mit «Upgrade gesperrt» ab, das bisherige Release läuft
  weiter; die Migration `0168_s3_only` prüft dasselbe noch einmal, ohne die Datenbank zu ändern.
- **Rückfallfrist beim Deploy beenden.** Liegt der Dateisystem-Bestand noch in der Rückfallfrist,
  warnt `deploy.sh` und fragt «Rückfallfrist jetzt beenden und den Dateisystem-Bestand
  bereinigen? [j/N]» (nicht interaktiv: `HOCX_SKIP_STORAGE_FALLBACK=1`, sonst Abbruch). Danach
  bereinigt der `storage-worker` des bisherigen Releases den Bestand - nur Dateien, deren Kopie die
  Erstmigration verifiziert hat - und `deploy.sh` wartet darauf (`HOCX_STORAGE_PURGE_TIMEOUT`,
  Default 3600 s). Ist die Frist schon abgelaufen, wird ohne Rückfrage bereinigt.
- **Backups von vor der S3-Migration** lassen sich nur noch mit hocX bis 1.2.2 wiederherstellen; die
  Wiederherstellung lehnt sie mit `backup_pre_s3` ab. `BACKUP_TRUST_FILESYSTEM_REGISTRY` und das
  Restore-Ziel `--storage filesystem` der Recovery-CLI entfallen.

### Migration

- `0167_kreide_spacing`: Corporate-Design-Profile im Design «Kreide» bekommen grössere Abstände
  (Zeilenabstand 1.35 → 1.5, Absatzabstand 2.5 → 3 mm, Abstand vor Abschnitten 6.5 → 10 mm),
  je Wert nur, wenn er noch auf dem bisherigen Wert des Beispiels steht. Als neue Revision; die
  vorherige lässt sich im Corporate Design wiederherstellen, bestehende PDFs bleiben gleich.
- `0168_s3_only`: Upgrade-Tor (siehe oben). Neuinstallationen ohne Dateien stellen direkt auf das
  Profil «Lokales S3 (Garage)» aus `LOCAL_S3_*` um (Generation 1). Das bisherige
  Dateisystem-Profil bleibt als deaktivierte Historie erhalten.

### Neu

- **Schnellmenü in allen Modi.** Sitzungsnotizen, Pendenz erfassen, Anliegen und Zusammenarbeit
  stehen jetzt beim Vorbereiten, in der Sitzung und beim Überarbeiten zur Verfügung (nicht im
  abgeschlossenen Protokoll).
- **Im Protokoll erfasste Pendenzen bearbeiten:** der Text lässt sich direkt im Protokoll ändern
  (im Nachverfolgungsmodus mit altem Text durchgestrichen).
- **Matrix schreibt in die Liste zurück.** Stammen die Karten einer Matrix aus einer Liste, werden
  Änderungen in den Zeilen aus der Liste (z. B. Leiter einer Gruppe) im Listeneintrag gespeichert.
- **Bussen mit Herkunft:** der Bussen-Block im PDF zeigt in der Spalte «Protokoll» für jede
  Busse Nummer und Datum des Protokolls, aus dem sie stammt.
- **Terminlisten: Zeilen in Tag-Farbe.** Die Option (bisher «Tag-Farben») hinterlegt jede Zeile im
  PDF und im Editor hell in der Farbe ihres Tags, auch ohne Tag-Spalte. Tags selbst erscheinen in
  Terminlisten jetzt immer in ihrer Farbe.

### Geändert

- «Sitzungs-Todos» heisst in Protokollen und Vorlagen nur noch «Todos» (en «To-dos», fr «Tâches»,
  it «Attività da fare»).
- Design «Kreide» luftiger gesetzt (siehe Migration); gilt auch für neu übernommene Beispiele.
- Zugeklappte Punkte im Akkordeon zeigen nur noch die Überschrift (vorher blieben die im
  Protokoll erfassten Pendenzen und Anliegen sichtbar).
- **Neuinstallationen starten direkt auf dem lokalen S3**, ohne Erstmigration und ohne
  Wartungsfenster.
- System → Storage zeigt keine Erstmigration mehr. Das alte Dateisystem-Profil erscheint als
  «Dateisystem (bis 1.2.2, nicht mehr unterstützt)» ohne Aktionen, frühere Erstmigrationen im
  Verlauf als «Erstmigration (bis 1.2.2)». Jede Migration ist eine Live-Migration zwischen
  S3-Profilen.
- Dokumentation: neuer Abschnitt «Upgrade auf S3-only» (Technik → Dateispeicher → Migrationen),
  RUNBOOK Abschnitt 14 angepasst.
- Der `photo-analysis-worker` liest Dateien nur noch über das S3-Profil und mountet den
  Speicherpfad nicht mehr.

### Behoben

- **Scrollen im Akkordeon (ohne Rad-Effekt):** ein Mausrad-Schritt übersprang kurze, zugeklappte
  Punkte, und am Dokumentanfang sprang die Auswahl beim Hochscrollen direkt auf den ersten Punkt.
  Jetzt kommt immer der nächste Punkt dran; nach oben erscheint ein langer Punkt mit seinem Ende
  am unteren Rand. Der Rest-Schwung des Mausrads wird in beide Richtungen kurz abgefangen.
- **Teilnehmerzahl in Matrix-Karten sprang zurück,** wenn die Termine über einen Zyklus gefiltert
  waren (die Karte zeigte einen einmal geladenen Stand).
- **PDF: «Absatzabstand» wirkte nicht auf Textblöcke** (fester Abstand im Rich-Text); Aufzählungen
  bleiben kompakt.
- **PDF: «Linienstärke» wirkte nicht auf Rahmen** von Karten, Kacheln, Formularen, Pendenzen und
  Matrix (fest 0.5 pt).

## [1.2.2] - 2026-11-09

Erweiterungen aus dem Testbetrieb und ein Performance-Paket auf 1.2.1. Eine neue Migration
(`0166`), keine Breaking Changes. Das Update läuft wie gewohnt über `deploy.sh`; neu sind
Postgres-Parameter und die Komprimierung durch Traefik (siehe «Beim Update beachten»).

### Migration

- `0166_perf_job_run_indexes`: `record_job_run` sucht den letzten Lauf über den passenden Index
  statt über den ganzen Verlauf, vier überflüssige Indizes entfallen. Keine Datenänderung.

### Beim Update beachten

- **Postgres-Parameter im Release-Stack:** `random_page_cost=1.1`, `effective_io_concurrency=200`,
  `max_wal_size=2GB`, `pg_stat_statements.track=top`. Sie gelten für alle Release-Instanzen und
  gehen von SSD-Speicher aus; `deploy.sh` erstellt die Datenbank dafür neu (kurzer Neustart).
- **Komprimierung liegt jetzt bei Traefik** (`compress@file`, zstd, Brotli, gzip, nur Text-Formate);
  Next.js komprimiert nicht mehr selbst. Betrieb ohne Traefik liefert unkomprimiert aus: ein
  eigener Reverse-Proxy muss HTML, CSS, JS und JSON selbst komprimieren.
- **Abnahme auf dem Test-Host:** Skill `testhost-abnahme` (`.claude/skills/testhost-abnahme`) und
  `scripts/testhost/abnahme.sh`.

### Neu

- **Transaktionen im Protokoll erfassen:** im Block «Transaktionen» Datum, Beschreibung,
  Einnahme/Ausgabe und Betrag eintragen (mit dem Protokoll verknüpft, Saldo und Kontostand werden
  sofort nachgeführt); im Protokoll erfasste Transaktionen lassen sich dort wieder löschen.
  Benötigt «Finanzen verwalten».
- PDF: Anwesenheit in den Darstellungen «Raster» und «Chips» mit ausgeschriebenem Status statt
  Punkt.
- **Pendenzen exportieren mit Auswahl:** im Export-Dialog «Fällig bis», «Nur mit Tag» und jede
  Pendenz einzeln an- oder abwählen (gilt für PDF, CSV, Excel und Text).
- **Neuer Export-Dialog.** Links Auswahl und Aussehen, rechts eine Live-Vorschau im gewählten
  Format: PDF-Seiten, Tabelle für CSV und Excel, die Nachricht für WhatsApp. Unten Spalten, Format
  und ein einziger Knopf zum Erstellen. Bei Pendenzen zusätzlich filterbar nach Status (auch «In
  Arbeit»), **Überfällig**, nächster Sitzung, Monatsende oder Datum (wahlweise mit Pendenzen ohne
  Fälligkeit), Tag, zuständiger Person und Protokoll; jeder Filter zeigt die Anzahl.
- **Gestaltungsbeispiele für alle Dokumenttypen.** Die Designs Kreide, Signal, Fokus, Siegel
  und Atlas gibt es neben dem Protokoll jetzt auch für Einladung, Traktandenliste, Anwesenheit,
  Präsenzliste, Mitgliederliste, Pendenzen, Terminplan, Kalender, Finanzbericht, Buchungen,
  Bussen, Statistik, Liste, Formular und freies Dokument (75 Vorlagen im Katalog). Übernehmen wie
  bei den Protokoll-Beispielen, auf Wunsch mit dem CD des Designs, danach frei bearbeiten. Die
  Pendenzenliste zeigt dabei auch die Anzahl überfälliger Pendenzen.
- **Matrix-Karten aus einer Liste aktualisieren.** Ändert sich die Liste hinter einer Matrix,
  zeigt der Block einen Hinweis mit «Daten aktualisieren»: neue Einträge werden zu Karten,
  Umbenennungen und Werte werden übernommen, Karten gelöschter Einträge entfallen. Karten mit
  erfassten Werten bleiben stehen und sind als «Nicht mehr in der Liste» markiert.

### Geändert

- **Rad-Effekt beim Scrollen standardmässig aus.** Er kippte jeden Abschnitt einzeln und
  ruckelte bei grossen Protokollen beim Scrollen und Schreiben. Wer ihn ausdrücklich eingeschaltet
  hat, behält ihn (Profileinstellung). Stattdessen werden Inhalte zum oberen und unteren Rand des
  Protokollbereichs hin sanft blasser (zwei mitlaufende Verlaufs-Leisten, ohne Neuzeichnen beim
  Scrollen).
- **Performance.** Gemessen mit einem Protokoll mit 23 Traktanden, CPU 4-fach gedrosselt:
  - Tippen in einer Pendenz: rund 60 ms statt 490 ms Verzögerung pro Taste. Pendenzen werden
    verzögert gespeichert, Bearbeitungssperren und Änderungen zeichnen nicht mehr alle Traktanden
    neu.
  - Protokoll öffnen: erstes Byte nach rund 410 ms statt 1050 ms. Aufgaben und Bilder kommen
    gebündelt (`GET /api/protocols/{id}/block-todos`, `/block-images`) statt je Block, Bezüge
    werden gesammelt nachgeschlagen.
  - Jede Seite lädt nur noch das CSS ihres Bereichs (250–340 KB statt 580 KB) und nur die
    Übersetzungen ihres Bereichs; Diagramme und schwere Dialoge kommen erst bei Bedarf.
    Neue Regeln dafür: `design/DESIGN.md` Abschnitt 10, `scripts/check-css-scopes.py`.
  - API-Antworten werden komprimiert, Admin-Seiten fragen in versteckten Tabs nicht mehr ab.

### Behoben

- Export-Dialog: die Spaltenauswahl erschien nie (die Anfrage für die Spaltenliste wurde vom Server
  abgelehnt).
- **Matrix-Karten aus einer Liste** stehen immer in der Reihenfolge der Liste und springen nicht
  mehr zwischen Spalten, wenn eine Karte höher wird. Die Karten-Auswahl erkannte beim Anlegen des
  Protokolls erzeugte Karten nicht (interne statt öffentliche ID) und konnte doppelte Karten anlegen.

## [1.2.1] - 2026-11-08

Fehlerkorrekturen auf 1.2.0 und kleinere Erweiterungen aus dem Testbetrieb. Drei neue
Migrationen (`0163`–`0165`), keine Breaking Changes. Das Update läuft wie gewohnt über
`deploy.sh`; die Migrationen korrigieren dabei bestehende Daten (siehe «Datenkorrekturen beim
Update»).

### Datenkorrekturen beim Update

- `0163_attendance_fine_repair`: Anwesenheitsbussen in **nicht abgeschlossenen** Protokollen
  werden an die erfasste Anwesenheit angeglichen. Fehlende Bussen für «Verspätet» und
  «Unentschuldigt» entstehen neu, offene Bussen mit falschem Typ werden gelöscht. Abgeschlossene
  Protokolle, eingezogene und mit Begründung gelöschte Bussen bleiben unverändert. Auch von Hand
  in einem offenen Protokoll gelöschte Bussen werden dabei wieder angelegt.
- `0164_submission_todo_public_ref`: Abgabe-Pendenzen, deren Element schon geprüfte Dateien hat,
  werden erledigt. Einträge des Abgabe-Verlaufs aus dem erneuten Virenscan bekommen die richtige
  Element-Referenz.
- `0165_event_field_config`: neue Mandanten-Einstellung für die Spezialfelder der Termine.

### Neu

- **Spezialfelder der Termine umbenennen oder ausblenden.** Unter Mandant-Einstellungen →
  Allgemein bekommen «Spezial 1–3» und «Spezial Text 1–3» eigene Namen oder werden ausgeblendet
  (Werte bleiben erhalten). Gilt beim Anlegen und Bearbeiten von Terminen, in den Termin-Feldern
  im Protokoll, im Abgabe-Formular, im Vorlagen-Editor und im Word-Import.
- **Text-Export für WhatsApp.** «Text kopieren (WhatsApp)» im Export-Dialog legt die
  Pendenzenliste direkt in die Zwischenablage, nur mit WhatsApp-Formatierung (fett, kursiv,
  durchgestrichen). Für CSV, Excel und Text lassen sich die Spalten pro Export an- und abwählen.
- **Smarte Datumsvorschläge** im Fälligkeits-Menü der Pendenzen: «morgen», «Freitag nächste
  Woche», «Ende Monat», «in 3 Wochen», «24.12.» usw. erscheinen, sobald das Getippte passt.
- **Mehrere Verantwortliche bei Abgaben.** Stehen mehrere Personen im Verantwortlichen-Feld eines
  Termins (oder in einer Listenspalte mit mehreren Personen), bekommen alle gemeinsam die Pendenz.
- **Abgabe-Status farbig:** abgegeben grün, Quarantäne gelb, offen blau, noch nicht offen bzw.
  ohne Abgabe geschlossen grau, Frist verpasst oder Scanfehler rot.
- Matrix-Planung: die Teilnehmerzahl lässt sich direkt in der Termintabelle ändern.
- Neuer Hintergrund-Job «Abgabe-Pendenzen abgleichen» (alle 15 Minuten, `/admin/jobs`).

### Behoben

- **Verspätete bekamen keine Busse mehr**, nachdem im Anwesenheitsblock einmal geklickt wurde:
  die Antwort enthielt den Bussentarif nicht, der Editor hielt die Bussen bis zum Neuladen für
  ausgeschaltet.
- **Abgaben schlossen ihre Pendenz nicht mehr ab.** Der Datenbank-Trigger suchte die Pendenz mit
  der internen statt der öffentlichen ID. Die Verknüpfung Termin → Abgabe → Pendenz wird jetzt bei
  jeder Termin-Änderung (Person, Titel, Tag, Löschen, Tag umbenennen, Importe) nachgeführt.
  Weggefallene offene Pendenzen werden entfernt, von Hand ergänzte nur abgebrochen. Dateien in
  Quarantäne erledigen eine Pendenz erst nach dem Scan.
- **Neu angehakte Termine** in einem Element mit Vorlagen pro Termin bekamen leere Blöcke. Jetzt
  entstehen alle Blöcke nach denselben Regeln wie beim Anlegen des Protokolls.
- **Termin-Änderungen über das Menü der Matrix-Tabelle** gingen bei langsamer Verbindung verloren
  (jeder Tastendruck speicherte parallel). Änderungen pro Termin laufen jetzt nacheinander.
- **Personen in Matrix-Zellen** wurden gespeichert, aber nicht angezeigt.
- Formular-Tabellen zeigten «N ausgewählt» statt der Namen.
- **Kalender in Menüs:** ein Klick auf ein Datum im Kalender eines Menüs (z. B. Fälligkeit im
  Pendenzen-Dialog) schloss das Menü, bevor das Datum ankam. Gilt für alle Menüs mit Kalender,
  Auswahlliste, Uhrzeit oder Farbauswahl.
- **Sperre bei gleichzeitiger Bearbeitung:** die Prüfung auf dem Server fand die Sperre des
  Editors nie (interne statt öffentliche Block-ID); gleichzeitiges Speichern wird jetzt abgewiesen.
- Vorbelegte Termine aus der Vorlage (Formular- und Matrixzeilen) erschienen im Protokoll leer;
  verknüpfte Listeneinträge ohne Snapshot erschienen als gelöscht.
- Virenscan-Ergebnisse fehlten im Verlauf eines Abgabe-Elements.
- Der Link von Abgabe-Dateien in der Dateiübersicht führte auf eine nicht vorhandene Seite; er
  öffnet jetzt die Abgabe.
- Dokument-Studio: Pendenzen-Felder standen in der Auswahl unter «Protokoll».

## [1.2.0] - 2026-10-28

Feature-Release auf 1.1.13. Fünf Entwicklungszweige sind zusammengeführt und aufeinander
abgestimmt: die neue **Dokument-Engine mit Document Studio** (Typst statt TeX, Corporate Design,
Vorlagen, Echtheitsprüfung), ein einheitlicher **Objektspeicher** (Dateisystem oder S3) mit
Wartungsmodus, ein **Offsite-Backup mit BorgBackup** inklusive Restore, eine
**Dokumentverwaltung** mit PDF-Ansicht und Textextraktion sowie **Bild-Metadaten** mit
Vorab-Abgleich beim Upload. Dazu die Audit-Reparaturen aus `main` (Abschnitt «Betrieb») und
die Umsetzung von vier Audits: **Datenschutz** (DSG/DSGVO: Löschung, Auskunft, Fristen,
Sicherheitsprotokoll), **Sicherheit** (u. a. Row-Level-Security in PostgreSQL, verschlüsselte
Exporte), **Stabilität unter Last** (neuer `job-worker`, Überlast-Schutz nach Abo) und
**Feature-Recovery**. Neu ausserdem **Anliegen**: Punkte für kommende Sitzungen, die
automatisch im nächsten Protokoll erscheinen. Die Datenbank wechselt auf **PostgreSQL 18**
(Umzug der Daten übernimmt `deploy.sh`). **Breaking Changes** - vor dem Update die Schritte
unten lesen.

### Update von 1.1.13 auf 1.2.0

1. **Backup ziehen.** `deploy.sh` legt vor den Migrationen einen Datenbank-Dump an, die
   Dateiablage (`HOCX_STORAGE_PATH`) zusätzlich selbst sichern. Migration
   `0115_document_engine_migrate` (TeX-Vorlagen → Hausstile → Brand-Profile) ist **nicht
   umkehrbar**, mehrere weitere Migrationen verlieren beim Downgrade Daten (u. a. `0116`,
   `0118`, `0136`, `0139`, `0141`). Der Rückweg auf 1.1.13 geht nur über `restore_db.sh` mit
   diesem Dump plus dem alten Deploy-Code. Der automatische App-Rollback von `deploy.sh` startet
   zwar die alten Images, rollt aber keine Migration zurück, und das 1.1.13-Backend erreicht das
   jetzt passwortgeschützte Redis nicht. Das alte PostgreSQL-16-Volume bleibt nach dem Update
   unverändert liegen (Schritt 3): der alte Deploy-Code startet wieder darauf, also mit dem Stand
   unmittelbar vor dem Update.
2. **Dump-Verschlüsselung vorbereiten (empfohlen).** `gpg` auf dem Host installieren und den
   öffentlichen Schlüssel unter `~/.hocx-backup/dump-public.asc` ablegen (oder
   `BACKUP_DUMP_PUBLIC_KEY_PATH` setzen, RUNBOOK Abschnitt 10). Ohne Schlüssel schreibt
   `deploy.sh` den Dump unverschlüsselt mit Warnung; mit `HOCX_REQUIRE_DUMP_ENCRYPTION=true`
   bricht er ab. Pre-Deploy-Dumps werden auf 10 Stück und höchstens 30 Tage gekürzt.
3. **Platz und Wartungsfenster.** Das Backend-Image wird grösser (LibreOffice, Tesseract,
   Poppler für den `document-worker`; BorgBackup, SSH und PostgreSQL-Client für den
   `backup-worker`; TeX Live entfällt). Lokales S3 (Garage) belegt erst nach einer
   Storage-Migration nennenswert Platz. PostgreSQL (`max_connections=150`) und Redis (neu mit
   Passwort im internen Netz `cache`) werden vor den Migrationen neu gestartet; ab dann bis zum
   Ende des Deploys ist die App nicht nutzbar. Wartungsfenster einplanen.
   **PostgreSQL 16 → 18:** Ein 16er-Cluster startet unter 18 nicht. `deploy.sh` stoppt deshalb
   nach dem Pre-Deploy-Backup alle Dienste ausser Traefik und lokalem S3, überträgt Rollen und
   Datenbanken per `pg_dumpall` direkt (ohne Zwischendatei) in das neue Volume
   `<projekt>_postgres18_data` und vergleicht danach Datenbanken, Rollen und die Zeilenzahl jeder
   Tabelle (`scripts/lib/pg_upgrade.sh`). Dauer etwa wie ein Dump plus Restore; freier Platz:
   rund das Anderthalbfache der Datenbankgrösse plus 1 GB. Das alte Volume
   `<projekt>_postgres_data` wird nur gelesen. Scheitert ein Schritt, entfernt `deploy.sh` das
   neue Volume und startet die gestoppten Dienste wieder, die App läuft dann weiter auf 1.1.13.
   Den Stack bis zum Abschluss nicht von Hand mit `docker compose up` starten, sonst legt
   PostgreSQL 18 ein leeres Volume an (`deploy.sh` erkennt das und bricht ab).
   Lief nach einem Rückweg auf 1.1.x wieder PostgreSQL 16 auf dem alten Volume, erkennt ein
   erneuter 1.2.0-Deploy den veralteten 18er-Stand und bricht mit Anleitung ab.
4. **Alte Vorlagen-Dateien zurücksetzen (als root, vor dem Code-Update).** 1.1.13 hat
   TeX-Dateien unter `storage/document_templates/` und `storage/latex_templates/` im Repository
   versioniert; das Backend schreibt sie bei jedem PDF-Export neu, und zwar mit Rechten, die der
   Deploy-Benutzer nicht ändern kann. `update_deploy_code.sh` bricht dann mit «Tracked
   Worktree-Aenderungen vorhanden» ab. Liegt `HOCX_STORAGE_PATH` im Checkout (Standard
   `./storage`), deshalb im Repository-Verzeichnis:

   ```bash
   # als root
   chown -R hocx-deploy:5001 storage && chmod -R u+rwX,g+rwX,o-rwx storage \
     && find storage -type d -exec chmod g+s {} +
   # als hocx-deploy
   git restore storage && git status --short --untracked-files=no   # muss leer sein
   ```

   Zurückgesetzt wird nur erzeugter TeX-Code; hochgeladene Logos, Schriften und alle übrigen
   Dateien sind nicht versioniert und bleiben unverändert.
5. **Code und Version.** Release 1.2.0 muss auf `main` stehen und den CI-Nachweis haben
   (`update_deploy_code.sh` akzeptiert nur `main`). `HOCX_VERSION=v1.2.0` in `.env`, dann
   `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>`. `deploy.sh` ergänzt
   die neuen Secrets (`STORAGE_CREDENTIALS_KEY`, `EXPORT_ENCRYPTION_KEY`, `REDIS_PASSWORD`,
   Zugangsdaten des lokalen S3, leere Backup-Platzhalter) und stellt `HOCX_ENVIRONMENT=prod` auf
   `production` um; die ergänzte `.env` danach neu sichern. Keine neuen Pflicht-Variablen.
   Optional (siehe `.env.prod.example`): `DOCUMENT_VERIFY_BASE_URL` (Standard
   `ABGABEBOX_BASE_URL/verify`), `ABGABEBOX_DEFAULT_PRIVACY_URL`, `HOCX_SERVER_LOCATION`
   (Standard `ch`), `STORAGE_ALLOWED_LOCATIONS`, `TENANT_OFFBOARDING_GRACE_DAYS`,
   `FRIENDLY_CAPTCHA_PUZZLE_URL`/`_VERIFY_URL` (EU-Endpunkt), `GARAGE_CAPACITY`, die
   Lastparameter `DB_POOL_*`, `DB_ADMISSION_*`, `OVERLOAD_*` und die Alarmschwellen
   `SECURITY_*` (RUNBOOK Abschnitt 17). `BACKUP_ENABLED=true` erst **nach** dem ersten
   1.2.0-Deploy setzen (vorher läuft kein `backup-worker`, `deploy.sh` bricht sonst ab).
6. **Migrationen** `0113` bis `0162` laufen automatisch. Getestet von 1.1.13 mit Demodaten und
   einem Vereinsstand mit TeX-Vorlage (Logo, Fussbild, eigene Schrift, eigener Vorlagen-Code),
   Protokollen, Todos, Bussen und Alt-PDF-Exporten: keine Fachdaten gehen verloren, Logo,
   Fussbild, Schrift und Farben landen je Mandant im Brand-Profil, die Alt-Exporte in der
   Export-Historie; Schema und Datenbankrechte sind danach identisch mit einer Neuinstallation.
   Neue Dienste `storage-init`, `storage-worker`, `local-s3`, `backup-worker`,
   `document-worker` und `job-worker` startet `deploy.sh` mit `up -d`. Die Smoke-Checks prüfen
   zusätzlich `document-worker`, `storage-worker` und `job-worker`.
7. **Nach dem Deploy:**
   - Neue PDFs setzen die hochgeladene Schrift eines Vereins ein, wo 1.1.13 sie nur bei der
     Schriftwahl «Eigene Schrift» bzw. «Century Gothic» nutzte und sonst DejaVu setzte. Exporte
     sehen dadurch teilweise anders aus; die Schrift lässt sich im Brand-Profil umstellen.
   - Das alte Datenbank-Volume nach ein paar Tagen Betrieb entfernen:
     `docker volume rm <projekt>_postgres_data` (Name in der Ausgabe von `deploy.sh`). Danach
     führt der Rückweg auf 1.1.13 nur noch über den Pre-Deploy-Dump.
   - `/admin/system`: Checks «Öffentliche Prüfseite», «Dateispeicher» und
     «Dokumentverarbeitung» grün; ein Protokoll exportieren und auf `/verify` der Abgabebox
     prüfen (Ergebnis «Original»).
   - Alte TeX-Vorlagen-Dateien entfernen, **solange noch das Dateisystem aktiv ist** (vor einer
     Umstellung auf S3): `./scripts/cleanup-legacy-document-templates.sh --dry-run`, dann ohne
     `--dry-run` (RUNBOOK Abschnitt 13).
   - `document_sync` übernimmt bestehende Dateien und Protokollexporte schrittweise als
     logische Dokumente; Fortschritt: `docker compose exec backend python -m app.workers.document_admin status`
     (RUNBOOK Abschnitt 16).
   - Optional einmalig den Bild-Metadaten-Backfill:
     `docker compose exec backend python -m scripts.backfill_image_metadata`
     (`backend/UPLOAD_DUPLICATES.md`, Abschnitt 12).
8. **Später, bewusst entscheiden:** Erstmigration der Dateien in den Objektspeicher (RUNBOOK
   Abschnitt 14) und Einrichtung des Borg-Offsite-Backups mit Ablösung der Cronjobs
   `backup_db`/`backup_storage` (RUNBOOK Abschnitt 15). Bis dahin bleibt das Dateisystem aktiv und
   die bisherigen Backup-Cronjobs gelten weiter.

**Wer einen Vorabstand mit digitaler Dokumentsignatur installiert hatte:** Die Signatur entfällt
vollständig. Die Variablen `DOCUMENT_SIGNING_*` werden ignoriert und können aus `.env` entfernt
werden, ebenso das Verzeichnis `.signing/` bzw. `DOCUMENT_SIGNING_DIR` und die Datei
`.secrets/document_signing_key_password`. Bereits signiert exportierte PDFs bleiben über die
Prüfseite prüfbar, weil ihr Hash gespeichert war (Migration `0116_document_registry`).

### Gestaltung und Designer (Nachtrag vom 2026-10-28)

- **Gestaltung auf Abruf.** Mitgelieferte Vorlagen und Designs (Alpin, Kreide …) liegen in einem
  zentralen **Katalog** und landen erst im Verein, wenn jemand sie übernimmt - als genau eine
  Vorlage, die sich ihre Herkunft merkt («Aus Katalog · Alpin»). Der Katalog zeigt die Vorschau
  mit dem eigenen Erscheinungsbild.
  - «Dokumentvorlagen» zeigt nur noch eigene und übernommene Vorlagen, gruppiert in «Sitzung»
    und «Weitere Dokumente», mit Verwendung (Protokollvorlagen bzw. Exporte der letzten zwölf
    Monate), «Standard» und «Update vN», wenn die Katalog-Fassung einer übernommenen
    Systemvorlage neuer ist. Fehlt ein Dokumenttyp, nutzt der Export weiter den Katalog-Standard
    ohne Kopie; die Karte «Aus Katalog hinzufügen» nennt ihn.
  - Die bisherige Seite «Protokollgestaltung» ist darin aufgegangen; `/documents/protocols`
    leitet auf `/documents` um.
  - «Neue Vorlage»: Dokumenttyp, dann Start aus dem Katalog, als Kopie einer eigenen Vorlage oder
    leer, dazu die Wahl des Erscheinungsbilds. **Ein Design legt kein eigenes Brand-Profil und
    keine Beispielbilder mehr an**; es nutzt das Erscheinungsbild des Vereins. Übernehmen
    braucht deshalb nur noch das Recht, Vorlagen zu gestalten (nicht mehr `settings.manage`).
  - **Aufräumen**: eigene Vorlagen, die nicht Standard, keiner Protokollvorlage zugewiesen, in
    zwölf Monaten nicht exportiert und älter als 30 Tage sind, lassen sich gesammelt archivieren
    (umkehrbar).
  - «Erscheinungsbild» (bisher «Brand Studio») trennt verwendete und nicht verwendete Profile
    (gesammelt archivierbar), zeigt «Wirkt auf N Vorlagen» und die Vorschau als Protokoll,
    Einladung oder Präsenzliste.
  - «Bilder und Schriften» filtert nach verwendet/nicht verwendet, zeigt, wo eine Datei steckt,
    und führt gleiche Dateien zusammen (nur unbenutzte Kopien werden entfernt).
  - Migration `0160_template_catalog_key` (neue Spalte, keine Datenänderung).
- **Gestaltungen: wer sie verwendet, was beim Anpassen passiert.** Im Vorlagen-Editor (PDF,
  Einladung) zeigt eine Zuweisungs-Leiste die verwendete Gestaltung, die anderen Vorlagen, die
  sie auch verwenden, und drei Wege: «Andere wählen» (sofort gespeichert, inkl. Standard des
  Vereins), «Bearbeiten» (wirkt auf alle Vorlagen, die sie verwenden) und «Nur hier anpassen»
  (Kopie; der Hinweis sagt, dass Änderungen an der Ausgangsgestaltung hier nicht mehr gelten).
  «Eigene/Gemeinsame Gestaltung» entfällt, die Tabs zeigen den Namen der Gestaltung.
- Designer: Hinweis, auf wie viele Vorlagen eine Änderung wirkt, mit «Nur für … ändern». Der
  Hinweis lässt sich wegklicken und erscheint wieder, wenn sich die Verwendung ändert.
- Jede Gestaltung zeigt, welche Protokollvorlagen sie verwenden; Kopien einzelner Vorlagen
  erscheinen in der Liste ebenfalls.
- Dokument-Designer mit zwei Modi wie im Entwurf v2: «Einfach» und «Erweitert». Der bisherige
  Modus «Experte» ist in «Erweitert» aufgegangen, damit u. a. die Position frei platzierter
  Elemente (z. B. Adresse in einer freien Ebene) wieder bearbeitbar ist; für solche Elemente
  entfallen die wirkungslosen Felder «Abstand oben/unten».
- PDF: grösserer Abstand zwischen den Traktanden. «Abstand vor Abschnitten» (Corporate Design →
  Seitenaufbau) hat neu 8 statt 6 mm als Standard (Vorlage «Kompakt»: 5 statt 4 mm). Profile mit
  dem bisherigen Standardwert bekommen per Migration `0159_brand_section_gap` eine neue Revision
  mit dem neuen Wert; eigene Werte bleiben, die vorherige Revision lässt sich wiederherstellen.
- Design «Kreide» näher am Mockup «Protokoll Template v2»: Aufzählungen mit Punkten statt
  Strichen (Grundstil). Beispiel-Vorlage und -CD: Traktandentitel in Textfarbe mit grüner Nummer,
  14/10.5 pt bei 9.5 pt Grundschrift; im Seitenkopf der Vereinsname klein geschrieben und
  «Titel · Datum»; Metadaten, Kennzahlen-Beschriftungen und Adresszeile in der Zweitfarbe;
  Inhaltsverzeichnis mit normalem Zeilenabstand; neues Vorschaubild.
- Abhängigkeiten aktualisiert (Dependabot und npm/PyPI): Node 24 LTS in den Frontend-Images und
  der CI (statt 22; das vorgeschlagene Node 26 ist noch kein LTS), Next.js 16.4.3, React 19.3.1,
  TypeScript 6.0, Vitest 5, Recharts 3, Playwright 1.64.1; FastAPI 0.162, SQLAlchemy 2.1,
  Alembic 1.20, psycopg 3.3, Pydantic 2.14, Uvicorn 0.54, redis-py 8, pytest 9; Traefik 3.7.15,
  Garage 2.4.1, aktuelle Digests für ClamAV, PostgreSQL 16, Python und nginx; GitHub Actions auf
  die aktuellen Hauptversionen (Node-24-Laufzeit). PostgreSQL bleibt bewusst bei 16: der
  Sprung auf 18 braucht ein Upgrade der Datenbank (`pg_upgrade` bzw. Dump/Restore) und ein
  anderes Volume-Layout und wird separat geplant.

### Protokoll-Editor und Abgabebox (Nachtrag vom 2026-11-08)

- **Protokoll-Editor schneller bei langen Protokollen.** Tippen und Löschen renderte bei jedem
  Tastendruck alle Punkte neu, jetzt nur noch den bearbeiteten. Der Rad-Effekt kippt nur noch
  Abschnitte in Bildnähe (vorher war jeder Abschnitt eine eigene 3D-Ebene), und die Positionen
  der Abschnitte werden nicht mehr in jedem Scroll-Frame neu gemessen. Gemessen mit 54 Punkten und
  vierfach gedrosselter CPU: Tastendruck 128 → 57 ms, Scroll-Frame 62 → 35 ms im Mittel.
- Abgabebox: die Sicherheitsprüfung (Captcha) läuft nur noch einmal pro Seitenaufruf. Das
  Sitzungs-Token gilt für den ganzen Abgabe-Link statt für ein einzelnes Element; Bindung an
  IP-Adresse und Ablaufzeit bleiben.
- Abgabebox: «GPS-Daten des Bildes mitsenden» erscheint erst, wenn ein Bild ausgewählt ist.
- Anwesenheit: Wer schnell über «Verspätet» auf «Entschuldigt» weiterklickte, behielt eine offene
  Verspätungsbusse. Die beiden Änderungen liefen gleichzeitig, die zweite sah die eben angelegte
  Busse noch nicht. Änderungen derselben Person laufen jetzt nacheinander (Desktop und Mobil).

### Korrektur: Gekoppelte Listen im Protokoll (Nachtrag vom 2026-11-08)

- Personen- und Termin-Spalten einer gekoppelten Liste blieben im Protokoll leer, obwohl die
  Liste Werte hatte. Mit «Gruppieren nach» dieser Spalte landeten alle Einträge in einer Zeile
  «Ohne Wert». Der eingefrorene Listenstand im Protokoll enthielt interne IDs, die die Oberfläche
  nicht zuordnen konnte. Die API übersetzt sie jetzt beim Lesen und beim Speichern zurück, das gilt
  auch für Zeilen «Zeile aus Liste», die Änderungsverfolgung und die Rückgängig-Kopie.

### Update-Probe (Nachtrag vom 2026-11-06)

Ein vollständiges Update von 1.1.13 auf den aktuellen Stand mit `update_deploy_code.sh` und
`deploy.sh test` (Altdaten mit TeX-Vorlage, Logo, Fussbild, eigener Schrift, PDF-Exporten,
Fotos und Abgabebox-Uploads) brachte drei Korrekturen:

- **Mandanten liessen sich nicht mehr löschen**, sobald ihre Konten Einträge im Audit-Log hatten
  (praktisch immer: jede Anmeldung). `audit_log_forget_tenant` (0143) änderte die Zeilen in
  derselben Transaktion, danach scheiterte das Löschen an `audit_log_actor_user_id_fkey`. Betraf
  das Adminportal, das automatische Offboarding und auf Testumgebungen jeden Deploy (Neuaufbau
  des Demo-Mandanten). Migration `0162_audit_forget_tenant_actor` entfernt dabei auch den Verweis
  auf das Konto.
- `deploy.sh` setzt fehlende Gruppenrechte auf eigenen Dateien unter `HOCX_STORAGE_PATH` selbst
  (Git legt `storage/exports/.gitkeep` beim Code-Update mit 0644 neu an); root braucht es nur
  noch für Dateien anderer Besitzer.
- Update-Anleitung um das Zurücksetzen der in 1.1.13 versionierten Vorlagen-Dateien ergänzt
  (Schritt 4).
- Rollback-Ziel: `deploy.sh` schreibt `.releases/current.env` jetzt direkt nach bestandenen
  Smoke-Checks. Scheiterte danach ein Folgeschritt (Storage-Controller, Demo-Seed), blieb es auf
  dem alten Release stehen, ein späterer Rollback hätte das falsche Ziel genommen. Ein
  fehlgeschlagener Demo-Seed auf Testumgebungen ist nur noch eine Warnung.
- Dateirechte in der Dateiablage: Backend, Abgabebox und Foto-Worker legten Verzeichnisse und
  Dateien mit der Docker-Standard-umask (2755/0644) an. Andere Dienste der Gruppe 5001 konnten dort
  nicht schreiben, und jeder weitere `deploy.sh` verlangte root. Alle Prozesse nutzen jetzt umask
  0007 (2770/0660). Auf Hosts, die bereits einen 1.2.0-Testkandidaten betrieben haben, einmalig den
  root-Befehl ausführen, den `deploy.sh` dann nennt.
- PostgreSQL 18 (siehe Schritt 3), Backend-Image mit `pg_dump`/`pg_restore` 18, CI und
  Test-Stacks auf 18. Dazu Traefik 3.7.16 und ein aktuelles ClamAV-Image.

### Update-Werkzeuge (Nachtrag vom 2026-10-24, nach dem ersten Test-Update)

- **Deploy und Rollback brachen ab**: `deploy.sh` schreibt `HOCX_BACKEND_WORKERS` ins
  Release-Manifest, der Env-Loader lehnte den Schlüssel ab. Ein Test prüft jetzt jeden
  Manifest-Schlüssel gegen die Allowlist.
- **Lokales S3 blieb uneingerichtet**: `storage-init` las den Garage-Admin-Token nur aus der
  Umgebung, Compose übergibt ihn als Secret-Datei (`GARAGE_ADMIN_TOKEN_FILE`). Garage blieb ohne
  Schlüssel und Buckets (AccessDenied). Eine Teilkonfiguration beendet `storage-init` jetzt mit
  Fehler, und die Smoke-Checks von `deploy.sh` führen es aus - ein Fehler führt zum Rollback.
- **`.env`-Migration**: leere Platzhalter aus `.env.example` (`STORAGE_CREDENTIALS_KEY=`) werden
  ersetzt statt den Schlüssel ein zweites Mal anzuhängen.
- `deploy.sh` verweigert einen Test-Candidate, dessen Commit der Checkout nicht enthält
  (neues Image mit altem Stack) - zuerst `./scripts/update_deploy_code.sh --deploy`.
- `deploy.sh` und `update_deploy_code.sh` prüfen vor jeder Änderung, dass der Checkout dem
  Deploy-Benutzer gehört, und nennen sonst den `chown`-Befehl für root. Vorher brach das Update
  mittendrin ab.
- Optionale, nicht versionierte `docker-compose.local.yml` für host-spezifische Anpassungen
  (Vorlage `docker-compose.local.example.yml`); wird überall automatisch mitgeladen.
- `deploy.sh` richtet den Cronjob `storage_controller` selbst ein (`HOCX_MANAGE_CRON=false`
  schaltet das ab).
- `verify_release.sh` prüft die Domains per `curl` mit SNI direkt gegen Traefik, ohne DNS;
  eigene CA über `HOCX_VERIFY_CA_FILE`. Private Hosts überspringen die Checks nicht mehr.
- `infra/garage/` ist Teil des signierten Deploy-Code-Nachweises.
- **Traefik-Rechte nach Code-Updates**: Git schreibt die versionierte
  `infra/traefik/dynamic/security.yml` als Deploy-Benutzer neu, danach brach `deploy.sh` mit
  «muss für die Container-Gruppe 5001 vorbereitet werden» ab. `deploy.sh` setzt die Gruppe 5001
  jetzt selbst, ohne root, über einen kurzlebigen Container aus dem geprüften Backend-Image.
- **`infra/traefik/letsencrypt`** gehört root mit Rechten 0711 statt 0700. Git erreicht die
  versionierte `.gitkeep` wieder, Traefiks `acme.json` (0600) bleibt geschützt. `deploy.sh` und
  `provision_deploy_user.sh` setzen die Rechte selbst.
- **Demo-Mandant (Testumgebung)**: Die Abgabe-Dateien des Demo-Mandanten verschwanden nach
  jedem weiteren Deploy. Der Seed schrieb sie unter festen Schlüsseln direkt auf die Platte, der
  Purge-Job entfernte sie über die Tombstones des gelöschten Vorgänger-Mandanten. Sie laufen
  jetzt über den Objektspeicher (auch bei S3) und liegen unter einem Schlüssel je Mandant.
- **Fester TOTP-Seed auf Testhosts**: `deploy.sh` erzeugt `DEMO_TOTP_SEED` auf Testhosts einmalig
  und behält ihn. Der Demo-Seed hinterlegt ihn für alle Demo-Konten und zusätzlich als Faktor
  «Dev-Seed» für jeden Plattform-Admin. Ein Authenticator-Eintrag reicht damit für Mandant und
  Admin-Seite, auch nach jedem Neuaufbau.

### Breaking Changes

- **PostgreSQL 18** statt 16, Daten in einem neuen Volume (`postgres18_data`, gemountet unter
  `/var/lib/postgresql`). `deploy.sh` und `scripts/dev.sh` ziehen bestehende Daten automatisch
  um (Update-Schritt 3); wer den Stack anders startet, muss das vorher selbst tun.
- Der TeX-Export ist entfernt (inkl. TeX Live im Backend-Image). Dokumentvorlagen werden
  automatisch zu **Brand-Profilen** des Document Studio (Migrationen `0115` und `0118`): Farben,
  Schrift (inkl. hochgeladener Schriften), Format, Kopf-/Fuss-/Titelseiten-/TOC-Variante,
  Nummerierung, Ort, Absender, Logo und Fussbild werden übernommen, ebenso TOC-Abstand, Farbe des
  Absenders, «Metadaten anzeigen» und die Kopfzeile «Logo mit Farbbalken». **Eigener
  Vorlagen-Code (Slots) entfällt ersatzlos**; betroffene Mandanten schreibt die Migration ins Log.
- Die Element-Option `latex_template` entfällt. Das Render-Format «Raw LaTeX» wird entfernt,
  sofern es nirgends verwendet wird; die PDF-Ausgabe richtet sich nur noch nach dem Element-Typ.
- API: `/api/exports/*` und die alten `/api/document-templates/*` sind entfernt, neu sind
  `/api/documents/*`, `/api/document-templates` (Document Studio), `/api/document-brands`,
  `/api/document-assets`, `/api/document-components`, `/api/document-template-assignments`,
  `/api/document-studio/*`, `/api/document-settings` und `/api/document-verification`. Die
  Dokumentverwaltung belegt `/api/documents/{uuid}…` (Details, Dateien, Text, Neuverarbeitung).
- Protokollvorlagen verweisen nicht mehr direkt auf eine Dokumentvorlage. Welche Vorlage und
  welches Corporate Design gelten, regeln Zuweisungen pro Dokumenttyp und Protokollvorlage.
- Mandanten-Export: Archivformat 7 mit Brand-Profilen, Assets, Vorlagen samt Revisionen,
  Komponenten, Zuweisungen, Export-Historie und Dokumentenregister. Archive der Formate 2-6
  lassen sich weiter importieren (alte Vorlagen und Hausstile werden umgewandelt). Die
  Verifizierung einer Organisation durch hocX wird nie mit importiert.
- Die Abgabebox-Datenbankrolle `hocx_abgabebox` liest von `tenant` nur noch `id` und
  `storage_quota_bytes` (vorher die ganze Tabelle).
- Abgabe-Link-Tokens können nicht `verify` lauten (Route der Prüfseite).
- Protokoll-PDFs, die Version eines logischen Dokuments sind (Dateien-Tab), fallen nicht mehr
  unter `EXPORT_RETENTION_DAYS` und die Regel «nur die neueste Datei je Protokoll»; nur ersetzte
  Darstellungen (gleicher Inhalt neu exportiert) und Exporte ohne Protokollbezug werden
  freigegeben. Das Speicherkontingent wächst dadurch mit jeder inhaltlich neuen Protokollfassung.
- Aus den Audits (Details in den Abschnitten unten): Mandanten-Export ist `POST` und liefert ein
  verschlüsseltes Archiv; der PDF-Export (`POST /api/documents/render`) antwortet mit `202` und
  einer Auftrags-ID statt mit der Datei; schreibende Requests mit fremdem `Origin` werden
  abgelehnt; Zugriffe auf fremde Datensätze antworten wegen Row-Level-Security teils mit `404`
  statt `403`; das Domain-Bridge-Token steht im URL-Fragment. Entfernt:
  `PATCH /api/admin/tenants/{id}/storage-quota`,
  `POST /api/submission-assignments/{id}/sync-todos`, `GET /api/tools/word-import/quality-stats`
  und `POST/GET /api/files/analysis-jobs`.

### Neu: Anliegen für kommende Sitzungen

- Neuer Bereich **Arbeiten → Anliegen** (Seite `/agenda`). Ein Anliegen hat Titel und Text und
  gehört zu einer Protokollvorlage und einem ihrer Traktanden. Das Popup wählt die zuletzt
  verwendete Vorlage vor (gespeichert je Person). Als Termin gilt entweder *nächste Sitzung* oder
  ein Monat («ab November 2026»).
- Das Anliegen erscheint ohne eigenen Block im Vorlagen-Aufbau im nächsten Protokoll der Vorlage,
  das *geplant* oder *vorbereitet* ist und ab dem Termin datiert. Dort steht es unter seinem
  Traktandum; ohne passendes Traktandum unter «Weitere Anliegen». Im Editor lassen sich Titel und
  Text direkt ändern, das Anliegen vertagen (neuer Termin) oder löschen. Den Ersteller zeigt nur
  die Liste, nicht änderbar.
- Im Mini-Menü des Editors (Sitzung läuft) erfasst *Anliegen erfassen* ein Anliegen direkt im
  aktuellen Protokoll, standardmässig unter dem gewählten Traktandum.
- Beim Wechsel auf *durchgeführt* gehören die angezeigten Anliegen fest zum Protokoll (Liste:
  *behandelt*). Nach dem Abschluss sind sie schreibgeschützt. Im Protokoll-PDF stehen sie unter
  ihrem Traktandum.
- Mit in Mandanten-Export/-Import/-Klon und in der Datenauskunft (selbst erfasste Anliegen).
  Migration `0153_agenda_item`: Tabellen `agenda_item` und `user_agenda_template_preference`,
  beide mit RLS. Benutzerdoku: `docs-site/docs/benutzer/anliegen.md`.

### Neu: Designs für Protokolle (Nachtrag vom 2026-10-25, ergänzt 2026-10-27)

- Sechs fertig gestaltete Designs: **Alpin**, **Kreide**, **Signal**, **Fokus**, **Siegel** und
  **Atlas**. Jedes gestaltet das ganze Dokument einheitlich: Titelseite (Farbband, Kennzahlen,
  Inhaltsverzeichnis oder Traktandenliste, Verteiler, Fussbild), Kopf- und Fusszeilen,
  Überschriften, Tabellen und die Darstellung **aller** Elemente.
- Gewählt wird das Design beim Anlegen über **Neue Vorlage** bzw. den Katalog. Die Vorlage
  erscheint mit den Farben, dem Logo und den Angaben des Vereins (seit «Gestaltung auf Abruf»
  ohne eigenes Brand-Profil, siehe oben). Der frühere Dialog **Beispiele** entfällt.
- Im Brand Studio sind die sechs Designs die Grundstile. Die bisherigen Grundstile
  «Abgerundet», «Kräftig» und «Schlicht» bleiben für Profile erhalten, die sie nutzen, stehen
  aber nicht mehr zur Wahl.
- Neue Darstellungen für Text, feste Texte und Anzeigen (Hinweis-Kasten, Akzentlinie),
  Aufzählungen (Nummern, Striche, Kästchen), Bilder (Rahmen, Karte), Diagramme (Rahmen) und Ein-
  und Austritte (nebeneinander). Damit hat jeder Baustein eines Protokolls eine Darstellung.
- **Bausteine einzeln gestalten:** In der PDF-Gestaltung einer Sitzungsvorlage listet der
  Designer unter «Protokollinhalt» deren Traktanden und Bausteine. Ein Baustein übernimmt die
  Darstellung des Dokuments und lässt sich je Elementart abweichend darstellen. Die Einstellung
  gehört zur Gestaltung (Entwurf, Vorschau, Veröffentlichen). Die Darstellungs-Auswahl im
  Sitzungsvorlagen-Editor entfällt; dort führt ein Link in die PDF-Gestaltung.

### Geändert: Vorlagen-Editor einer Protokollvorlage (Nachtrag vom 2026-10-27)

- Zwei Spalten statt drei: links die Traktanden mit ihren Bausteinen, Verantwortlichen als
  Avatare und Pfeilen zum Umsortieren, darunter «+ Neues Traktandum» und «Aus «Meine
  Bausteine» einfügen»; rechts ein Panel mit «Meine Bausteine» (inkl. Verwendungen), dem
  gewählten Traktandum (Titel, Einladung, Verantwortliche, Bausteine, Wiederverwenden) oder
  dem gewählten Baustein (Inhalt bearbeiten, «Wo und wie» als Schalter, Darstellung im PDF).
- Kopf mit Nummer-Muster, Teilnehmenden-Zähler und Bussentarif («eigener»/«Mandant»); die
  Tabs PDF und Einladung zeigen, ob die Gestaltung gemeinsam oder eigen ist.

### Neu: Funktionsvergleich auf der Landing Page (Nachtrag vom 2026-10-27)

- Unter den Preiskarten zeigt «Alle Funktionen im Vergleich» alle buchbaren Abos als Spalten:
  Preis pro Monat und Jahr, Benutzer, Speicher und jedes verkäufliche Feature, nach
  Produktmodul gruppiert (✓ enthalten, «zubuchbar» mit Monatspreis oder –).
- Die Daten kommen bei jedem Aufruf aus der Datenbank (`GET /api/public/plan-comparison`,
  öffentlich, ohne interne Felder): Änderungen an Abos, Preisen und Features im Adminportal
  sind sofort sichtbar. Preiskarten und Tabelle nutzen denselben Abruf.
- `features_generated.py` enthält jetzt die Produktmodule (`MODULES`) in fester Reihenfolge.

### Neu: Modus «Einfach» im Dokument-Designer (Nachtrag vom 2026-10-27)

- Der Designer startet im Modus **Einfach**: drei Schritte (Aussehen, Inhalt, Seite), die
  PDF-Vorschau ist die Arbeitsfläche. Ein Klick in die Vorschau öffnet den passenden Baustein,
  bei Protokollen auch einzelne Bausteine eines Traktandums mit ihrer Darstellung.
- **Aussehen:** Stilkarten mit den sechs Designs, Logo, Hauptfarbe, Schrift - nur für diese
  Vorlage (neue Felder in `BrandOverrides`: `appearance_base`, Kopf-/Fusszeilen-Schalter,
  Fusszeilentext).
- **Inhalt:** Bausteine mit Ein/Aus, Reihenfolge und 1–3 Einstellungen in Alltagssprache
  (Beschreibung in `backend/app/documents/simple.py`), fertige Bedingungen statt Regel-Editor,
  «+ Baustein hinzufügen» mit acht häufigen Bausteinen; frei gestaltete Bereiche bleiben als
  «Eigener Bereich» erhalten.
- **Seite:** Titelseite, Kopf- und Fusszeile, Hoch-/Querformat.
- Werkzeugleiste reduziert (Name, Status, Speicherstand, Rückgängig, «Erweitert öffnen»,
  Veröffentlichen). Wer kein Corporate Design verwaltet, startet immer im Einfach-Modus.
- Vorschau: `node_boxes` (Positionen der Knoten per Typst-Query), Server-Cache gerenderter
  Vorschauen, kürzere Entprellung im Einfach-Modus. Die Seitenvorlagen der Designs folgen jetzt
  den Kopf-/Fusszeilen-Schaltern.

### Neu: Dokument-Engine und Document Studio

- **Document Studio** (Navigation «Dokument-Studio», eigenes Icon zur Unterscheidung von «Dateien»):
  - **Vorlagen:** Bibliothek mit 26 mitgelieferten Vorlagen für alle 16 Dokumenttypen
    (Protokoll in fünf Varianten), eigene Vorlagen und angepasste Kopien, Entwurf und
    Veröffentlichung, Versionen vergleichen und wiederherstellen, Standardvorlagen pro
    Dokumenttyp und Protokollvorlage.
  - **Visual Designer:** Elemente per Drag-and-drop, Struktur, Datenfelder aus hocX mit Format
    und Ersatztext, Bedingungen und Wiederholen ohne Code, Seitenvorlagen, Titelseite,
    Wasserzeichen, Inhaltsverzeichnis, drei Modi (Einfach, Erweitert, Experte), Undo/Redo,
    Autosave mit Konflikterkennung, verbindliche PDF-Vorschau mit Beispiel- oder echten Daten.
  - **Corporate Design (Brand Studio):** mehrere Profile mit Farben, Schriften, Logos,
    Seitenaufbau, Angaben zur Organisation und Prüfvermerk, Live-Vorschau, Versionen.
  - **Bilder und Schriften**, **wiederverwendbare Komponenten**, **Export-Verlauf**.
- Ein Export-Dialog für alle Dokumente (Protokolle, Todos, Termine, Listen, Statistik): Vorlage
  wählen, Vorschau mit echten Daten, Optionen, PDF oder Zusatzformat (CSV, XLSX, ICS, Markdown).
- Fachkomponenten u. a. Monatskalender, Agenda, Präsenzliste zum Unterschreiben,
  Mitgliederliste, Kennzahlen-Kacheln, Diagramme als Vektorgrafik, QR-Code, Unterschriftsfelder.
- Datenfelder werden beim Export mit den Rechten der exportierenden Person gefüllt (z. B.
  Finanzdaten nur mit Finanz-Feature, Listen und Mitgliederdaten nur für Schreibende).
- Dokumentsprache pro Verein, pro Export änderbar; alle festen PDF-Texte in allen Sprachen.
- PDFs als PDF/A-2b; Metadaten (Dokument-ID, Typ, Version, Inhalts-Hash, Prüf-URL, Mandant nur
  bei freigegebener Anzeige) im XMP.
- **Dokumentenregister und Echtheitsprüfung:** Jedes PDF wird mit seinem SHA-256 registriert und
  trägt (je nach Corporate Design) Prüf-URL, Kurz-ID und QR-Code. Die öffentliche Prüfseite
  `/verify` der Abgabebox zeigt ohne Konto, ob eine Datei unverändert aus hocX stammt, mit
  Status, Version, Hinweis auf eine neuere Version, einem beim Export überschriebenen Titel und
  importierten, nicht verifizierten Einträgen. Die Datei verlässt dabei nie den Browser.
- **Mandanten-Einstellungen → Echtheitsprüfung:** Name und Logo auf der Prüfseite anzeigen (Standard aus), auf
  neuere Versionen hinweisen (Standard an), Verifizierung durch hocX beantragen, Vorschau.
- **Adminportal → Verifizierungen:** Anträge bestätigen oder ablehnen, Verifizierung entziehen;
  eine Namensänderung hebt sie automatisch auf. Bestätigte Organisationen erhalten auf der
  Prüfseite das Abzeichen «Verifizierte Organisation».
- Version steigt nur bei geändertem Inhalt (Inhalts-Hash). Eine andere Vorlage, ein anderes
  Corporate Design oder eine andere Sprache erzeugt keine neue Version (Design-Hash separat); die
  erste Endfassung ist immer v1.0. Jeder Export wird mit Vorlagen- und Brand-Revision protokolliert.
- Entwürfe tragen immer ein Wasserzeichen, ausser Schreibende schalten es ab.
- Render-Warteschlange begrenzt (HTTP 503 statt Stau), abgebrochene Vorschauen beenden das
  Warten, Vorschau und Thumbnails rastern nur die benötigten Seiten.
- Systemcheck «Öffentliche Prüfseite» inkl. ntfy.
- CI: visuelle Regressionstests (Golden-Bilder), Galerie-PDF als Artefakt, Katalogprüfung inkl.
  aller Studio-Texte.

### Neu: Eigene Prüf-Domain je Mandant

- Neues Feature **«Eigene Prüf-Domain»** (`verify_domain`), im Adminportal unabhängig von
  «Eigene Domain» Plänen oder einzelnen Mandanten zuzuordnen (keinem Plan vorbelegt). Mandanten
  richten unter Domains eine Domain mit dem Zweck **Prüfseite** ein (z. B. `verify.verein.ch`, DNS
  wie bei den anderen Domains).
- Die Prüfseite unter dieser Domain zeigt Logo und Name des Vereins; seine Dokumente erhalten die
  Stufe «Prüf-Domain verifiziert», schwächer als «Verifizierte Organisation».
- Neue PDFs verweisen in Prüfvermerk, QR-Code und XMP auf die Prüf-Domain. Die zentrale Prüfseite
  leitet Dokumente solcher Vereine automatisch weiter (mit «Hier bleiben»), ohne dass die Datei
  erneut ausgewählt werden muss; fremde Dokumente gehen von einer Vereinsseite weiter zur
  richtigen Prüf-Domain bzw. zu hocX. Voraussetzung: Name und Logo sind freigegeben.
- Migration `0126_verify_domain`; neuer Endpoint `GET /api/public/verify/site` (Abgabebox).
  Optional `DOCUMENT_VERIFY_BASE_URL` jetzt auch für `abgabebox-backend`.

### Neu: Cashflow im Adminportal

- Adminportal **Mandanten → Cashflow** mit drei Bereichen. **Kosten:** fixe Ausgaben mit
  Abo-Datum (monatlich, jährlich oder einmalig, optional mit Enddatum) und prozentuale Ausgaben
  wie Zahlungsgebühren, die von jeder bezahlten Forderung abgehen. Jede Ausgabe ist **aktiv**
  (wird verrechnet) oder **geplant** (nur in der Rechnung «inkl. geplanter Kosten»).
- **Forderungen:** was jeder Mandant je Abrechnungsperiode schuldet, ohne echte Rechnung.
  Sie entstehen automatisch ab dem neuen Feld **Abo-Start** (Tab «Plan & Abo», leer =
  Erstellungsdatum). Der Betrag (Plan + Zusatzmodule − Rabatt + Speicherpakete) wird beim
  Entstehen festgehalten und lässt sich bei offenen Forderungen neu berechnen. Status **offen**,
  **bezahlt** (mit Zahlungsdatum) oder **erlassen**; nur bezahlte zählen als Einnahme.
- **Überfällig:** offene Forderungen, deren Zahlungsfrist (30 Tage ab Periodenbeginn) abgelaufen
  ist; eigener Filter und Hinweis in Liste und Übersicht.
- **Mandanten sehen ihre Forderungen** unter Mandanten-Einstellungen → Abo & Nutzung (nur
  Mandanten-Admins, auch mobil): Periode, Betrag, Fälligkeit, Status bezahlt, offen, überfällig
  oder erlassen, Zahlungsdatum. Interne Notizen des Betreibers bleiben verborgen. Neuer Endpoint
  `GET /api/tenants/{id}/charges`.
- **Übersicht:** Einnahmen, Ausgaben und Ergebnis des Jahres, Bilanz seit Beginn (real und mit
  geplanten Kosten), Monatsrechnung nach aktuellem Stand, Verlauf je Monat mit Prognose.
- Migration `0127_cashflow` (Tabellen `cashflow_cost`, `tenant_charge`, Spalten
  `tenant.billing_start_date`/`billing_charged_until`). Beim ersten Öffnen entstehen für alle
  Mandanten mit Preis die Forderungen seit Erstellung zum heutigen Preis: falls das nicht stimmt,
  den Abo-Start setzen (offene Forderungen werden neu erzeugt) oder alte Forderungen erlassen.

### Neu: Notizen und Dateien an Todos

- Im Todo-Popup der Todo-Liste gibt es ein Feld **Notizen** mit demselben Markdown-Editor wie im
  Protokoll (fett, kursiv, Listen) und den Bereich **Dateien**: bereits hochgeladene Dateien
  (Dateien- und Fotos-Seite) lassen sich per Suche verknüpfen, öffnen und wieder entfernen.
  Gespeichert wird mit «Speichern».
- Notizen und Dateien erscheinen bewusst nur im Popup, nicht in Liste, Übersicht, Protokoll oder
  Exporten. Wird eine Datei gelöscht, verschwindet nur ihre Verknüpfung.
- Migration `0128_todo_notes_files` (Spalte `protocol_todo.notes`, Tabelle `protocol_todo_file`);
  Endpoints `GET`/`PUT /api/protocol-todos/{id}/details`. Mandanten-Export, -Import und -Klon
  übernehmen beides.

### Neu: Objektspeicher (S3), Live-Migration und Wartungssystem

- Alle persistenten Dateien (Uploads, Abgabebox inkl. Quarantäne, Document-Studio-Assets,
  erzeugte PDFs, Dateien logischer Dokumente, Mandantenlogos, Klon-/Import-Dateien) laufen über
  eine einheitliche Objektspeicher-Abstraktion (Dateisystem oder S3: AWS, Hetzner, Garage,
  S3-kompatibel).
- Lokales S3 (Garage v2.3.0) wird beim Deployment automatisch bereitgestellt; ein Host-Controller
  stoppt es nur, wenn es nachweislich nicht mehr gebraucht wird, und löscht nie Daten.
- Adminportal **System → Storage**: verschlüsselte Speicherprofile, Verbindungstest,
  Erstmigration (in voller Wartung) und Live-Migrationen mit Änderungsjournal, Prüfung,
  Schreib-Fence und atomarem Cutover in neue Speichergenerationen; Fortschritt, Raten, Restzeit,
  Heartbeat, Verlauf, Prüfbericht, Bereinigung alter Generationen.
- Adminportal **System → Wartung**: Wartungsfenster planen/starten/beenden; Freigabe nur bei
  erfüllten Bedingungen. Serverseitige Sperre (503 + Retry-After, WebSocket 1013) für Backend
  und Abgabebox, Wartungshinweis auf der Anmeldeseite, konservative Dauerabschätzung.
- Gelöschte Dateien werden erst nach dem Commit physisch entfernt (Tombstone + Job
  `storage_purge`): scheitert eine Löschung in der Datenbank, bleibt die Datei erhalten.
- Die Adresse eines S3-Endpunkts wird bei jeder Verbindung neu aufgelöst und geprüft
  (Schutz vor DNS-Rebinding auf interne Ziele).
- Neue Jobs: `storage_migration_worker`, `maintenance_supervisor`, `storage_journal_cleanup`,
  `storage_purge`, `storage_controller`, `backup_storage`; neue Systemprüfungen
  `object_storage`, `storage_migration`.

### Neu: Offsite-Backup mit BorgBackup

- Dienst `backup-worker` (einziger Dienst mit Borg-Schlüssel und -Passphrase): verschlüsselte,
  deduplizierte Backups von Datenbank und allen Objekten auf eine Hetzner Storage Box
  (append-only), inkrementelle Objektsicherung, Retention, Integritätsprüfung und monatlicher
  Restore-Test.
- Konsistente Sicherung im laufenden Betrieb: Während eines Backups sichert jeder Schreiber und
  der Purge-Job den bisherigen Inhalt eines Objekts vor dem Überschreiben bzw. Löschen
  (Copy-on-Write-Hold).
- Adminportal **System → Backups**: Status, Einstellungen, Sicherungspunkte, Wiederherstellung
  eines Mandanten **als Kopie** oder **vollständig** (Rettungspunkt, isolierte Datenbank, neue
  Speichergeneration, Tausch mit automatischem Rücktausch), jede Wiederherstellung mit frischer
  TOTP-Bestätigung; Recovery-CLI für den Notfall ohne laufende App.
- `deploy.sh` legt vor den Migrationen ein geschütztes Backup an, sobald Borg eingerichtet ist
  (`HOCX_PRE_DEPLOY_BACKUP`, `..._ALLOW_PARTIAL`, `..._TIMEOUT`).
- Neue Systemprüfungen `backup`, `backup_repository`, `backup_verification` inkl. ntfy.

### Neu: Dokumentverwaltung mit PDF-Ansicht und Textextraktion

- Hochgeladene Dokumente (Dateien-Tab, Word-/PDF-Import, Abgabebox) sind logische Dokumente:
  genau ein Eintrag im Dateien-Tab, bevorzugt als PDF angezeigt. Originaldatei, extrahierter
  Text und ältere Versionen stehen in den Dokumentdetails.
- Automatische PDF-Konvertierung (LibreOffice, isoliert) und formatspezifische Textextraktion
  (PDF, DOCX, DOC, ODT, RTF, TXT, Markdown, CSV, XLSX; OCR für gescannte PDFs) im neuen Dienst
  `document-worker`, mit persistenten Aufträgen, Wiederholungen und Statusanzeige. Der
  Dateien-Tab zeigt laufende Verarbeitung unter dem Dateinamen samt Stufe («Wird verarbeitet ·
  Virenprüfung / PDF-Ansicht / Texterkennung», `DocumentSummary.processing_stage`); Filter und
  Tabelle in einer Karte, Download und Teilen als Symbol-Buttons.
- Einheitliches, versioniertes Inhaltsformat (`hocx.document-content` v1) als Grundlage für das
  spätere Zusammenführen mehrerer Dokumente.
- **Protokollexporte der Dokument-Engine** bilden je Protokoll und Dokumenttyp ein Dokument mit
  Versionshistorie (neue Version nur bei neuem Inhalt); der Dateien-Tab zeigt die aktuelle
  Version (Filter «Protokollexporte»).
- Bestehende Dateien und Exporte werden automatisch übernommen (`document_sync`, wiederholbar).
- Neue Jobs `document_sync`, `document_worker`; neue Systemprüfung `document_queue`
  (gestaute oder endgültig gescheiterte Aufträge, inkl. ntfy).

### Neu: Bild-Metadaten und Vorab-Abgleich beim Upload

- Bild-Upload prüft Bilder vorab im Browser (Web Worker): SHA-256, Aufnahmedatum,
  Zeitzone, GPS, Kamera, Abmessungen, Ausrichtung – für JPEG, PNG, WebP, TIFF und HEIC/HEIF.
  Bereits vorhandene Bilder werden nicht erneut übertragen (`POST /api/files/upload-precheck`);
  fehlende Metadaten vorhandener Bilder werden dabei ohne Upload ergänzt. Auch Dokumente und
  Protokollbilder nutzen den Vorab-Abgleich (nur Hash).
- Drei getrennte Datumsarten: echtes Aufnahmedatum, neues **geschätztes Aufnahmedatum**
  (reines Kalenderdatum) und Uploaddatum. Galerie-Sortierung, -Gruppierung und Bilddetails
  folgen zentral dieser Reihenfolge; geschätzte Daten und der Uploaddatum-Fallback sind in den
  Datumsüberschriften mit einer beschrifteten Pille gekennzeichnet («Geschätztes Datum»,
  «Uploaddatum», bei gemischten Tagen mit Anteil).
- Upload-Popup: Hinweis und optionales Schätzdatum für Bilder ohne Aufnahmedatum, Ordner per
  Drag & Drop oder „Ordner auswählen“, automatische Aufteilung grosser Auswahlen in Aufträge zu
  höchstens 50 Dateien, Abbrechen während der Übertragung.
- Upload-Ergebnis je Datei: Hochgeladen, Übersprungen, Übersprungen · Metadaten ergänzt,
  Fehlgeschlagen – mit Zusammenfassung und Detailliste; Upload-Fehler übersetzt (Fehlercodes).
- Bilddetails: Aufnahmedatum als eigener Kasten oben (Herkunft «aus EXIF», geschätzt mit «Ändern»
  oder unbekannt), übrige Angaben in festem Raster. Echtes Aufnahmedatum (in Kamerazeit, mit Offset), geschätztes Datum
  (bearbeiten/entfernen, `PATCH /api/stored-files/{id}/capture-date`; nur bei Bildern ohne
  echtes Aufnahmedatum), Uploaddatum und Standort getrennt.
- GPS-Daten werden gespeichert (Breite, Länge, Höhe, Blickrichtung, Genauigkeit, Herkunft).
  **Standort je Album-Freigabe schaltbar:** Freigaben an Partner-Mandanten teilen ihn
  standardmässig, Freigabe-Links nicht; ohne Freigabe entfernen Downloads, Vorschau und
  Live-Photo-Clips den Standort.
- Downloads, Mehrfachdownload und Freigabe-Links schreiben ein geschätztes Datum in EXIF/XMP
  einer temporären Kopie, wenn kein echtes Aufnahmedatum existiert; Originale bleiben
  unverändert.
- Abgabebox und Protokollbilder speichern Aufnahmedatum, GPS und Kamera beim Upload.
- Gezielter Metadaten-Backfill für ältere Bilder (fortsetzbar, wiederholbar, mit Auswertung).
- Ein nur geschätztes Datum führt nie zu einer automatischen Termin-Zuordnung; Aufnahmezeiten
  werden in der Detailansicht nicht mehr um die App-Zeitzone verschoben.

### Datenschutz (Datenschutz-Audit vom 2026-10-21, Paket 1)

- **Statistik:** Bussen und Anwesenheit je Person sehen nur noch Schreibende, Kassier und Admins.
  Leser sehen dort ihre eigenen Werte, auch in PDF-Diagrammen. Mandanten-Admins können die
  Ranglisten unter Mandanten-Einstellungen → Datenschutz für alle freigeben (Migration `0138`,
  standardmässig aus). Finanzzahlen in der Statistik nur noch mit gebuchtem Modul Finanzen.
- **Fehlerprotokoll:** keine Werte aus SQL-Parametern oder Postgres-Details mehr
  (`hide_parameters`, Redaktion von E-Mail-Adressen). Der Auslöser wird als Konto-ID gespeichert
  und beim Anzeigen aufgelöst; nach dem Löschen eines Kontos bleibt keine Adresse zurück
  (Migration `0139`, leert bestehende Adressen). Fehler werden dem Mandanten des Kontos zugeordnet.
- **Kalender-Abos** übertragen standardmässig nur Titel und Datum (Migration `0140`, bestehende
  Abos unverändert).
- **Offline-Entwürfe** im Browser gehören dem angemeldeten Konto und werden beim Abmelden
  gelöscht (Rückfrage bei ungesendeten Änderungen).
- **Freigabelinks:** gelöschte Fotos verschwinden aus Dateilinks; ein Dateilink liefert nur Dateien
  seines Mandanten.
- **Fristen** für Upload- und Analyse-Jobs (30 Tage), Abgabebox-Uploadverlauf (90 Tage),
  Betriebsereignisse (2 Jahre), entschiedene Verifizierungsanträge und Word-Import-Lernsignale
  (1 Jahr) sowie widerrufene/abgelaufene Freigabelinks (90 Tage); Job `log_cleanup`.
  Die Prüfkopie zusammengeführter Bussen aus Migration 0116 wird entfernt (Migration `0141`).
- **Dumps:** Pre-Deploy-, Cron- und Restore-Sicherungen werden mit einem öffentlichen GPG-Schlüssel
  verschlüsselt (`BACKUP_DUMP_PUBLIC_KEY_PATH`, RUNBOOK Abschnitt 10), Pre-Deploy-Dumps nach
  30 Tagen entfernt. Unverschlüsselte Dumps gehen nur auf ein rclone-crypt-Remote, alte
  Offsite-Kopien werden gelöscht.
- Backends schreiben kein Access-Log mehr (Pfade enthielten Link-Tokens).

### Datenschutz (Paket 2: vollständige Dateilöschung)

- **Protokoll löschen:** ein Dialog zeigt die Bilder des Protokolls; standardmässig werden sie
  mitgelöscht, abgewählte wandern mit Tag «Protokoll …» in die Galerie. Bilder, die noch ein anderes
  Protokoll verwendet, bleiben. Erzeugte PDFs verschwinden mit. Vorher blieben alle Bilder liegen.
- **Abgabe löschen:** gleicher Dialog für eingereichte Dateien und Galeriefotos der Abgabe;
  behaltene Einreichungen werden aus dem Abgabebox-Speicher in die Galerie übernommen.
- **Einzelne Einreichungen** lassen sich im Abgabe-Detail löschen (z. B. auf Wunsch der
  einreichenden Person), samt Vorschau, Dokumenten, Album- und Linkeinträgen.
- Eine gemeinsame Löschfunktion räumt bei jeder Dateilöschung Objekt, Vorschaubild, Dokumente,
  Album- und Freigabelink-Einträge ab. `/admin/system` meldet Dateien, die zu nichts mehr gehören.

### Datenschutz (Paket 3: Sicherheitsprotokoll)

- **Audit-Log:** fehlgeschlagene Anmeldungen (App, MFA, Plattform-Admin), Plattform-Logins,
  hinzugefügte MFA-Faktoren und Einblicke des Plattform-Supports in Mandantendaten werden
  protokolliert. Statt IP-Adressen steht ein gekürzter, gehashter Netz-Fingerabdruck (`ip_hash`),
  dazu `outcome` (Migration `0143`). Die App-Rolle darf das Protokoll nicht mehr ändern oder löschen;
  Aufbewahrung (mindestens 30 Tage) und das Entfernen von E-Mail-Adressen gelöschter Personen bzw.
  Mandanten laufen über eigene DB-Funktionen.
- **Verlauf für Mandanten-Admins** unter Mandanten-Einstellungen → Verlauf (nur eigener Mandant,
  Plattform-Zugriffe als «Plattform-Support»), **Plattform-Ansicht** unter `/admin/audit` (Owner).
- **Sicherheitsalarme:** neuer Check `security` in `/admin/system` und ntfy (viele fehlgeschlagene
  Logins, auffällig viele Exporte, Restores, Admin-Änderungen; Schwellen per `SECURITY_*`, RUNBOOK).
- Mandanten löschen liefert einen Bericht (Personen, Dateien, Fehler beim Objektlöschen).

### Datenschutz (Paket 4: Löschjournal)

- Endgültige Löschungen (Mandant, Person, Protokoll, Termin, Abgabe, Einreichung, Datei) landen im
  Löschjournal (Migration `0144`, nur Einfügen für die App-Rolle, Aufbewahrung ≥ 400 Tage). Ein
  Voll-Restore und eine Mandanten-Kopie wenden sie vor dem Umschalten erneut an, damit gelöschte
  Daten nicht aus dem Backup zurückkehren. Abschalten nur beim einzelnen Restore mit Begründung.
- **Behoben:** Termin oder Listeneintrag löschen entfernt jetzt auch die zugehörigen
  Abgabebox-Einreichungen samt Dateien (blieben vorher verwaist liegen).

### Datenschutz (Paket 5: Datenauskunft)

- **Datenauskunft je Person** (Personen → Menü → Datenauskunft, nur Admin) und **«Meine Daten»** im
  Profil: passwortgeschützte ZIP-Datei (AES-256) mit `Auskunft.xlsx` (ein Blatt je Bereich),
  `daten.json` und Lesehinweis. Enthält nur die eigenen Zeilen (Anwesenheit, Bussen, Aufgaben,
  Termine, Dateien, Sicherheitsereignisse, Erwähnungen in Protokolltexten), keine Zugangsdaten.
  Abruf wird protokolliert, Selbstauskunft max. 3× pro Stunde. Öffnen mit 7-Zip, Keka oder WinRAR
  (der macOS-Finder kann AES-ZIP nicht öffnen). Neue Abhängigkeit `pyzipper`.

### Datenschutz (Paket 6: Vereinsexport)

- **Vereinsexport** unter Mandanten-Einstellungen → Datenschutz (Mandanten-Admin, Anmeldung mit
  Zwei-Faktor-Bestätigung): AES-ZIP für die Weiterarbeit mit `Mitglieder.xlsx`, `Termine.xlsx`,
  `Anwesenheit.xlsx` (Person × Sitzung), `Bussen.xlsx`, `Finanzen.xlsx` (Blatt je Konto),
  `Aufgaben.xlsx`, `Listen/`, den PDFs abgeschlossener Protokolle und auf Wunsch `Fotos/`
  (nach Album bzw. Termin), `Abgaben/` und `Dokumente/` als Originaldateien. Namen statt IDs,
  Datum TT.MM.JJJJ, keine Zugangsdaten. Gebaut vom neuen Job `tenant_data_export` (Migration
  `0145`, RLS), danach 7 Tage abrufbar. Abgeschlossene Protokolle ohne gespeichertes PDF werden im
  Lesehinweis aufgeführt (nicht automatisch erzeugt).
- **Plattform-Export ohne Zugangsdaten als Standard:** Passwort-Hashes, MFA-Secrets und Link-/Abo-
  Tokens nur noch mit der neuen Option «Zugangsdaten mitexportieren» (`include_credentials`). Ohne
  sie erhalten importierte Konten ein zufälliges Passwort und Links neue URLs. Die Mandanten-Kopie
  aus dem Backup nimmt sie weiterhin mit.
- Datenauskunft: Passwort-Mindestlänge auch im API-Schema, Rate-Limit für die Admin-Auskunft,
  temporäre Dateien werden auch bei Fehlern gelöscht (Security-Review).

### Datenschutz (Paket 7: Korrekturweg abgeschlossener Protokolle)

- Abschliessen → zurückstufen → korrigieren → abschliessen: beim erneuten Abschluss verschwinden
  die Änderungsmarkierungen samt alter Fassung, die PDFs des früheren Abschlusses werden sofort
  gelöscht und ihre Registereinträge verlieren den Titel (nur der Prüfwert bleibt, die Prüfseite
  meldet sie als ersetzt). Beschrieben in der Benutzerdoku unter Protokolle.

### Datenschutz (Paket 8: Aufbewahrungsfristen je Verein)

- Neuer Tab **Mandanten-Einstellungen → Aufbewahrung** (Migration `0146`, RLS): Einreichungen der
  Abgabebox X Monate nach Abgabeschluss löschen, ehemalige Mitglieder X Jahre nach Austritt
  **deaktivieren** (Login aus, Sitzungen beendet, Daten bleiben), alte Galeriebilder ohne Album und
  Termin nach X Jahren vorschlagen. Alle Regeln standardmässig aus. Der neue tägliche Job
  `retention_proposals` legt Vorschläge an; der Admin setzt sie um oder verwirft sie, wahlweise
  automatisch (Galeriebilder nie automatisch). Löschung über die bestehenden Löschpfade mit
  Löschjournal und Verlauf.
- **Offboarding:** Vertragsende je Mandant im Adminportal (Abo); `/admin/system` meldet Mandanten
  nach Vertragsende plus `TENANT_OFFBOARDING_GRACE_DAYS` (Standard 90) zur Löschung (Check
  `tenant_offboarding`, gelöscht wird von Hand).

### Datenschutz (Paket 9: Abgabebox-Hinweise, GPS-Wahl, Speicherstandort)

- **Abgabebox:** vor dem Upload stehen der verantwortliche Verein, ein Link zu dessen
  Datenschutzhinweisen (Mandanten-Einstellungen → Datenschutz, sonst `ABGABEBOX_DEFAULT_PRIVACY_URL`)
  und ein Hinweis zu Friendly Captcha. Die Abgabebox liest Name und Link nur über die DB-Funktion
  `abgabebox_privacy_notice()` für den Mandanten ihres Links (Migration `0147`).
- **Friendly Captcha in der EU:** Puzzle- und Verify-Endpunkt per `FRIENDLY_CAPTCHA_PUZZLE_URL` /
  `FRIENDLY_CAPTCHA_VERIFY_URL` einstellbar (CSP folgt automatisch); `/admin/system` zeigt, ob der
  EU- oder der globale Endpunkt aktiv ist.
- **«GPS-Daten des Bildes mitsenden»** (Standard an) bei Galerie-Upload, Protokollbild (auch mobil)
  und Abgabebox. Aus: der Server entfernt vor dem Speichern nur die Standortangaben (EXIF-GPS in
  JPEG/HEIC/WebP/PNG/TIFF, XMP-GPS, Ortsangaben in Live-Photo-Clips) ohne Neukodierung; Datum,
  Kamera und Bild bleiben, die GPS-Spalten leer. Gespeichert wird mit GPS wie bisher.
- **GPS erst ab Rolle Schreiber:** Leser sehen keine Koordinaten in den Fotodetails und erhalten
  Originale ohne Standort.
- **Datenstandort der Speicherprofile:** Schweiz / EU-EWR / angemessen / Drittland, bei AWS und
  Hetzner aus der Region abgeleitet, bei S3-kompatibel gewählt. Drittland nur mit
  Übermittlungsgrundlage und Bestätigung, Migration dorthin fragt erneut nach; optional
  `STORAGE_ALLOWED_LOCATIONS`. Badge in `/admin/storage`. Neu: serverseitige Verschlüsselung (S3
  `AES256`) je Profil, im Verbindungstest geprüft.

### Stabilität unter Last (Concurrency-Audit vom 2026-10-21, Lasttest vom 2026-10-22)

- **Neuer Dienst `job-worker`** (Backend-Image): Galerie-Ingest, Qualitäts-Backfill,
  Vereinsexport, Album-Sync, Virenscan-Nachprüfungen, Thumbnail-Backfill und Aufräumjobs laufen
  nicht mehr in den Backend-Workern. Eigenes Budget (3 GiB / 1,5 CPU), Backend jetzt
  4 GiB / 2,5 CPU. `deploy.sh` startet und prüft ihn, Heartbeat unter `/admin/jobs`.
- **PDF-Export als Auftrag** (Migration `0150`): der Export antwortet sofort, der `job-worker`
  rendert reihum je Mandant, die Oberfläche meldet «PDF bereit» auch nach einem Seitenwechsel.
  Das automatische PDF nach Protokollabschluss läuft ebenfalls als Auftrag; dabei behoben, dass
  der Abschluss weder Audit-Eintrag noch PDF auslöste.
- **Typst-Renderer** mit eigenen Worker-Prozessen: ein Timeout beendet nur den betroffenen
  Compile, Exporte haben Vorrang vor Vorschauen und Thumbnails.
- **Keine Lost Updates in Protokollblöcken** (Migration `0149`): gleichzeitige Änderungen an
  derselben Blockkonfiguration enden mit einem Hinweis und dem aktuellen Stand statt still
  überschrieben zu werden; Anwesenheits-Klicks gehen nicht mehr verloren. Live-Updates aus
  Listen- und Anwesenheitsänderungen kommen bei anderen Bearbeitenden wieder an.
- **Uploads:** der Virenscan läuft ohne den Upload-Lock des Vereins (vorher warteten alle Uploads
  eines Vereins, auch die öffentliche Abgabebox, auf ClamAV); Galerie und Abgabebox nehmen mit
  begrenzten Plätzen an und lassen kurz warten statt sofort 503 zu melden, die Abgabebox
  wiederholt bei 503 automatisch. Galerie-Ingest reihum je Mandant.
- **Verbindungen kurz gehalten:** Downloads und Streams geben die DB-Verbindung vor der
  Auslieferung frei, Pools je Prozess einstellbar (`DB_POOL_*`), ein voller Pool antwortet mit
  503 `db_busy` und `Retry-After` statt nach 30 s mit 500; nichts Blockierendes mehr im
  Event-Loop.
- **Hintergrundjobs:** Singleton-Locks laufen nach 30 min nicht mehr ab (Jobs liefen doppelt),
  hängende Fotoanalyse-Aufträge werden nach 6 h beendet, Backup-Prüfung und Restore-Test nur im
  Nachtfenster (`BACKUP_HEAVY_WINDOW_HOURS`).
- **Redis/Kollaboration:** Timeouts, Feldsperren atomar, Redis-Ausfall blockiert das Speichern
  von Protokollen nicht mehr, `maxmemory` mit `noeviction` statt OOM-Kill.
- **Öffentliche Album-ZIPs** werden 10 min wiederverwendet und begrenzt gebaut, Abgaben-ZIPs auf
  der Platte statt im Speicher; Diagramme aktualisieren nur bei sichtbarem Tab und höchstens
  minütlich; Thumbnails auf Abruf begrenzt; Ähnlichkeitsgruppen mit Cache (Duplikate-Tab grosser
  Galerien vorher über 70 s).
- **Monitoring:** Laufzeitkennzahlen je Prozess (Migration `0148`: Event-Loop-Verzögerung,
  Pool- und Threadpool-Belegung) mit Check `runtime` und `render_queue` in `/admin/system`.
- **Behoben:** Abgabebox-Einreichungen im Dateisystem-Speicher waren für das Backend nicht lesbar
  (Dateien mit 0600 statt umask-Rechten), lokales S3 (Garage) startete im Release-Stack wegen
  der Rechte der Secret-Dateien nicht, Traefik-Admin brach grosse Mandantenimporte nach 60 s ab.
- **Request-Annahme je Backend-Worker:** höchstens so viele gleichzeitige Requests wie
  DB-Verbindungen (Standard 16), der Rest wartet kurz und bekommt erst nach 20 s ein 503
  `db_busy`. Vorher konnte der Server bei rund 250 aktiven Nutzern in einen Stau kippen, in dem
  fast jede Anfrage erst nach Sekunden mit 503 endete. Einstellbar über `DB_ADMISSION_*` (RUNBOOK).
- **Priorität bei Überlast je Abo:** Jeder Plan hat im Preiskatalog eine Priorität (niedrig,
  normal, hoch). Wird es knapp, sehen neue Nutzer von Abos mit niedriger Priorität zuerst eine
  Überlast-Seite, die automatisch weiterleitet, sobald wieder Platz ist. Wer bereits arbeitet,
  bleibt angemeldet. Wartende Anfragen werden nach Priorität bedient. Jede Abweisung wird
  protokolliert. Das Adminportal zeigt sie unter System → Überlast je Mandant und meldet sie als
  Warnung (Migration `0151`, `OVERLOAD_*` im RUNBOOK).

### Geändert (Nachtrag vom 2026-10-24)

- **Fotos: Duplikate und Ähnliche werden im Hintergrund gruppiert.** Die beiden Tabs rechneten
  bisher bei jedem Aufruf im Request (bis 1500 Bilder paarweise samt Originalen) und brachen bei
  grösseren Galerien mit «Ähnliche Fotos konnten nicht geladen werden» ab, weil der Browser nach
  15 s aufgab. Neu berechnet der `job-worker` (Job `photo_similarity_refresh`, Takt
  `PHOTO_SIMILARITY_REFRESH_INTERVAL_MINUTES`, Standard 2 Minuten) die Gruppen je Mandant, sobald
  sich dessen Fotos ändern, und legt sie in `photo_similarity_result` ab (Migration 0152). Die
  Tabs rufen nur noch das Ergebnis ab, zeigen den Stand der Berechnung und behalten es beim
  Tabwechsel. Gelöschte Fotos fallen sofort heraus, neue erscheinen nach dem nächsten Lauf. Bis
  zum ersten Lauf nach dem Update zeigen die Tabs «wird im Hintergrund gruppiert». Obergrenze
  10 000 Fotos je Mandant (statt 1500 je Filter).
- **Seitenleiste:** Das Dokument-Studio steht unter *Konfiguration* statt unter *Arbeiten*
  (sichtbar ab Schreibrecht).

### Behoben

- **Verlauf:** Aktionen mit mehreren Punkten (z. B. `backup.restore.create`) wurden falsch benannt.
- **Foto-Analyse:** Der Foto-Worker konnte seit Migration `0134` keine Dateien mehr laden
  (`permission denied for table submission_assignment`), die Gesichtsanalyse fiel aus. Korrigiert
  in Migration `0142`.

### Sicherheit (Security-Audit release/1.2.0 vom 2026-10-17)

- **Mandantenimport:** Album-Freigaben und Vertrauensbeziehungen zu anderen Mandanten werden
  nicht mehr aus dem Archiv übernommen. Eigene Alben gehen als neue Einladung an den Partner
  (Zustimmung erneut nötig), Freigaben fremder Alben fallen weg (Warnung beim Import).
- **Album-Freigaben, öffentliche Links:** zwei Schalter je Freigabe (Migration `0130`, beide
  standardmässig an): der Besitzer legt fest, ob der Partner das Album öffentlich verlinken darf,
  der Partner, ob seine Fotos in öffentlichen Links erscheinen. Öffentliche Links geben den
  Standort eines Fotos nur weiter, wenn der anlegende Mandant ihn auch intern sehen darf.
- Tags von Partner-Fotos aus geteilten Alben sind nicht mehr änderbar; Album-Einladungen sind
  auf 30 pro Stunde und Mandant begrenzt.
- **Custom-Domains:** eindeutig ist nur noch eine aktive Domain (Migration `0129`); eine
  unbestätigte Domain eines anderen Mandanten blockiert nicht mehr.
- Schreibende API-Requests mit fremdem `Origin` werden abgelehnt (CSRF-Schutz zusätzlich zu
  `SameSite=Lax`); offene Collaboration-WebSockets prüfen Session und Protokollrecht alle 30 s.
- Löscht ein Admin den MFA-Faktor eines anderen Kontos, enden dessen Sessions. Passkey-
  Registrierung prüft gegen die konfigurierte Domain (neu: `TRAEFIK_ADMIN_DOMAIN` im Backend).
- Abgabebox: Nonce-CSP statt `script-src 'unsafe-inline'`; die Ähnlichkeitswarnung vergleicht nur
  noch mit Bildern derselben Abgabe. Traefik setzt `Permissions-Policy`, Next.js kein
  `X-Powered-By` mehr. Fotoworker lädt nur Dateien des Job-Mandanten.
- Abhängigkeiten: PyJWT 2.15.1, Next.js 16.4.2, sharp 0.35.5, Tiptap 3 (inkl. tiptap-markdown 0.9).
- **Todos:** jedes Todo gehört fest seinem Mandanten (Migration `0131`, `protocol_todo.tenant_id`
  Pflicht); bei Todos in Protokollen setzt die Datenbank den Wert aus dem Protokoll. Behebt, dass
  Mandanten-Export und -Klon Todos aus Protokollen nicht mitnahmen. Todos ohne jeden Bezug (in
  keiner Ansicht erreichbar) werden bei der Migration entfernt.
- **Row-Level-Security** (Migration `0132`): PostgreSQL prüft die Mandantentrennung jetzt
  zusätzlich zum Code. Angemeldete Mandanten-Anfragen sehen und ändern nur Zeilen ihres Mandanten,
  auch wenn einer Abfrage der Filter fehlt; Ausnahmen sind die Daten gemeinsamer Fotoalben.
  Plattform-Admin, Hintergrundjobs, Worker und öffentliche Links bleiben unbeschränkt.
  Zugriffe auf fremde Datensätze antworten dadurch teils mit 404 statt 403.
- **Abgabebox unter RLS** (Migration `0133`): die öffentliche DB-Rolle sieht ohne Upload-Link
  nichts mehr und mit Link nur dessen Mandanten; gebunden wird das geheime Token, nicht die
  Mandanten-ID. Von `stored_file` liest sie nur noch Prüfsummen (keine Namen, Pfade, GPS-Daten).
- **Domain-Bridge:** das Einmal-Token steht im URL-Fragment statt in der Query und geht nur im
  Request-Body ans Backend (`POST /api/auth/bridge/preview`); Einlösen prüft zusätzlich
  `login_enabled` und eine seither erfolgte Session-Beendigung.
- **Lokales S3:** RPC und Admin-API von Garage nur noch auf `127.0.0.1`; `storage-init` teilt den
  Netz-Namespace von `local-s3`.
- **Datenbank-Performance:** Protokoll-, Todo- und Albenliste laden zugehörige Daten gesammelt statt
  je Eintrag (20 Einträge: 44 → 6, 41 → 4, 66 → 10 Abfragen; Session-Cache für public_ids, Tests
  gegen N+1). Migration `0135`: Indizes für 43 Fremdschlüssel (schnelleres Löschen von Konten und
  Mandanten, Abfragen je Zyklus/Abgabe/Vorlage) und Timeouts für die Laufzeitrollen (Abgabebox und
  Fotoworker erstmals mit statement_timeout, alle mit idle_in_transaction_session_timeout).
- **RLS für Untertabellen** (Migration `0134`): Mandantendaten ohne eigene `tenant_id`
  (Traktanden, Blöcke, Texte, Listeneinträge, Buchungen, Bussen, Vorlagen-Elemente, Album-Einträge,
  Dokumentversionen …) sind jetzt über ihre Elterntabelle geschützt; MFA-Faktoren nur im eigenen
  Mandanten.
- **Sicherheitsregeln für Menschen und AI-Agents:** `SECURITY-RULES.md` (über `CLAUDE.md` für alle
  Agents verbindlich, auch Gemini/Tabnine), `scripts/check-security-rules.py` meldet neu
  eingeführte Verstösse (ungescopte Lookups, SQL-f-Strings, `HTTPException` ohne `from exc`,
  Secrets in URLs, `dangerouslySetInnerHTML`) als Claude-Code-Hook, im Pre-Commit und in der CI
  (`security-lint`); Review-Agent `security-reviewer`.
- **Systemstatus, lokales S3:** neuer Eintrag „Lokales S3 (Garage)“ mit Bedarf (aktiver Speicher,
  Migration, Rückfallfrist, nicht benötigt …), Objektanzahl und belegten GB. Ein vom
  Storage-Controller gestopptes Garage gilt nicht mehr als Ausfall (vorher roter Container und
  ntfy-Alarm, sobald die Dateien bei einem anderen Anbieter liegen).
- **Mandanten-Exporte verschlüsselt:** ohne Passwort mit dem Server-Schlüssel (nur auf diesem
  Server importierbar), mit Passwort auch auf einem anderen Server. Neues Secret
  `EXPORT_ENCRYPTION_KEY`, das `deploy.sh` einmalig erzeugt; zusammen mit `.env` sichern. Ältere
  `.zip`-Exporte bleiben importierbar. Der Export-Endpunkt ist jetzt `POST`.
- **CI/Release:** `pip-audit` und `npm audit` (ab HIGH) blockieren; neue `public_id`-Lookups ohne
  `tenant_id=` blockieren Pull-Requests (Semgrep); Trivy-Scan vor jeder Image-Promotion und
  wöchentlich für die `latest`-Images.

### Korrekturen (Feature-Recovery-Audit v1.2)

- **Live-Photo-Videos nach ClamAV-Ausfall:** Der Nachscan (`upload_pipeline_rescan`) erfasst
  jetzt auch das Video eines Live Photos. Vorher blieb ein Clip, der beim Upload nicht geprüft
  werden konnte, dauerhaft `pending` und war nie abspielbar; betroffene Clips werden beim
  nächsten Lauf automatisch nachgeprüft.
- **Protokollkopf:** zeigt wieder Erstellungsdatum und Vorlagenversion des Protokolls (seit der
  neuen Ansicht für abgeschlossene Protokolle nirgends mehr sichtbar).
- Ungenutzte Komponente `SnapshotSwitcher` samt Texten entfernt.
- **Manuelles Speicherkontingent vollständig entfernt** (Migration `0136`): Der API-Endpunkt
  `PATCH /api/admin/tenants/{id}/storage-quota` und das Feld `storage_quota_manual_override`
  entfallen; das Kontingent ergibt sich nur noch aus Plan + Zusatzpaketen. Mandanten mit einem
  per API gesetzten Sonderwert (auch eine Einschränkung, die 0088 stehen liess) bekommen beim
  Update wieder Plan + Pakete; IDs und alte Werte stehen im Migrationslog.
- **Bussentarif je Protokollvorlage** (Migration `0137`): Im Vorlagen-Editor (Button
  «Bussentarif», nur mit Finanzen) kann eine Vorlage statt des Mandantentarifs eigene Beträge und
  ein eigenes Konto haben. Der Tarif gilt sofort für alle offenen Protokolle der Vorlage; bereits
  erfasste Bussen behalten ihren Betrag. Duplizieren, Klonen und Export/Import nehmen ihn mit.
  Ersetzt die Tarife je Anwesenheitsblock, die mit `0113` weggefallen waren.
- **Todos zu Abgaben entstehen automatisch:** beim Anlegen und Ändern einer Abgabe mit
  Verantwortlichen, bei Terminen mit passendem Tag und bei neuen/geänderten Listeneinträgen.
  Vorher bekamen Listen-Abgaben nie Todos und bestehende Termine erst nach einer Bearbeitung;
  Fehler beim Abgleich wurden verschluckt und landen jetzt im Fehlerprotokoll. Der nie
  angebundene Endpunkt `POST /api/submission-assignments/{id}/sync-todos` entfällt.
- **Adminportal «Dokumentvorlagen»** (`/admin/document-templates`): mitgelieferte Vorlagen des
  Document Studio ansehen, je Dokumentart den Plattform-Standard setzen, Vorlagen archivieren
  oder wieder anbieten (die Routen gab es schon, die Oberfläche fehlte).
- Entfernt, ohne Oberfläche: `GET /api/tools/word-import/quality-stats` (das Lernen der
  Schwellwerte im Word-Import bleibt) und `POST/GET /api/files/analysis-jobs` (die Fotoanalyse
  läuft automatisch nachts, `photo_analysis_auto_queue`).

### Abstimmung beim Zusammenführen (Release 1.2.0)

- Document Studio liest und schreibt Assets und erzeugte PDFs über den Objektspeicher (vorher
  direkt im Dateisystem - nach einer S3-Migration wären Logos, Schriften und PDFs verloren
  gewesen); Protokollbilder im PDF ebenso.
- Storage-Migration und `storage_verify` prüfen die Referenzen des Document Studio
  (`document_asset`) statt der entfallenen TeX-Vorlagen-Bauteile.
- Der Backup-Hold sichert auch noch nicht gelöschte Tombstones (Migration
  `0123_backup_hold_tombstones`) - sonst hätte der Purge-Job während eines Backups Inhalte
  gelöscht, die das Backup noch braucht.
- Downloads mit Standortschutz und Exportfassung (Bild-Metadaten) laufen über den
  Objektspeicher; Mandanten-Restore aus Borg prüft importierte Register-Einträge wie der
  ZIP-Import.
- `deploy.sh`: Rollback stoppt bzw. startet die Worker mit Backend-Image passend zum vorherigen
  Release; Smoke-Checks für `document-worker` und `storage-worker`.
- Migration `0118_docmgmt_storage_purge` ist ein No-op (doppelte Einführung desselben Verfahrens,
  die Fassung aus `0118_storage_purge_after_commit` behält die Rollenbindung der Abgabebox).

### Neu und geändert aus main (Audit-Reparatur seit 1.1.13)

- **Bussen:** mitgeführte Bussen mit Pflichtbegründung löschen (Soft-Delete, Anzeige im
  Protokoll, rückgängig solange offen), doppelte Bussen beim Update zusammengeführt und per
  Unique-Index ausgeschlossen, CHECK auf Status und Typ, offene Bussen aus abgeschlossenen
  Protokollen einkassierbar, Bussen-Buchungen und Konten mit Historie geschützt, Statistik je
  Währung.
- **Elemente:** einheitliches Konfigurationsschema, ein Block-Editor für Anlegen und Bearbeiten,
  gemeinsamer Terminfilter, zentraler Bussentarif, fehlende Optionen je Elementtyp.
- **Sicherheit:** Login-Sperre pro Konto und Quell-IP (Traefik als Trusted Proxy), Domain-Wechsel
  erst nach Bestätigung auf der Ziel-Domain, Nonce-CSP statt `unsafe-inline`, OIDC-state an den
  startenden Browser gebunden, Admin-SSO nur mit bestätigter E-Mail, Multipart nur mit
  signierter Session und Grössenlimit, localhost-Origins nur ausserhalb der Produktion,
  Profilbilder validiert und neu kodiert.
- **Betrieb:** Traefik liest Docker nur über einen Socket-Proxy, Lese-/Schreib-Timeouts 1 h,
  Body- und Inflight-Grenzen je IP; Redis mit Passwort; Images per Digest und Actions per SHA
  gepinnt (Dependabot); shellcheck in der CI.
- Zahlreiche Korrekturen in Uploads, Thumbnails, Mandanten-Import/-Klon, Autosave,
  Offline-Outbox, Kollaboration und Oberfläche (siehe Git-Historie).

### Betrieb

- Prod lief bisher mit `HOCX_ENVIRONMENT=prod` und damit für das Backend nicht als
  Produktion (offenes `/docs`/`/openapi.json`, Demo-Daten- und Konfigurationssperren aus).
  `deploy.sh` schreibt jetzt `production`, migriert eine bestehende `.env` beim nächsten
  Deploy automatisch (`prod` → `production`, Sicherung als `.env.bak-*`) und
  `verify_release.sh` prüft den Produktionsmodus. Backend und Frontend akzeptieren `prod`
  weiterhin als Alias.
- Neues `scripts/restore_db.sh` für das Zurückspielen eines Dumps (stoppt die DB-Dienste,
  sichert den aktuellen Stand, legt die DB neu an, spielt mit `ON_ERROR_STOP` in einer
  Transaktion ein). Die bisherige RUNBOOK-Anleitung (`gunzip | psql` in die laufende DB) ist
  ersetzt.
- `backup_db.sh`, `restore_db.sh` und `run_job.sh` verwenden explizit Compose-Projekt und
  -Dateien je Host-Markierung; ohne Markierung gilt `HOCX_COMPOSE_PROJECT` (Default `hocx`,
  für eine über `dev.sh` betriebene Instanz `hocx-dev`). `backup_db.sh` läuft jetzt auch auf
  Hosts ohne Markierung und meldet eine fehlgeschlagene Offsite-Kopie als Fehler.
- `deploy.sh` behält nur die neuesten 10 Pre-Deploy-Dumps (`PRE_DEPLOY_BACKUP_KEEP`) und nimmt
  auf Prod nur noch Release-Tags (`vX.Y.Z`) als `HOCX_VERSION`.
- Der Env-Loader von `deploy.sh` liest unquotierte Werte mit Inline-Kommentar und Escapes in
  doppelt quotierten Werten jetzt wie Compose.
- Redis hängt nur noch im internen Netz `cache` zwischen Backend und Redis.
- `docker-compose.dev.yml` setzt den Projektnamen fest auf `hocx-dev`. Wer den Dev-Stack bisher
  ohne `-p` gestartet hat, bekommt dadurch neue (leere) Dev-Volumes.
- `docker-compose.yml`: `HOCX_ENVIRONMENT` ist per `.env` steuerbar (Default `development`);
  `.env.example` setzt `ABGABEBOX_ENVIRONMENT` nicht mehr. Bestehende `.env`-Dateien einer
  Server-Instanz mit `ABGABEBOX_ENVIRONMENT=development` sollten den Eintrag entfernen.
- Basis-Stack nutzt Traefik v3.6.1 wie der Release-Stack.

## [1.1.13] - 2026-10-13

Feature-Release auf 1.1.12: Offene Protokolle lassen sich nach Änderungen an der Vorlage
neu aufbauen, ohne erfasste Daten zu verlieren; Terminlisten in Matrizen filtern nach
Zyklus und Protokolldatum. Keine Migration, keine neuen Umgebungsvariablen.

### Update von 1.1.12 auf 1.1.13

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.13` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.
Keine weiteren Schritte nötig.

### Neu

- Protokollliste: «Elemente aus Vorlage neu laden» im Drei-Punkte-Menü nicht
  abgeschlossener Protokolle. Übernimmt neue und entfernte Elemente, Titel, Beschreibungen,
  Vorgabetexte, Filter (z. B. Tag-Filter wiederholter Termin-Blöcke), Formularzeilen,
  Matrix-Zeilen/-Spalten und weitere Einstellungen aus der aktuellen Vorlage. Erfasste
  Texte, Todos, Bilder, Formular- und Matrixwerte, Anwesenheiten und ausgeblendete Blöcke
  bleiben erhalten; unveränderte Vorgabetexte folgen der Vorlage. Elemente und Blöcke, die
  nicht mehr in der Vorlage sind, werden nur entfernt, wenn sie leer sind, sonst bleiben
  sie am Ende stehen. Vor dem Anwenden zeigt eine Rückfrage, was sich ändert; offene
  Editoren desselben Protokolls laden danach neu.
- API: `POST /api/protocols/{id}/sync-template` (mit `?dry_run=true` nur Vorschau).
- Matrix-Designer: Terminlisten-Zeilen lassen sich auf einen Zyklus relativ zum
  Protokolldatum (aktueller, vorheriger, … Zyklus) und auf Termine vor dem Protokolldatum
  einschränken. Matrix-Zelle und PDF-Export filtern gleich; bestehende Einstellungen «Nur
  im aktuellen Zyklus» gelten als aktueller Zyklus.

## [1.1.12] - 2026-10-12

Feature- und Bugfix-Release auf 1.1.11 mit neu gestaltetem Matrix-Designer, Zyklus-Filter
für automatische Termin-Spalten, Todos, die nach dem Protokollabschluss bearbeitbar bleiben,
und mehreren Korrekturen am PDF-Export. Enthält die Migration `0112`; sie läuft beim Deploy
automatisch und ist umkehrbar. Keine neuen Pflicht-Umgebungsvariablen.

### Update von 1.1.11 auf 1.1.12

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.12` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.

- Migration `0112` ergänzt `protocol.todos_snapshot_json` (Todo-Stand beim Abschluss).
  Bereits abgeschlossene Protokolle haben keine Momentaufnahme und zeigen weiterhin den
  aktuellen Stand ihrer Todos, bis sie erneut abgeschlossen werden.
- Optional: `HOCX_APP_URL` (z. B. `https://app.hocx.ch`) bestimmt das Ziel von «Anmelden»
  auf der Website. Leer oder nicht gesetzt gilt weiterhin `https://${TRAEFIK_DOMAIN}`.

### Neu

- Todos bleiben nach dem Abschluss ihres Protokolls bearbeitbar: ändern, erledigen,
  löschen und neu anlegen (ohne Änderungsverfolgung). Beim Abschliessen wird der Stand
  aller Todos, inklusive offener Todos aus früheren Protokollen, als Momentaufnahme
  eingefroren; Ansicht und PDF-Export des abgeschlossenen Protokolls zeigen diesen Stand.
  Zurücksetzen verwirft die Momentaufnahme nach einer Warnung.
- Matrix-Designer: Automatische Termin-Spalten lassen sich auf einen Zyklus einschränken
  (aktueller, vorheriger, … Zyklus relativ zum Protokolldatum). Der Tag-Filter
  automatischer Termin-Spalten akzeptiert mehrere Tags.
- Website: Sprachumschalter im Header; «Anmelden» zeigt auf `HOCX_APP_URL`.

### Geändert

- Matrix-Designer neu gestaltet: Einstellungsleiste für Spaltenquelle, Raster mit
  nummerierten Zeilen und Spaltenköpfen, Inspektor für Zeile oder Spalte, Abbrechen
  verwirft alle Änderungen seit dem Öffnen.
- Abgeschlossene Protokolle öffnen im selben Dokument-Layout wie der Protokolleditor
  (schreibgeschützt); die alte Einzelabschnitt-Ansicht entfällt.
- Stammlisten: Einzel-Teilnehmer erscheinen als Chip mit Initialen wie bei
  Mehrfach-Teilnehmern.
- Abgabe-Detail: Termin bzw. Listeneintrag als Titel, verantwortliche Person in der
  Metazeile.
- Todo-Dialog: Verantwortliche als Mehrfachauswahl; die Herkunft aus einem Aufgabenpaket
  steht im Dialog statt als Badge in der Todo-Liste.
- Aufgabenpakete: Button «Aus Liste» statt «Ämtli aus Liste».
- Website: Hinweis «Hosting in der Schweiz» aus dem Hero entfernt.

### Behoben

- Todo bearbeiten ersetzte mehrere Verantwortliche (z. B. aus einem Aufgabenpaket) durch
  eine einzige Person.
- PDF-Export zeigte andere Termine als der Protokolleditor: Der Editor lud nur die
  neuesten 100 Termine, der Export enthielt «Nächster Hock»-Platzhalter, und
  Terminlisten-Zeilen in Matrizen filterten anders als im Editor.
- Termine «Nur im aktuellen Zyklus» funktionierten nicht, weil die Zyklus-Zuordnungen in
  der Termin-Antwort fehlten.
- PDF-Export: Kleine Bilder wurden auf Textbreite hochskaliert und unscharf;
  Bildunterschriften erschienen als «Figure 1: *».
- Protokollsuche: Treffer im Titel stehen vor Treffern im Inhalt.
- Termine: Tag-Zeilen in der Seitenleiste waren zu hoch, der Stern ragte über den Rand.
- Sidebar: Eine lange Copyright-Zeile schnitt Identitätskarte und Footer ab.
- Website: Ein leeres `HOCX_APP_URL` führte nicht auf `TRAEFIK_DOMAIN` zurück.

## [1.1.11] - 2026-10-12

Feature-Release auf 1.1.10 mit Aufgabenpaketen für wiederkehrende Todos, mehreren
Verantwortlichen pro Todo, einem überarbeiteten Dashboard, einem neu gestalteten
Stammlisten-Block im Protokoll und einem Redesign der Abgabebox. Enthält die Migrationen
`0110` und `0111`; sie laufen beim Deploy automatisch und sind umkehrbar. Keine neuen
Pflicht-Umgebungsvariablen.

### Update von 1.1.10 auf 1.1.11

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.11` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.

- Migration `0110` legt `user_protocol_template_preference` an (zuletzt gewählte
  Protokollvorlage pro Benutzer und Mandant).
- Migration `0111` legt die Tabellen für Aufgabenpakete (`task_package`,
  `task_package_cycle`, `task_package_item`) und mehrere Verantwortliche pro Todo
  (`protocol_todo_assignee`) an. Bestehende Todos behalten ihren Verantwortlichen.
- Neuer täglicher Job `task_package_rollover`, erscheint automatisch unter `/admin/jobs`.
- Ist `TRAEFIK_WEBSITE_DOMAIN` gesetzt, prüft `verify_release.sh` nach dem Deploy, dass die
  Website-Domain die Landing Page ausliefert. Optional einen zweiten Uptime-Kuma-Monitor für
  die Website-Domain anlegen (RUNBOOK).

### Neu

- **Aufgabenpakete** (Vorlagen → Aufgabenpakete): Pakete wie «Sommerlager» oder
  «Scharleitung» bündeln wiederkehrende Aufgaben und werden einem oder mehreren Zyklen
  zugewiesen. Für den laufenden Zyklus entstehen daraus automatisch Todos – einmal pro
  Zyklus, monatlich, wöchentlich oder pro Termin mit einem bestimmten Tag, mit fester oder
  relativer Fälligkeit. Verantwortliche kommen wie im Protokoll aus Listenzeilen (z. B. der
  Ämtliliste): alle Personen eines Ämtlis werden gemeinsam einer Aufgabe zugewiesen. Ändert
  sich die Liste oder das Paket, werden offene Aufgaben des laufenden Zyklus angepasst;
  vergangene Zyklen, erledigte Aufgaben und von Hand geänderte Felder bleiben unverändert.
  Beim Löschen eines Pakets oder einer Zyklus-Zuweisung wird gefragt, ob alle, nur künftige
  oder keine Aufgaben gelöscht werden. Neuer täglicher Job `task_package_rollover`
  (`/admin/jobs`) legt beim Zykluswechsel die Aufgaben des neuen Zyklus an.
- Todos können mehrere Verantwortliche haben; «Meine Todos», Kalender-Abo, Export und
  Mandanten-Export/-Import berücksichtigen alle. Migration `0111_task_packages`.
- Termine: Tags lassen sich mit einem Stern als wichtig markieren. Sie stehen in der
  Seitenleiste direkt unter «Alle Termine», mobil zuvorderst in der Tag-Leiste.
- Neue Protokolle merken sich die zuletzt gewählte Vorlage pro Benutzer; die
  Namensvorschau zeigt den tatsächlich entstehenden Protokollnamen (Migration `0110`).
- Dashboard: Kontostände (Kassier/Admin) und Abgaben mit Frist (Schreiber/Admin mit
  Abgabebox) als neue Kacheln.
- Preiskatalog: Ungenutzte Speicherpakete lassen sich löschen.

### Geändert

- Dashboard: Desktop und Mobile nutzen dieselben Daten und rollenbasierten Kacheln. Am
  Desktop neu mit Begrüssung, «Meine Todos» (eigene und überfällige), kommenden Terminen
  und Statistik. Offene Bussen erscheinen nur mit gebuchtem Finanzmodul, Leser sehen ihre
  eigenen offenen Bussen.
- Stammlisten-Tabellenblock im Protokoll neu gestaltet: Personen als Chips mit Initialen,
  Besetzungsgrad, Filter Alle/Offen/Geändert, Änderungsfarben nur bei aktiver
  Änderungsverfolgung. «Leere Zeilen hervorheben» ist pro Block im Template einstellbar;
  Gruppieren/Sortieren kommt aus dem Template statt aus dem Protokolleditor.
- Abgabebox neu gestaltet (Desktop und Mobile): Seitenleiste bzw. Kopfzeile mit
  Schrittanzeige, Abgaben als Karten, Upload mit Dropzone und Sicherheitsprüfung als
  Statuskarte, Erfolgsansicht mit Quittung.
- Aufgabenpaket-Dialog vereinfacht: Verantwortliche als ein Feld mit Chips, Wiederholung
  und Fälligkeit als Segment-Auswahl.
- Teilnehmerfilter: «Aktiv» steht zuerst und ist standardmässig ausgewählt.
- Platform-Admin: Kontoeinstellungen sind ins Profilmenü umgezogen.
- Footer: Versionsanzeige kompakter, Test- und Entwicklungsumgebungen mit Badge.

### Behoben

- Beim Tippen im Protokolltext erschien eine falsche Konflikt-Meldung, und der getippte
  Text wurde durch den Serverstand ersetzt, obwohl niemand sonst bearbeitete.
- Mobile: iOS zoomte beim Fokus ins Login-Formular, Doppeltipp zoomte ungewollt.
- Word-Import: Nach mehreren Importen scheiterte ein gültiges Dokument gelegentlich mit
  «Datei konnte nicht gelesen werden: XMLSyntaxError». Ein solcher Fehler wird jetzt
  einmal in einem frischen Parser-Prozess wiederholt.
- Dashboard: Summe und Personenzahl offener Bussen brachen nach 50 Einträgen ab.
- `deploy.sh` brach mit «Nicht erlaubte Variable TRAEFIK_WEBSITE_DOMAIN» ab, sobald die mit
  1.1.10 eingeführten Variablen `TRAEFIK_WEBSITE_DOMAIN` oder `WEBSITE_CONTACT_EMAIL` (oder
  `ABGABEBOX_ENVIRONMENT`) in der `.env` gesetzt waren. Ein Test stellt jetzt sicher, dass
  jede Variable aus `.env.example` von den Deploy-Skripten akzeptiert wird.

## [1.1.10] - 2026-10-11

Feature-Release auf 1.1.9 mit einer vollständigen Mobile-Oberfläche, Kalender-Abos für
Termine und Todos, einer öffentlichen Landing Page mit Preisen aus dem Katalog,
Systemstatus, Job-Übersicht und ntfy-Benachrichtigungen im Platform-Admin, einer
gemeinsamen Identität für Teilnehmer und Benutzer sowie einem vollständigen
Mandanten-Backup per Export/Import. Enthält die Migrationen `0102` bis `0109`; sie laufen
beim Deploy automatisch. **Migration `0108` ist nicht umkehrbar** (siehe unten). Keine
neuen Pflicht-Umgebungsvariablen.

### Update von 1.1.9 auf 1.1.10

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.10` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.

- **Backup vor dem Update:** Migration `0108` führt Teilnehmer und Benutzerkonten zu einer
  Identität zusammen und entfernt die Tabelle `participant`. Ein Downgrade ist nicht
  möglich; zurück geht es nur mit dem Datenbank-Backup von vor dem Update. `deploy.sh`
  legt dieses Backup automatisch unter `backups/*-pre-v1.1.10.sql.gz` an – vor dem
  Weitermachen prüfen, dass die Datei existiert und nicht leer ist.
- Migration `0108` übernimmt alle Teilnehmer-Verweise (Vorlagen, Todos, Bussen,
  Termin-Rollen, Anwesenheit, Listen, Verantwortliche, Word-Import-Entwürfe) auf die
  bestehende Benutzer-ID. Unverknüpfte Teilnehmer erhalten ein Konto ohne Login,
  Schattenkonten verlieren ihre Platzhalter-E-Mail und ihr Passwort. Login-E-Mails werden
  kleingeschrieben und müssen danach eindeutig sein: Gibt es zwei Konten, deren E-Mail sich
  nur in Gross-/Kleinschreibung unterscheidet, bricht die Migration ab – vorher prüfen mit
  `SELECT lower(trim(email)), count(*) FROM app_user GROUP BY 1 HAVING count(*) > 1;`
- Migration `0109` gibt dem Abgabebox-Dienst Lesezugriff auf die Namensspalten von
  `app_user` (ohne E-Mail und Kontodaten), damit Abgaben mit Teilnehmer-Elementen nach
  `0108` weiter funktionieren.
- Migrationen `0105` und `0107` legen die Tabellen für Job-Übersicht, Systemstatus und
  Benachrichtigungen an, `0106` ergänzt `storage_package.is_bookable` (bestehende Pakete
  bleiben buchbar).
- Migration `0102` legt die Tabelle `calendar_feed` an (Kalender-Abos). Tokens werden
  nur als SHA-256-Hash und Fernet-verschlüsselt mit `ADMIN_AUTH_SECRET` gespeichert.
- Migration `0103` ergänzt `plan.is_featured` und markiert den Plan `standard` als
  «Beliebteste Wahl». Fehlt dieser Plan, bleibt keiner markiert.
- Migration `0104` ergänzt `tenant.show_on_website`. Standard ist «nicht gelistet»;
  kein Verein erscheint ohne Freigabe im Adminportal auf der Website.
- Neue optionale Variablen `TRAEFIK_WEBSITE_DOMAIN` (Domain der Landing Page, z. B. die
  Hauptdomain) und `WEBSITE_CONTACT_EMAIL` (mailto-Ziel der Demo-/Kontakt-Buttons).
  Leer bleibt die Website deaktiviert, und Traefik fordert kein Zertifikat für sie an.
  Für eine eigene Website-Domain muss deren DNS auf den Server zeigen, damit Traefik ein
  Zertifikat beziehen kann.
- Neuer Container `docker-socket-proxy` (nur lesender Zugriff auf die Docker-API, im
  internen Netz `docker-api`, nur für das Backend erreichbar). Er bindet
  `/var/run/docker.sock` read-only ein; `deploy.sh` startet ihn automatisch mit.
- Der Virenscanner sucht jetzt alle zwei Stunden nach neuen Signaturen
  (`FRESHCLAM_CHECKS=12` in den Compose-Dateien), keine Aktion nötig.
- Optional nach dem Update: ntfy unter `/admin/notifications` einrichten, Host-Cronjobs
  (Backup, Speicher-Aufräumen) über `scripts/run_job.sh` starten und den Statusendpunkt in
  Uptime Kuma eintragen (RUNBOOK Abschnitt 10 und 12).
- Exportformat 4: Alte Archive (Format 2/3) bleiben importierbar. Archive ab 1.1.10
  enthalten Zugangsdaten und sind wie ein Datenbank-Dump aufzubewahren.
- Git-Tag und GitHub-Release entstehen erst nach erfolgreicher Promotion aller Images
  durch den Release-Workflow. Der Push dieser Vorbereitung veröffentlicht noch kein
  Release.

### Neu

- Mobile-Oberfläche: Bis 900 px zeigen dieselben URLs eine eigene Mobile-Ansicht mit
  Tableiste (Übersicht, Termine, Todos, Mehr). Unter «Mehr» hat jeder Bereich der
  Desktop-Navigation eine eigene Ansicht, rollenabhängig gelistet. Der mobile
  Protokoll-Editor bearbeitet Text, Anwesenheit, Todos, Fotos, Notizen und Status mit
  Live-Abgleich und erzeugt PDFs. Dialoge erscheinen als Bottom-Sheet. Element-Editor,
  Dokument-Layouts und Import verweisen auf den Computer.
- Verknüpfungen (Benutzermenü): Termine (Schreiber/Admins) und Todos (alle Rollen, eigene
  oder alle sichtbaren) als abonnierbarer Kalender für Apple und Google. Optionen für
  erledigte Todos und «nur Titel und Datum»; URL neu erzeugen oder entfernen. Ein
  deaktivierter Benutzer, eine Rollenänderung oder «überall abmelden» wirkt sofort auf
  den Feed.
- Öffentliche Landing Page unter `TRAEFIK_WEBSITE_DOMAIN` mit Preiskarten direkt aus dem
  Preiskatalog (Monat/Jahr-Umschalter, Ersparnis). Im Admin-Preiskatalog lässt sich ein
  Plan als «Beliebteste Wahl» markieren, im Mandanten-Dialog ein Verein als Kunde unter
  «Im Einsatz bei» freigeben. Indexierung per `robots.txt` nur auf der Website-Domain.
- Toasts können eine Aktion tragen (z. B. «Rückgängig»).
- Platform-Admin: neue Seite „Jobs“ (`/admin/jobs`) mit allen periodischen Hintergrundjobs –
  Virenprüfung, Bildanalyse, Uploads, Aufräum- und Wartungsjobs – samt letztem Lauf, Dauer,
  Status (OK, läuft, fehlgeschlagen, überfällig, nie gelaufen), letzter Fehlermeldung und
  Verlauf. Der Bildanalyse-Worker wird über ein Lebenszeichen überwacht. Jobs, die sich melden,
  aber nicht registriert sind (z. B. künftige Host-Cronjobs), erscheinen unter „Weitere“.
- Platform-Admin: neue Seite „Systemstatus“ (`/admin/system`) mit allen Containern (Status,
  Healthcheck, Neustarts, CPU/RAM, Version) und den Diensten, von denen hocX abhängt (Datenbank,
  Redis, Virenscanner inkl. Alter der Signaturen, Speicherplatz, Fehlerrate, Rückstand der
  Virenprüfung, Bildanalyse-Warteschlange), offenen Problemen und Ereignisverlauf. Container-Daten
  kommen über einen neuen, nur lesenden `docker-socket-proxy` in einem internen Netz.
- Platform-Admin: Benachrichtigungen per ntfy (`/admin/notifications`), konfigurierbar mit
  Server, Topic, Token, Erinnerungsintervall und Testnachricht. Gemeldet werden neue (nach 90 s
  Karenzzeit), verschärfte, weiterhin offene und behobene Probleme sowie Container-Neustarts.
- Statusendpunkt `/api/system-status/summary` (per Token) für externe Überwachung, z. B. mit
  Uptime Kuma: HTTP 503 bei kritischen Problemen oder veraltetem Systemstatus.
- `scripts/run_job.sh`: Wrapper für Host-Cronjobs, meldet Läufe an die Job-Übersicht
  (Backup und Speicher-Aufräumen sind dort bereits registriert, siehe RUNBOOK Abschnitt 10/12).
- Todos: Fälligkeit per Schnellauswahl „Ende der Woche“, „Ende des Monats“ und „In zwei
  Wochen“ sowie mit frei wählbarem Datum – im Fälligkeitsmenü am Desktop und in der
  Mobile-Ansicht.

### Geändert

- Mandant-Einstellungen (Allgemein, Domains, Abo & Nutzung) haben eigene
  Mobile-Ansichten statt eingebetteter Desktop-Karten.
- Profil-Dialog: Sprachauswahl mit Chevron, «Protokollpunkte automatisch einklappen» als
  Karte mit Schalter.
- Abgabebox mobil: kein iOS-Zoom bei der Sprachauswahl, grössere Touch-Ziele, «Datei
  auswählen» statt Drag-and-drop-Hinweis auf Touch-Geräten, lange Titel brechen um.
- Teilnehmer und Benutzer verwenden einen gemeinsamen Datensatz. Die Oberfläche unterscheidet
  „Teilnehmer“ und „Teilnehmer mit Login“. E-Mail und Passwort sind nur für einen Login nötig;
  Kontaktadressen ohne Login dürfen mehrfach vorkommen. Nur Administratoren schalten Logins frei.
  Schattenkonten und Merge-Funktionen entfallen; Authentifizierungs-IDs bleiben erhalten.
- Exportformat 4 referenziert Teilnehmer über UUIDs statt E-Mail-Adressen. Alte Archive
  (Format 2/3) bleiben importierbar. Geklonte Teilnehmer erhalten keinen aktiven Login.
- Der Mandanten-Export ist jetzt ein vollständiges, mandantenspezifisches Backup: Er enthält
  zusätzlich Abgabebox-Links (mit Abgabe-Zuordnung), öffentliche Freigabe-Links,
  Kalender-Abos, gebuchte Features und Speicherpakete, Vertrauensbeziehungen und
  Album-Freigaben mit Partner-Mandanten. Tokens bleiben beim Import erhalten, damit verteilte
  URLs nach einem Restore weiter funktionieren; ist ein Token auf der Zielinstanz bereits
  vergeben, wird mit Warnung ein neuer erzeugt. Beziehungen zu anderen Mandanten werden nur
  wiederhergestellt, wenn der Partner auf der Zielinstanz existiert.
- **Sicherheit:** Export-Archive enthalten damit Zugangsdaten (Passwort-Hashes, MFA-Secrets,
  Link- und Abo-Tokens) und sind wie ein Datenbank-Dump aufzubewahren. Der Export-Dialog
  weist darauf hin.
- Adminportal: Katalog-Import-Dialog ist vor dem Laden einer Datei schmal und wird erst für
  die Vorschau breit; Badges der Plankarten im Preiskatalog brechen sauber um.

### Behoben

- Freigabeseite: «Alle herunterladen» schlug bei Alben ab etwa 20 Fotos mit einer
  fehlerhaften `download.json` fehl, weil die Vorschaubilder das gemeinsame Rate-Limit
  verbrauchten. Jede Endpunkt-Art hat jetzt einen eigenen Zähler; das
  Vorschaubild-Limit liegt bei 3000/min.
- Todos ohne Protokoll liessen sich nicht abhaken, bearbeiten oder löschen.
- Abgabebox: fehlende Gestaltung des Offline-Hinweises ergänzt.
- Der Quarantäne-Aufräumjob der Abgabebox und das Aufräumen alter Exporte im Backend teilten
  sich denselben Datenbank-Lock und haben sich dadurch gegenseitig Durchläufe weggenommen.
- Ein Hintergrund-Loop konnte dauerhaft und ohne jede Spur stehen bleiben, wenn schon das
  Holen seiner Datenbankverbindung fehlschlug (z. B. Pool-Timeout). Solche Fehler beenden jetzt
  nur den einzelnen Durchlauf. Ausserdem starten die Loops zeitversetzt, statt beim Hochfahren
  alle gleichzeitig um den Connection-Pool zu konkurrieren.
- Der Virenscanner konnte nach einem Neustart bis zu einem Tag mit veralteten Signaturen
  arbeiten, wenn das Signatur-Update genau beim Hochfahren lief. Er sucht jetzt alle zwei
  Stunden statt einmal täglich nach neuen Signaturen.
- Mandanten-Export/-Import als vollständiges Backup: Fotoalben (inkl. Best-of-Auswahl)
  und die Zyklus-Snapshots der Listen werden jetzt mitexportiert und wiederhergestellt.
- Import übernimmt die öffentlichen IDs (`public_id`), solange sie auf der Zielinstanz frei
  sind. URLs, Lesezeichen und per `public_id` gespeicherte Bezüge (Abgabe-Element von
  Galerie-Fotos, Upload-Protokoll und Todos, Album-Einträge, Entwürfe offener Word-Importe)
  bleiben so gültig; bei einer Kollision werden sie konsistent umgeschrieben.
- Import verknüpfte einige Daten weiterhin mit dem Quell-Mandanten bzw. brach auf einer
  frischen Instanz ab: Zyklus-Filter von Abgaben, Verantwortliche eines Protokolls,
  „Wiederholen aus Termin/Todo“-Blöcke sowie die gelernten Zuordnungen und Analysen des
  Word-Imports werden jetzt umgemappt. Verantwortliche und Wiederhol-Blöcke waren auch
  beim Mandanten-Klon betroffen.
- Ein auf der Zielinstanz unbekannter Preisplan bricht den Import nicht mehr ab, sondern
  wird mit Warnung weggelassen.
- Mandanten-Klon: Abgabe-Bezüge (`element_ref`) in Upload-Protokoll und Todos zeigen jetzt
  auf die geklonten Termine/Listeneinträge statt auf die des Quell-Mandanten.

## [1.1.9] - 2026-10-05

Feature- und Fix-Release auf 1.1.8 mit einem Zyklus-Filter in der Terminübersicht,
durchgehend automatischer Fotoanalyse, wiederhergestellten Kategorien in der
Blocktyp-Auswahl und einer Korrektur des PDF-Exports. Keine Migration, keine neuen
Pflicht-Umgebungsvariablen.

### Update von 1.1.8 auf 1.1.9

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.9` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.

- Neue Standardwerte: `PHOTO_ANALYSIS_AUTO_QUEUE_START_HOUR=0`/`END_HOUR=24` (rund um
  die Uhr statt 01–06 Uhr UTC), `PHOTO_ANALYSIS_AUTO_QUEUE_INTERVAL_MINUTES`,
  `DOMAIN_HEALTH_CHECK_INTERVAL_MINUTES` und
  `ABGABEBOX_QUARANTINE_CLEANUP_INTERVAL_MINUTES` je 5 statt 30 Minuten. Wer diese
  Variablen in `.env` explizit gesetzt hat, behält seine Werte; für das neue Verhalten
  die Einträge entfernen.
- Git-Tag und GitHub-Release entstehen erst nach erfolgreicher Promotion aller Images
  durch den Release-Workflow. Der Push dieser Vorbereitung veröffentlicht noch kein
  Release.

### Neu

- Terminübersicht: Zyklus-Filter. Standardmässig zeigt sie die aktuelle Periode aller
  Zyklen; im Ansicht-Menü lässt sich ein einzelner Zyklus wählen. Zur Periode gehören
  Termine, die zeitlich hineinfallen oder mit ihr verknüpft sind. Tags ohne Termine in
  der Auswahl verschwinden aus der Seitenleiste.

### Geändert

- Fotoanalyse läuft automatisch rund um die Uhr (Prüfung alle 5 Minuten); die
  Last-Bremse (`PHOTO_ANALYSIS_AUTO_QUEUE_MAX_LOAD_FACTOR`) bleibt. Der Button
  «Analyse starten» entfällt. Duplikate und Ähnliche sind wieder eigene Tabs.
- Domain-Health-Check und Quarantäne-Aufräumen der Abgabebox laufen alle 5 statt 30
  Minuten.
- Blocktyp-Auswahl wieder mit den Gruppen Basics, Finanzen und Organisation und einer
  Mini-Vorschau pro Karte; Sitzungsnotizen (#17) hat eine eigene Vorschau. Die
  #ID-Badges bleiben.
- Die Terminliste scrollt bei jedem Tag-, Zeit- oder Zykluswechsel zur «Heute»-Linie.
- Block-Konfiguration aufgeräumt; die Zyklusauswahl in Diagramm-Blöcken ist eine
  kompakte Pill-Gruppe.

### Behoben

- PDF-Export brach mit «invalid literal for int()» ab, wenn ein Block im Editor
  gewählte Teilnehmer oder Termine (öffentliche UUID) neben aus der Vorlage
  vorbefüllten (interne ID) enthielt. Export, Anwesenheit-Speichern sowie Mandant
  klonen/importieren lösen beide Formen jetzt auf; beim Klonen und Importieren gehen
  UUID-Referenzen in Block-Snapshots nicht mehr verloren.

## [1.1.8] - 2026-10-05

Feature-Release auf 1.1.7 mit einem neuen Blocktyp «Sitzungsnotizen», mehrtägigen
Terminen als Balken im Kalender, Datumsauswahl über die Terminübersicht und einer
Korrektur der Anwesenheitsauswahl. Enthält die Migration `0101`; sie läuft beim Deploy
automatisch. Keine neuen Pflicht-Umgebungsvariablen.

### Update von 1.1.7 auf 1.1.8

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.8` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.

- Migration `0101` legt den Blocktyp `session_notes` mit der festen id 17 an. Bestehende
  Vorlagen und Protokolle bleiben unverändert. Ist die id 17 oder der Code bereits
  anders belegt, bricht sie mit einer Meldung ab, statt zu raten.
- Git-Tag und GitHub-Release entstehen erst nach erfolgreicher Promotion aller Images
  durch den Release-Workflow. Der Push dieser Vorbereitung veröffentlicht noch kein
  Release.

### Neu

- Neuer Blocktyp «Sitzungsnotizen»: zeigt die freien Notizen aus dem Sitzungspanel als
  eigenen Block im Protokoll und im PDF-Export, ohne die Sitzungs-Todos. Der Block ist
  nur drin, wenn er in einer Vorlage hinzugefügt wird; bestehende Vorlagen und
  Protokolle bleiben unverändert. Im Protokoll ist er schreibgeschützt, geschrieben wird
  weiterhin im Sitzungspanel. Migration `0101` legt den Typ (id 17) an.
- Der Kalender-Button beim Sitzungsdatum öffnet die Terminübersicht; ein Klick auf einen
  Tag übernimmt das Datum («Nächster Hock»). In der Elementvorlage Sitzungsdatum legt
  ein Tag-Filter fest, welche Termine im Kalender erscheinen (leer = alle).

### Geändert

- Monatskalender in Wochenzeilen: mehrtägige Termine laufen als durchgehender Balken
  über ihre Tage, überlappende Termine bekommen eigene Zeilen, ab der vierten Zeile
  «+N weitere».
- Die Terminübersicht startet bei der «Heute»-Linie; vergangene Termine per
  Hochscrollen. Auf dem Desktop scrollt nur die Terminliste, Kopfzeile, Toolbar und
  Tag-Leiste bleiben stehen. Beginnt ein Monat mit dem ersten kommenden Termin, steht
  die «Heute»-Linie vor dessen Monatsüberschrift.
- Beim Öffnen eines Protokolls springt die Ansicht direkt zum zuletzt aktiven bzw.
  ersten Punkt, statt auf dem Leerraum über dem ersten Punkt stehenzubleiben.
- Fotogalerie: Kacheln wieder in der Grösse vor dem Umbau (automatische Spaltenzahl,
  ca. 180px breit, schmalerer Abstand) statt fester 4/3/2 Spalten; das
  Vergrössern-Icon auf den Kacheln entfällt.
- Dateityp-Icons in der Dateiliste sind kleiner.

### Behoben

- Die Anwesenheitsauswahl im Protokoll verschwand nach dem Klick sofort wieder, weil
  die Serverantwort die interne statt der öffentlichen Teilnehmer-ID enthielt. Dieselbe
  Ursache setzte die Anwesenheit beim Neuladen eines Protokolls auf «Unentschuldigt»
  zurück.

## [1.1.7] - 2026-10-05

Feature-Release auf 1.1.6 mit zyklusbasierter Protokoll-Gruppierung, automatischem
Abgabe-Abschluss und einer neu gestalteten, metadatensensiblen Freigabeseite. Enthält
die Migration `0100`; sie läuft beim Deploy automatisch. Keine neuen Pflicht-
Umgebungsvariablen.

### Update von 1.1.6 auf 1.1.7

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.7` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.

- Migration `0100` ergänzt `share_link.share_location`/`share_capture_date`/
  `share_camera` und setzt für bestehende Links dieselbe Vorgabe wie für neue: nur das
  Aufnahmedatum geht mit, Standort (GPS) und Kamera/Gerät nicht. Bisher gingen bei
  öffentlichen Freigaben alle Metadaten ungefiltert raus; wer bei bestehenden Links
  bewusst mehr mitgeben möchte, stellt das pro Link in den Freigabe-Einstellungen um.
- Git-Tag und GitHub-Release entstehen erst nach erfolgreicher Promotion aller Images
  durch den Release-Workflow. Der Push dieser Vorbereitung veröffentlicht noch kein
  Release.

### Neu

- Die Protokoll-Liste gruppiert nach Zyklus statt einer einzigen flachen Liste: der
  aktuelle Zyklus und der unmittelbar vorherige stehen offen, ältere Zyklen stehen
  hinter «Ältere Zyklen anzeigen». Vorlagen ohne Zyklus gruppieren nach Kalenderjahr.
  Suchen/Filtern zeigt alle Treffer unabhängig vom Einklapp-Zustand.
- Diagramm-Blöcke im Protokoll können einen Zyklus relativ zum Protokolldatum wählen
  (aktueller, vorheriger, …) statt einen fest einprogrammierten Zyklus-Schlüssel –
  dieselbe Zyklus-Offset-Auswahl wie bei Abgaben.
- Abgaben können Elemente automatisch schliessen: nie, nach der ersten Abgabe oder
  sobald die maximale Dateizahl erreicht ist. «Wieder aufschalten» funktioniert
  unverändert.
- Dateien/Fotos-Tabelle zeigt ein Dateityp-Icon nach Dateiendung statt eines generischen
  Platzhalters.
- Beim Erstellen eines Freigabe-Links wählbar, welche Foto-Metadaten mitgehen: Standort
  (GPS), Aufnahmedatum, Kamera & Gerät – Vorgabe nur das Aufnahmedatum. Enthält Migration
  `0100`, die diese Vorgabe auch auf bestehende Links setzt.
- Die öffentliche Freigabeseite (`/share/<token>`) ist ohne Login erreichbar (der Token
  bleibt die einzige Authentifizierung) und neu gestaltet: Absender-Kopfzeile, Meta-Zeile
  (Anzahl, Grösse, Aufnahmezeitraum, Ablaufdatum), Masonry-Raster, Lightbox mit Blättern.
  «Alle herunterladen» liefert ein ZIP, im Auswahlmodus nur die gewählten Dateien.

### Geändert

- Terminliste, Kalender und der Termin-Dialog im neuen Design: Tag-Sidebar mit Zählern,
  Monatsgruppen mit Datumskachel und Heute-Linie, Zeitfilter Kommend/Alle/Vergangen,
  Ansicht-Menü für die Zeilenfelder (pro Browser gespeichert); Kalender als
  Vollbild-Dialog mit Tagesdetail; neuer Termin zweispaltig mit Zeitraum,
  Personen-Rollen, Tag-Chips und Zyklen.
- Transaktionsformular der Finanzen mit expliziter Einnahme-/Ausgabe-Auswahl statt
  Vorzeichen-Eingabe über den Betrag.
- Fotogalerie mit haftender Auswahlleiste und kompakteren Aktionen.

### Behoben

- Ein zweiter, schnell aufeinanderfolgender Klick in der Anwesenheitskontrolle (eine
  Person schnell durchklickend, oder zwei Personen nehmen gemeinsam Anwesenheit auf)
  überschreibt nicht mehr stillschweigend den gerade gespeicherten Status der anderen
  Person; betraf auch die Entschuldigen-Aktion im Dashboard.
- Weitertippen im Protokolltext, während ein vorheriger Save noch läuft, löst keinen
  Konflikt mehr gegen die eigene vorherige Version aus, der den gerade getippten Text
  sichtbar durch eine veraltete Serverversion ersetzt hat.
- Die Galerie-Gruppierung «Duplikate»/«Ähnliche» verifiziert vor dem Gruppieren den
  tatsächlichen Bildinhalt (Pixelvergleich), statt sich allein auf den groben
  Perceptual-Hash-Kandidatenfilter zu verlassen.
- Die Aufgaben-Tabelle ist breiter und besser lesbar.
- Die Fotogalerie ordnet Kacheln als Masonry-Raster nach dem echten Bildformat statt
  gleich hoher Zeilen; der Ladezustand zeigt einen getönten Platzhalter statt einer
  leeren Fläche.

## [1.1.6] - 2026-10-04

Wartungsrelease auf 1.1.5 mit Korrekturen an Blocktypen, Zyklus-Zuordnung von Terminen
und der Anzeige von Teilnehmernamen im Protokoll-Editor. Enthält die Migration `0098`;
sie läuft beim Deploy automatisch. Keine neuen Pflicht-Umgebungsvariablen.

### Update von 1.1.5 auf 1.1.6

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.6` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.

- Migration `0098` gleicht die Blocktyp-ids 12–16 an die festen ids des Vorlagen-Editors
  an (12 Kontostand, 13 Transaktionen, 14 Bussenliste, 15 Diagramm, 16 Ein-/Austritte).
  Auf Installationen, die aus der 1.0.0-Baseline aufgesetzt wurden, waren diese Typen
  verschoben; die Migration benennt nur die Typ-Codes um, bestehende Blöcke erhalten
  dadurch den Typ, der im Editor gewählt wurde. Auf bereits korrekten Datenbanken ist sie
  ein No-op; bei unerwarteter Belegung bricht sie mit einer Meldung ab, statt zu raten.
- Nach dem Update betroffene, bereits erstellte Protokolle kurz prüfen: Blöcke, die
  vorher als falscher Typ erschienen, zeigen nun den richtigen Typ. Ein-/Austritte-Blöcke,
  die als Diagramm gespeichert wurden, enthalten noch keine Einträge – den Punkt im
  offenen Protokoll bei Bedarf neu anlegen.
- Bestehende Zyklus-Zuordnungen von Terminen werden nicht automatisch geändert. Termine,
  die fälschlich einem späteren Zyklus zugeordnet sind, in der Terminverwaltung
  korrigieren.
- Git-Tag und GitHub-Release entstehen erst nach erfolgreicher Promotion aller Images
  durch den Release-Workflow. Der Push dieser Vorbereitung veröffentlicht noch kein
  Release.

### Geändert

- Termine werden standardmässig dem Zyklus zugeordnet, in den ihr eigenes Datum fällt –
  beim Erfassen im Protokoll, in der Terminverwaltung sowie beim Word- und CSV-Import.
  Bisher erhielten im Protokoll erfasste oder importierte Termine zusätzlich den Zyklus
  des Protokolls, wodurch z. B. rückblickend erwähnte Anlässe im neuen Zyklus auftauchten.
  Manuell gewählte Zyklen bleiben erhalten; bei einer Datumsänderung wandern nur
  unveränderte Standard-Zuordnungen mit.
- Das Termin-Popup (Terminverwaltung, Terminübersicht und Terminauswahl im Protokoll)
  zeigt die Zyklen des Termins und erlaubt, sie direkt anzupassen.
- Mehrfachauswahlen von Teilnehmern zeigen im Protokoll-Editor alle Namen statt
  „Name + N“; zu lange Listen werden mit Auslassungspunkten gekürzt, der volle Text
  steht im Tooltip.

### Behoben

- Neu angelegte Kontostand-, Transaktions-, Bussenlisten-, Diagramm- und
  Ein-/Austritte-Blöcke werden mit dem richtigen Typ gespeichert (siehe Migration
  `0098`). Zuvor erschienen z. B. Ein-/Austritte unter Finanzen und „Kein Diagramm
  ausgewählt“ statt der Ein-/Austritte. Frische Installationen erhalten die Typen
  direkt mit festen ids.
- Der Protokoll-Editor zeigt Namen auch für Teilnehmer, die nicht der Vorlage
  zugewiesen sind, statt „X ausgewaehlt“ – in Listen, Formularen, Matrix-Zellen,
  eingebetteten Blöcken und verknüpften Ereignissen.
- Nach einer Spalte gruppierte Listen fassen Einträge mit verschiedenen Personen nicht
  mehr in einer einzigen Zeile zusammen; zusammengefasste Zeilen brechen um, statt die
  Tabelle zu sprengen.
- Ein-/Austritte-Blöcke tragen im Protokoll ihre Bezeichnung statt „ENTRY_EXIT“.

## [1.1.5] - 2026-10-04

Wartungsrelease auf 1.1.4 mit Korrekturen rund um Teilnehmer-Mitgliedschaften,
historische Listen und die Protokollnummerierung im Zyklus. Keine Migrationen und
keine neuen Pflicht-Umgebungsvariablen.

### Update von 1.1.4 auf 1.1.5

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.5` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.

- Keine Datenbank-Migrationen, keine manuellen Vorbereitungsschritte.
- Git-Tag und GitHub-Release entstehen erst nach erfolgreicher Promotion aller Images
  durch den Release-Workflow. Der Push dieser Vorbereitung veröffentlicht noch kein
  Release.

### Geändert

- In aktuellen Listen werden noch verknüpfte, bereits ausgetretene Teilnehmer
  orange markiert. Der Hinweis zeigt das Austrittsdatum; dies gilt für Einzel-
  und Mehrfachverknüpfungen. Historische Ansichten behalten ihre damalige Darstellung.

### Behoben

- `[n_cycle]` zählt über alle Vorlagen, die derselben Zyklus-Definition zugeordnet
  sind (z. B. Hock und Arbeitsweekend im selben Scharjahr); Vorlagen ohne Zyklus
  zählen weiter pro Vorlage. Einschübe nummerieren offene Protokolle anderer Vorlagen
  im selben Zyklus mit um, und bei einer Kollision der Protokollnummer weicht nur die
  Nummer aus – der Titel behält den echten Rang.
- Automatische Ereignis-Blöcke in Protokollen finden ihr verknüpftes Ereignis wieder
  zuverlässig. Titel, Felder und die Auswahl bereits verwendeter Ereignisse werden
  korrekt angezeigt, statt als unbekanntes Ereignis zu erscheinen.
- Offene Protokolle aktualisieren Teilnehmerlisten sowie Ein- und Austritte nach
  Änderungen der Mitgliedschaft anhand des Protokolldatums. Erfasste Anwesenheiten,
  Notizen und ausgeblendete Einträge bleiben erhalten.
- Historische Listen zeigen die damals verknüpften Teilnehmer wieder korrekt an.
  Neue Snapshots speichern zusätzlich ihre Namen und erhalten sie auch nach einer
  späteren Umbenennung oder Löschung. Abgeschlossene Protokolle zeigen den
  eingefrorenen Stand ihrer Anwesenheitslisten.
- Die Teilnehmerauswahl berücksichtigt Ein- und Austrittsdaten: Aktuelle Listen
  verwenden das heutige Datum, Protokolle und ihre zugehörigen Eingaben das
  Protokolldatum. Der Austrittstag bleibt eingeschlossen; danach stehen ausgetretene
  Teilnehmer nicht mehr zur Auswahl. Bestehende Verknüpfungen bleiben sichtbar.

## [1.1.4] - 2026-10-04

Wartungsrelease auf 1.1.3 mit vollständiger Mehrsprachigkeit (Deutsch/Englisch/
Französisch/Italienisch), einem Design- und einem Usability-Audit sowie mehreren
Sicherheits- und Kollaborations-Fixes. Enthält die Migration `0097`; sie läuft beim
Deploy automatisch. Für das Update von 1.1.3 sind keine neuen Pflicht-Umgebungsvariablen
nötig.

### Update von 1.1.3 auf 1.1.4

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.4` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.

- Migration `0097` ergänzt `app_user.preferred_language` nachträglich bei bereits
  laufenden, inkrementell migrierten Installationen, auf denen die Spalte trotz
  aktueller `sql/baseline_schema.sql` noch fehlte (Query-Fehler auf praktisch jedem
  authentifizierten Request). Prüft per Inspector, ob die Spalte schon existiert, ist
  also auch auf frisch per `baseline_schema.sql` initialisierten Datenbanken sicher.
  Keine manuellen Vorbereitungsschritte.
- `deploy.sh` erstellt Traefik beim ersten Deploy mit dieser Version einmalig neu (kurze
  Unterbrechung von wenigen Sekunden), weil sich `infra/traefik/traefik.yml` geändert
  hat (siehe unten).
- Git-Tag und GitHub-Release entstehen erst nach erfolgreicher Promotion aller Images
  durch den Release-Workflow. Der Push dieser Vorbereitung veröffentlicht noch kein
  Release.

### Neu

- **Vollständige Internationalisierung (i18n)** von Hauptapp, Platform-Admin und
  Abgabebox mit next-intl: Deutsch (Default), Englisch, Französisch, Italienisch.
  Zentrale Locale-Konfiguration in `i18n/locales.json` (siehe `CLAUDE.md`, Abschnitt
  „Internationalisierung / i18n"), Sprachauswahl in den Benutzereinstellungen,
  persistente Präferenz (`app_user.preferred_language` + `hocx_locale`-Cookie) und
  automatische CI-Prüfung auf Übersetzungs-Vollständigkeit, hart codierte UI-Texte und
  fehlerhafte Key-Auflösung zur Laufzeit.
- Echter Upload-Fortschritt im Galerie-Upload-Dialog: Fortschrittsbalken pro Datei
  (gesendete/gesamte Bytes), Prozentanzeige am Upload-Button, animierte Anzeige vor dem
  ersten Fortschrittsereignis und während der Server den Upload entgegennimmt.
- Gemeinsames Action-Icon-Set (`components/ui/action-icons.tsx`) für
  Bearbeiten/Löschen/Schliessen/Plus/Kopieren statt roher Unicode-Zeichen und
  duplizierter Inline-SVGs; `mini-menu` als eigenständiger, in `DESIGN.md`
  dokumentierter Baustein.

### Geändert

- Primäre Seitenaktion durchgängig auf `button-primary` vereinheitlicht (betraf
  mehrere Listen-/Manager-Seiten, die bisher `button-secondary` zeigten).
- Lösch-Terminologie vereinheitlicht ("Löschen" statt "Entfernen" bei echten
  Löschvorgängen, Bestätigungstexte auf Standardformel).
- Vorlagen-Detailseite und ihre Feldlabels lokalisiert und an die Struktur der
  Schwesterseite `/templates` angeglichen.
- Finanzen-Seite: fehlender Mobile-Breakpoint behoben (einspaltiges Layout ≤900px,
  scrollende Transaktionstabelle ≤640px statt Viewport-Überlauf).
- Protokoll-erstellen-Dialog: Namensvorschau beschriftet, Platzhalter aufgelöst statt
  rohe `{n}`/`{date:...}`-Syntax zu zeigen; Dashboard-CTA „+ Neues Protokoll" öffnet den
  Dialog jetzt direkt statt nur zur Liste zu navigieren.
- Natives `required` (englische Browser-Validierungsmeldung) durch disabled-
  Speichern-Button ersetzt (Benutzer-erstellen-Formulare, Tenant- und
  Platform-Admin-Variante).
- „ClamAV Online/Offline"-Chip durch Klartext „Virenprüfung aktiv/offline" ersetzt;
  Offline-Hinweistext bei der Protokoll-Kollaboration erklärt jetzt, dass Änderungen
  trotzdem automatisch gespeichert werden.
- Autofokus beim Öffnen eines Protokolls nur noch bei expliziten Sprungaktionen
  (Navigation/Tastatur/Suche), nicht mehr beim passiven Laden/Wiederherstellen der
  Scroll-Position.
- Nav-Label fr/it gekürzt (Organisation/Organizzazione), Sprachauswahl-Dropdown im
  Seitenkopf der Abgabebox nach denselben Tokens gestylt wie das Haupt-App-Select.

### Behoben

- `deploy.sh` erstellt Traefik neu, wenn sich `infra/traefik/traefik.yml` geändert hat.
  Bisher lief Traefik nach einem Update mit der alten statischen Konfiguration weiter
  (u. a. 60-s-`readTimeout`), wodurch grosse Galerie-Uploads mit «Bad Gateway» abbrachen.
- **Protokoll-Kollaboration** war über vier Bugs zusammen unzuverlässig: Der
  Kollaborations-Websocket liess nur die statische Haupt-Domain zu, nie eine
  Mandanten-eigene Custom-Domain (sofort „Offline"); Todo-/Bild-Updates wurden
  serverseitig immer abgelehnt, weil nur der übergeordnete Block sperrbar ist;
  Anwesenheits-Klicks verliessen sich auf ein Fokus-Event, das bei einem Button-Klick
  nicht in jedem Browser (v. a. Safari) auslöst; die „Status & Zusammenarbeit"-Kachel
  zählte auch ausgeblendete oder zum Löschen vorgesehene Anwesenheits-Blöcke.
- Protokoll-Suche: Sprung zum gewählten Kapitel landete nicht mehr korrekt, weil der
  Scroll-Spy den programmatischen Smooth-Scroll abbrach; ein Treffer auf das bereits
  aktive Kapitel scrollt jetzt ebenfalls.
- **Zentrale Fehlererfassung:** mehrere Stellen, an denen unerwartete Backend-Fehler
  nie in `system_error_log` landeten, geschlossen — u. a. ein falscher `source`-Wert in
  den Wartungs-Loops, der an der DB-Constraint scheiterte und sämtliche
  Wartungs-Loop-Fehler lautlos verwarf, sowie fehlendes zentrales Logging in
  WebSocket-Hintergrund-Tasks und weiteren Hintergrund-Diensten.
- `MISSING_MESSAGE`-Laufzeitfehler durch falschen Übersetzungs-Namespace behoben
  (Haupt-App-Breadcrumb, Protokoll-Vorlagen-Platzhaltervorschau); neuer
  `check-i18n-key-resolution.py`-CI-Guard verhindert ein Wiederauftreten.
- Fehlende Migration für `app_user.preferred_language` ergänzt — fehlte real auf
  bereits laufenden, inkrementell migrierten Datenbanken.
- **Sicherheitsaudit vom 30.09.2026:** `require_feature("custom_domain")` gate nur
  das Anlegen/Verifizieren einer Custom-Domain, nicht deren fortlaufenden Betrieb —
  nach Entzug des Features blieb eine bereits aktive Domain unbegrenzt geroutet;
  Regenerate-Aufruf, Health-Check-Loop und Login-Bridge prüfen das Feature jetzt
  zusätzlich laufend. Dependency-Updates: Next.js 16.2.12 → 16.3.6 (Out-of-Band-
  Sicherheitsupdate), `starlette` explizit auf `>=1.0.1` gepinnt (CVE-2026-48710),
  PyJWT 2.10.1 → 2.12.0, transitive `nanoid`-Schwachstelle in beiden Frontends per
  `npm audit fix` behoben.
- Admin-Mandanten-Einstellungen: Hooks-Reihenfolge-Crash im Speicher-Tab behoben
  (`useTranslations` wurde nach einem frühen `return null` aufgerufen).

## [1.1.3] - 2026-09-27

Wartungsrelease auf 1.1.2 mit Feature-Gating und Preiskatalog im Plattform-Admin,
mandantenübergreifendem Fotoalben-Teilen und mehreren Sicherheits-Fixes an der
Abgabebox. Enthält die Migrationen `0084` bis `0096`; sie laufen beim Deploy
automatisch. Für das Update von 1.1.2 sind keine neuen Umgebungsvariablen nötig.

### Update von 1.1.2 auf 1.1.3

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.3` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.

- Migrationen `0084` bis `0096` ergänzen Feature-Gating, Preiskatalog, Speicher-Zusatzpakete,
  Freigabe-Links und mandantenübergreifendes Fotoalben-Teilen. Alle sind additiv oder
  backfillen bestehende Mandanten automatisch (Finanzen, Abgabebox und eigene Domain
  bleiben für alle bisherigen Mandanten freigeschaltet); keine bricht bei bestehenden
  Daten ab, es sind keine manuellen Vorbereitungsschritte nötig.
- Migration `0088` setzt ein manuell erweitertes Speicherkontingent zurück, wenn es über
  der neuen automatischen Berechnung aus Plan und Zusatzpaketen lag; ein manuell
  verringertes Kontingent bleibt unverändert. Das lässt sich nicht rückgängig machen.
- Das Backend-Speicherlimit (`mem_limit`) steigt in den mitgelieferten Compose-Dateien
  von 1024 MB auf 6144 MB (Spielraum für Galerie-Uploads und Bildverarbeitung) und wird
  beim Update automatisch übernommen; der Host braucht entsprechend freien Arbeitsspeicher.
- Der Galerie-Upload-Router in Traefik puffert Anfragen nicht mehr vollständig, sondern
  streamt direkt zum Backend, das die bisherige Obergrenze jetzt selbst durchsetzt.
- Vor dem Update das Datenbankbackup prüfen.
- Git-Tag und GitHub-Release entstehen erst nach erfolgreicher Promotion aller Images
  durch den Release-Workflow. Der Push dieser Vorbereitung veröffentlicht noch kein Release.

### Neu

- **Feature-Gating und Preiskatalog im Plattform-Admin:** Mandanten lassen sich einzelne
  Funktionen (aktuell Finanzen, Abgabebox, eigene Domain) unabhängig von Rollen zu- oder
  abschalten. Neuer Preiskatalog mit Plänen (Monats-/Jahrespreis, Nutzer-/Speicherlimits),
  Rabatt in Prozent und interner Notiz pro Mandant sowie Abo-Zuweisung im Adminportal.
  Bestehende Mandanten wurden beim Umstieg automatisch auf ihren bisherigen Funktionsumfang
  freigeschaltet.
- **Speicher-Zusatzpakete:** zusätzlich zum Plan-Kontingent einzeln zubuchbare
  Speicherpakete pro Mandant; das Gesamtkontingent wird automatisch aus Plan und Paketen
  berechnet.
- **Fotoalben teilen:** Alben lassen sich mit anderen Mandanten teilen (Einladen per
  Mandanten-ID, Annehmen/Ablehnen), auch automatische Zyklus- und Abgabe-Alben. Neu
  hinzukommende Fotos in einem geteilten Album sind erst nach manueller Freigabe für den
  Partner-Mandanten sichtbar; manuell hinzugefügte Fotos sind sofort geteilt. Name,
  Profilbild und Teilnehmerzahl eines anderen Mandanten werden erst nach gegenseitig
  angenommener Freigabe angezeigt, nicht schon bei offener Anfrage.
- **Freigabe-Links:** öffentliche, tokenbasierte Download-Links ohne Login für einzelne
  Dateien oder ein ganzes Album, verwaltet unter «Freigabe-Links» mit eigener öffentlicher
  Download-Seite.
- Neuer Dialog «Fotos hinzufügen» für Alben: Mehrfachauswahl nach Datumsgruppe,
  «Alle auswählen», Filter und Suche über Tags, Termin, Protokoll oder Abgabe.
- Ctrl+F Kapitel- und Volltextsuche im Protokoll-Editor.
- Elemente lassen sich im Protokoll-Editor mit allen Blöcken duplizieren.
- Foto-Viewer: mit den Tasten J/L zwischen Bildern wechseln.

### Geändert

- **Abgabebox und eigene Domain sind jetzt eigene Feature-Gates** statt immer freigeschaltet;
  bestehende Mandanten behalten beim Umstieg automatisch den Zugriff.
- Manuelles Speicherkontingent-Feld im Adminportal wieder entfernt: Das Kontingent ergibt
  sich automatisch aus Plan und Speicher-Zusatzpaketen.
- Überarbeiteter Teilen-Dialog für Fotoalben: Vorschaukarte des gefundenen Mandanten,
  Statusliste «Geteilt mit», Entfernen bzw. Zurückziehen einer Freigabe.
- Mandanten-ID ist in den Mandanten-Einstellungen sichtbar.
- Protokollmenü vereinfacht; PDFs werden beim Öffnen eines Protokolls automatisch neu
  erstellt.
- Element-Anlegen-Popup an die neue Designvorlage angeglichen (Zyklus-Platzhalter-Karte,
  vereinfachtes Blocktyp-Raster, ergänzte Einstellungsabschnitte für Bild, Sitzungsdatum
  und Bussenliste).
- Modal-Schliessen ist durchgängig ein Icon-Button statt eines Text-Buttons; Auswahl-Popups
  (Teilnehmende, Terminverwaltung, strukturierte Listen) speichern jede Änderung sofort
  statt über einen «Auswahl übernehmen»-Button.
- Letztes rohes Datumsfeld (Todo-Export-Filter) durch den einheitlichen `DateInput` ersetzt.
- Admin-Navigation: Das «Neu»-Badge ist komplett entfernt.
- Redundante Inline-Styles am Zeitraum-Filter entfernt.

### Behoben

- **Sicherheitsaudit vom 24.09.2026:** Die Abgabebox prüfte das Speicherkontingent eines
  Uploads nur gegen eine globale Konstante statt gegen das tatsächliche Mandantenkontingent;
  ein Mandant auf einem kleineren Plan konnte sich darüber kostenlosen Zusatzspeicher bis zur
  globalen Obergrenze verschaffen. Geprüft wird jetzt der jeweils kleinere der beiden Werte.
  Ausserdem prüfte die Domain-Aktivierung das Feature-Gate für eigene Domains nicht wie das
  Anlegen, sodass eine bereits angelegte Domain nach Entzug des Features weiterhin aktiviert
  werden konnte.
- **Galerie-Upload blieb dauerhaft auf «queued» hängen:** Periodische Hintergrundschleifen
  (u. a. der Galerie-Upload-Ingest) nutzten Advisory Locks, die mit Connection-Pooling
  unsicher sind; betroffen waren auch Start-Locks und die Quarantäne-Bereinigung der
  Abgabebox.
- Escape-Zuständigkeit für Modals, Popups und Auswahlmenüs vereinheitlicht.
- Die Protokollliste aktualisiert sich beim Zurücknavigieren im Browser.
- Backend-Reload: Parser-Worker werden jetzt sauber heruntergefahren.
- Admin-Mandantenliste: Der `plan`-Filter griff bei direktem Routenaufruf fälschlich als
  Text statt als leerer Filter.

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
