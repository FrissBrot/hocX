# Word-Import

Altprotokolle als **.docx** oder **.pdf** (auch als **.zip** mit mehreren Dateien)
einlesen und daraus neue, echte hocX-Protokolle anlegen – statt sie manuell
nachzutippen.

## Ablauf

1. Datei(en) unter **Tools → Word-Protokoll-Import** (`/tools/word-import`) hochladen.
2. hocX analysiert den Text automatisch und schlägt vor:
   - **Anwesenheit** (wer war da / entschuldigt / unentschuldigt)
   - **Termine** (nächste Sitzung, weitere erwähnte Daten)
   - **Listen-Zuordnungen** (z. B. Zeilen aus einer zentralen [Liste](listen.md))
   - **Matrizen** und **Freitext-Abschnitte** (inkl. Fett-/Kursiv-Formatierung und
     Absätze aus dem Originaldokument)
3. Ein Review-Wizard zeigt alle Vorschläge zur Kontrolle. Unklare Abschnitte werden als
   **"Unvollständig"** markiert statt geraten – sie lassen sich manuell korrigieren oder
   bewusst **ignorieren**.
4. Erst nach Bestätigung wird daraus ein reguläres Protokoll erzeugt (Vorlage und
   Teilnehmerkreis werden vorher ausgewählt).

## Warteschlange für mehrere Dokumente

Unter **Tools → Import** (`/tools/import`) lassen sich mehrere Altprotokolle sammeln und
nacheinander abarbeiten. Jeder bestätigte Import analysiert die restlichen, noch offenen
Dokumente in der Warteschlange automatisch neu, um deren Vorschläge zu verbessern –
bereits vorgenommene manuelle Korrekturen bleiben dabei erhalten.

## Grenzen

Der Import ist eine **Hilfestellung**, kein Automatismus ohne Kontrolle: Er ersetzt nicht
das Gegenlesen vor dem Abschliessen des Protokolls. Layout-Elemente, die im Originaldokument
nicht eindeutig einem Blocktyp der Vorlage zuordenbar sind, werden als Freitext übernommen.
