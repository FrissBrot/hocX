# Dateien und Dokumente

Im Bereich **Dateien** stehen alle Dokumente deiner Organisation: direkt hochgeladene Dateien,
Einreichungen aus der Abgabebox, Word-/PDF-Importe und die exportierten Protokolle.

## Ein Eintrag pro Dokument

Jedes Dokument erscheint genau einmal. hocX erstellt dafür automatisch eine **PDF-Ansicht**,
auch wenn die Datei als Word-, OpenDocument-, RTF- oder Textdatei hochgeladen wurde. Ein Klick
auf **PDF öffnen** zeigt diese Ansicht.

Direkt nach dem Hochladen steht neben dem Namen kurz **In Verarbeitung** – die PDF-Ansicht und
der Text werden im Hintergrund erstellt, meist innerhalb weniger Sekunden bis Minuten. Die
Originaldatei ist in dieser Zeit schon verfügbar.

## Dokumentdetails

Ein Klick auf die Zeile öffnet die Details mit:

- der **Vorschau** der ersten Seite – ein Klick darauf öffnet das ganze PDF,
- **PDF herunterladen** und **Originaldatei herunterladen** (die Datei, so wie sie hochgeladen
  wurde, bleibt immer unverändert erhalten),
- **Extrahierten Text anzeigen** – der reine Text des Dokuments, z. B. zum Kopieren,
- der **Versionshistorie**, wenn es mehrere Versionen gibt.

Konnte ein Dokument nicht verarbeitet werden, zeigt der Status **Verarbeitung fehlgeschlagen**.
Mit **Erneut verarbeiten** (Schreibrechte nötig) startet hocX einen neuen Versuch.

## Suchen und Keywords {#suche}

Die Suche der Ablage arbeitet wie die [Fotosuche](fotos.md#suche): tolerant gegenüber Tippfehlern
und Umlauten, mit Synonymen, beste Treffer zuerst (solange du keine andere Sortierung wählst).
In den Dokumentdetails setzt du unter **Keywords** zusätzliche Suchbegriffe, die nirgends angezeigt
werden. Für mehrere Dateien: Kästchen in der Liste oder auf den Kacheln anwählen ›
**Keywords bearbeiten**. Keywords ändern braucht bei Dateien die Berechtigung «Dateien & Fotos verwalten», bei Fotos «Fotos verwalten».

## Protokollexporte und Versionen

Exportierst du ein Protokoll mehrmals, entsteht kein neuer Eintrag, sondern eine neue
**Version** desselben Dokuments – sofern sich der Inhalt geändert hat. Im Dateien-Tab steht
immer die aktuelle Version; ältere öffnest du in den Details unter **Versionen**. Mit dem
Filter **Protokollexporte** siehst du nur diese Dokumente.

## Upload-Verlauf {#upload-verlauf}

**Ablage › Uploads** zeigt jeden Upload mit dem Ergebnis je Datei (hochgeladen, Duplikat,
abgelehnt mit Grund). Details: [Upload-Verlauf](upload-verlauf.md).

## Papierkorb {#papierkorb}

Wer Dateien bzw. Fotos verwalten darf, kann direkt hochgeladene Dateien über das Menü **···**
einer Datei (bzw. in der Foto-Ansicht und der Mehrfachauswahl) **in den Papierkorb** legen. Eine
Datei im Papierkorb ist nirgends mehr zu sehen: nicht in Listen, Galerie, Suche, Alben,
Pendenzen und Exporten, und ein Freigabelink liefert sie nicht mehr aus.

Der **Papierkorb** (Knopf auf der Dateien- und der Fotos-Seite) zeigt, wer was wann gelöscht hat
und wie viele Tage bis zum endgültigen Löschen bleiben:

- **Wiederherstellen** bringt die Datei mit allem zurück: Alben, Tags, Termin- oder Abgabe-Bezug,
  Pendenz-Verknüpfungen und Freigabelinks.
- **Endgültig löschen** bzw. **Papierkorb leeren** entfernt sofort und unwiderruflich.
- Nach **30 Tagen** löscht hocX automatisch endgültig.

Bis dahin belegen Dateien im Papierkorb weiter Speicher und **zählen zum Speicherkontingent**
(Kategorie «Papierkorb» unter Abo & Speicher). Lädst du eine Datei aus dem Papierkorb erneut
hoch, wird sie normal gespeichert.

Löschungen nach Datenschutzrecht, das Löschen einer ganzen Organisation, Aufbewahrungsfristen und
das Löschen von Protokollen oder Abgaben samt Dateien gehen nicht über den Papierkorb: sie
löschen sofort und schliessen Dateien im Papierkorb mit ein.

## Gut zu wissen

- Bilder gehören in den Bereich **Fotos** (siehe [Fotos und Alben](fotos.md)); ZIP-Archive bleiben normale Dateien ohne
  PDF-Ansicht.
- Bei Tabellen und Präsentationen gibt es eine PDF-Ansicht, aber keinen extrahierten Text.
- Bei eingescannten PDFs versucht hocX, den Text automatisch zu erkennen. Das Ergebnis kann
  Fehler enthalten.
- Dateien, die bei der Virenprüfung auffallen, werden nicht verarbeitet und bleiben gesperrt.
