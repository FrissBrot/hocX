# Testbook: Word-Import und historische Listen

Dieses Testbook verbindet reproduzierbare Testdateien mit automatisierten End-to-End-
Prüfungen. Es schützt insbesondere die Übergänge zwischen öffentlichen UUIDs und
internen IDs, Datumsinterpretation und historische Daten. Die Tests verwenden echte
HTTP-Endpunkte, DOCX-Parser, Datenbank und Chromium; Importantworten werden nicht gemockt.

## Ausführung

Der vollständige, isolierte Lauf inklusive Anmeldung und Aufräumen:

```bash
./scripts/e2e.sh all
```

Die Importfälle liegen in `frontend/e2e/word-import.spec.ts` und
`frontend/e2e/word-import-history.spec.ts` und werden automatisch von Playwright/CI
gefunden. Bei bereits gestarteter E2E-Umgebung:

```bash
cd frontend
PLAYWRIGHT_BASE_URL=http://127.0.0.1:13000 npx playwright test \
  e2e/word-import.spec.ts e2e/word-import-history.spec.ts --workers=1
```

Nach einer erfolgreichen Anmeldung kann zur lokalen Wiederholung
`--project=chromium --no-deps` verwendet werden. Für einen frischen vollständigen Lauf
den E2E-Stack zurücksetzen: MFA-Einrichtung und Cookies gehören zur jeweiligen
Testdatenbank. Niemals gegen Produktion ausführen. Die Tests erzeugen abgeschlossene
Protokolle und belassen ihre Daten zur Diagnose bis zum Abbau des isolierten Stacks.

## Testdateien und feste Sollwerte

`frontend/e2e/fixtures/word-import/manifest.json` enthält die Sollwerte. Die zugehörigen
DOCX-Dateien und das ZIP sind eingecheckt, enthalten ausschließlich synthetische Daten
und lassen sich mit dem Backend-Paket `python-docx` erneut erzeugen:

```bash
python backend/scripts/generate_word_import_e2e_fixtures.py
```

ZIP-Zeitstempel und Dokument-Metadaten sind fest, damit die Erzeugung reproduzierbar ist.
Das Dokumentdatum wird bewusst von Datei-Metadaten und heutigem Datum getrennt.

Der Testzyklus endet am **31. Juli**. Der Folgetag gehört zum nächsten Zyklus.

| Datei | Protokolldatum | Zyklusjahr | Feuer / Küche |
|---|---|---|---|
| german-date.docx | 2023-10-14 | 2023 | Herbst 2023 / Menü – Herbst 2023 |
| leap-day.docx | 2024-02-29 | 2023 | Schalttag 2024 / Menü – Schalttag 2024 |
| cycle-end.docx | 2024-07-31 | 2023 | Zyklusende 2024 / Menü – Zyklusende 2024 |
| cycle-start.docx | 2024-08-01 | 2024 | Zyklusbeginn 2024 / Menü – Zyklusbeginn 2024 |
| year-end.docx | 2024-12-31 | 2024 | Silvester 2024 / Menü – Silvester 2024 |
| year-start.docx | 2025-01-01 | 2024 | Neujahr 2025 / Menü – Neujahr 2025 |
| no-date.docx | zunächst leer | erst nach Korrektur | Datum manuell / Menü – Datum manuell |
| historical-batch.zip | drei verschiedene Daten | 2023 und 2024 | unveränderte Einzeldateien, absichtlich unsortiert |

Die Live-Liste startet mit `LIVE HEUTE`. Dieser Wert muss nach jedem historischen
Import unverändert sein. Ein erfolgreicher HTTP-Status allein genügt nie: Die Tests
lesen Protokoll, Zyklus und gespeicherte Zeilen erneut über die API.

## Automatisierte Testfälle

