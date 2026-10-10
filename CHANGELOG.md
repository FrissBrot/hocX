# Changelog

Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
Versionierung nach [SemVer](https://semver.org/lang/de/). Die Beta-Historie
(`v0.1.0-beta.1` bis `v0.1.1.1-beta.9.9`) wird hier nicht rekonstruiert; 1.0.0
ist der erste offiziell unterstützte Stand und muss keine älteren
Installationen aktualisieren können.

## [Unveröffentlicht]

## [1.1.10] - 2026-10-10

Feature-Release auf 1.1.9 mit einer vollständigen Mobile-Oberfläche, Kalender-Abos für
Termine und Todos, einer öffentlichen Landing Page mit Preisen aus dem Katalog sowie
Korrekturen an Freigabeseite und Standalone-Todos. Enthält die Migrationen `0102` bis
`0104`; sie laufen beim Deploy automatisch. Keine neuen Pflicht-Umgebungsvariablen.

### Update von 1.1.9 auf 1.1.10

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.10` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.

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

### Geändert

- Mandant-Einstellungen (Allgemein, Domains, Abo & Nutzung) haben eigene
  Mobile-Ansichten statt eingebetteter Desktop-Karten.
- Profil-Dialog: Sprachauswahl mit Chevron, «Protokollpunkte automatisch einklappen» als
  Karte mit Schalter.
- Abgabebox mobil: kein iOS-Zoom bei der Sprachauswahl, grössere Touch-Ziele, «Datei
  auswählen» statt Drag-and-drop-Hinweis auf Touch-Geräten, lange Titel brechen um.

### Behoben

- Freigabeseite: «Alle herunterladen» schlug bei Alben ab etwa 20 Fotos mit einer
  fehlerhaften `download.json` fehl, weil die Vorschaubilder das gemeinsame Rate-Limit
  verbrauchten. Jede Endpunkt-Art hat jetzt einen eigenen Zähler; das
  Vorschaubild-Limit liegt bei 3000/min.
- Todos ohne Protokoll liessen sich nicht abhaken, bearbeiten oder löschen.
- Abgabebox: fehlende Gestaltung des Offline-Hinweises ergänzt.

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
