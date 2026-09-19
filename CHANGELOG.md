# Changelog

Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
Versionierung nach [SemVer](https://semver.org/lang/de/). Die Beta-Historie
(`v0.1.0-beta.1` bis `v0.1.1.1-beta.9.9`) wird hier nicht rekonstruiert; 1.0.0
ist der erste offiziell unterstützte Stand und muss keine älteren
Installationen aktualisieren können.

## [1.1.0] - Unveröffentlicht

**Status: in Erprobung/QA auf dem Testhost - noch nicht als Release promotet und ohne
Veröffentlichungsdatum.** Diese Version enthält zusätzlich zu allen seit 1.0.0
gemergten Fixes/Hardening-Massnahmen auf `main` die folgenden neuen Funktionen.

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

## [1.0.0] - 2026-08-27

Erste stabile Version.

### Geändert

- Die 74 inkrementellen Alembic-Migrationen der Beta-Reihe wurden zu einer
  einzigen Baseline-Migration (`0001_initial_schema`) zusammengefasst. Neue
  Installationen erhalten direkt den aktuellen Schema-Stand; ein Upgrade-Pfad
  von einer bestehenden Beta-Installation auf 1.0.0 ist nicht vorgesehen.