| ID | Durchführung | Erwartung |
|---|---|---|
| IMP-01 (6 Varianten) | DOCX hochladen, Liste zuordnen, erneut analysieren, abschließen | Datum in Analyse, Protokoll, Titel und Warteschlange exakt; richtiger Zyklus; exakte Protokoll- und Historienzeilen; Live-Liste unverändert |
| IMP-02 | Direkter Multipart-Import mit Listen-UUID in `table_roles_json` | Analyse akzeptiert UUID und liefert dieselbe UUID zurück; zwei Listenzeilen |
| IMP-03 | 31.07. auf 01.08. korrigieren, neu laden und abschließen | Korrigiertes Datum bleibt erhalten; Zykluswechsel wird berücksichtigt |
| IMP-04 | Dokument ohne Datum abschließen, dann Schaltjahrdatum angeben | Kein erfundenes Datum; Abschluss ohne Datum abgelehnt; gültige Korrektur funktioniert |
| IMP-05 | ZIP in nicht chronologischer Reihenfolge importieren | Nur DOCX-Dateien werden übernommen; drei getrennte Protokolle; spätere Imports verändern frühere Protokollwerte nicht |
| IMP-06 | Dasselbe Queue-Dokument zweimal abschließen | Zweiter Abschluss abgelehnt; ursprünglicher Protokollverweis erhalten |
| IMP-07 | Im Browser „Neu analysieren“ und neu laden | Tatsächlich gesendete Listen-ID ist UUID; kein Integer-Validierungsfehler; Datum bleibt sichtbar |
| IMP-08 | Datei im Browser auswählen, Datum korrigieren, Werte prüfen und Protokoll erstellen | Ganzer Wizard funktioniert; gespeicherte Werte und korrigiertes Datum stimmen |
| IMP-09 | Beschädigte Datei, danach 24 echte Analysen derselben gültigen Datei | Fehler wird sauber abgewiesen; Parser bleiben bei Wiederverwendung funktionsfähig; Datum und Werte bleiben identisch |
| HIST-01 (2 Reihenfolgen) | Älteres und neueres Protokoll desselben Zyklus importieren | Neuester Protokollstand gewinnt unabhängig von Upload-Reihenfolge; Nachbarzyklus bleibt getrennt |
| HIST-02 | Historischen Wert manuell ändern, danach neueres Protokoll importieren | Änderung ohne Bestätigung abgelehnt; bestätigte manuelle Werte bleiben geschützt |
| HIST-03 | Vorhandene rekonstruierte Historie, danach Import | Bestehende historische Werte bleiben unverändert |
| HIST-04 | Neue Zeilen ausschließlich historisch importieren | Stabile UUIDs und getrennte Snapshot-Identitäten; keine neuen Live-Einträge |
| HIST-05 | Heutiges und zukünftiges Protokoll importieren | Keine vorzeitig erzeugte Historie für offene Zyklen |
| HIST-06 | Historischen Zyklus in Listenansicht öffnen, neu laden, anderen Mandanten abfragen | Exakte importierte Werte im Browser; fremder Mandant erhält keinen Zugriff |

IMP-02 und IMP-07 hätten den ursprünglichen `TablePreview.list_definition_id`-Fehler
gefunden. IMP-01 fand zusätzlich eine falsche `CycleAssignment`-ID beim Abschluss.
IMP-08 schützt vor dem Speichern eines leeren Entwurfs während des ersten Ladens.

## Regeln für automatisch ergänzte Historie

- Nur bestätigte Listenzeilen mit einem verknüpften Zielblock werden übernommen.
- Maßgeblich ist das bestätigte Protokolldatum und der Zyklus der Vorlage.
- Nur abgeschlossene Zyklen erhalten historische Listenstände.
- Reguläre und manuell bearbeitete Historie wird nicht überschrieben.
- Vom Import selbst erzeugte, unbearbeitete Historie darf ein neueres Protokoll desselben
  Zyklus aktualisieren. Bei identischem Datum bleibt der erste bestätigte Stand erhalten.
- Die Herkunft wird pro historischer Liste mit Protokoll-UUID und Datum gespeichert.
- Andere Listen, andere Zyklen und heutige Live-Werte bleiben erhalten.

## Ergänzende Prüfebenen und Grenzen

Die bestehenden Backend-Integrationstests `test_word_import_e2e.py`,
`test_word_import_multiday_events.py`, `test_word_import_attendance_status.py`,
`test_word_import_edge_cases.py` und `test_word_import_text_formatting.py` prüfen
zusätzlich PDF, Anwesenheit, Termine, mehrtägige Ereignisse, Matrizen, Namensauflösung
und Formatierung. Die hier beschriebenen Browserdateien konzentrieren sich auf
DOCX/ZIP, Datumsgrenzen und Listenhistorie; sie ersetzen keine Prüfung beliebiger
Word-Layouts oder gescannter PDF-Dateien.

Bei Fehlern liegen Screenshot, Video und Trace in `frontend/test-results/playwright`.
Ein roter Test wird nicht durch pauschale Retries oder gelockerte Sollwerte kaschiert.
Erst fachlichen Fehler, Testannahme und Infrastrukturfehler unterscheiden, dann korrigieren.
