# Dateien importieren

Mit dem Datei-Import übernimmt ein Verein eine bestehende Ablage in einem Durchgang nach hocX -
zum Beispiel den Vereinsordner aus OneDrive, Google Drive oder Dropbox. Zu finden unter
**Dateien › Importieren**.

!!! info "Wer darf importieren?"
    Die Berechtigung **Dateien importieren** hat standardmässig nur die Rolle *Administrator*. Sie lässt
    sich unter *Rollen* auch eigenen Rollen geben. Für Bilder braucht es zusätzlich «Dateien & Fotos
    verwalten». Es läuft immer nur ein Import pro Verein gleichzeitig.

## Quellen

| Quelle | Wann | Hinweise |
|---|---|---|
| **ZIP-Archiv** | Download aus OneDrive/Dropbox, Google Takeout, Archiv vom PC | Mehrere ZIPs pro Import möglich (z. B. Takeout-Teilarchive), je bis 10 GB. Bei Google Takeout wird der Ordner «Takeout» automatisch erkannt. Die Metadaten-Dateien (`.json`) werden nicht importiert, ihr Aufnahmedatum aber übernommen, wenn das Foto selbst keines hat (siehe unten). |
| **Ordner hochladen** | Synchronisierter Ordner auf dem PC (OneDrive, Google Drive, …) | Zuerst wird nur die Dateiliste übertragen. Nach dem Start lädt der Browser genau die Dateien hoch, die importiert werden - das Fenster muss dafür offen bleiben. Wird es geschlossen, denselben Ordner später erneut wählen; der Upload geht weiter. |

Direkte Verbindungen zu OneDrive und Google Drive folgen in einer späteren Version.

Grenzen: höchstens 50 000 Dateien und 100 GB pro Import; Dokumente bis 20 MB, Bilder bis 100 MB
(wie beim normalen Hochladen). Grössere oder nicht unterstützte Dateien erscheinen im Bericht.

## Regeln

Regeln werden der Reihe nach auf jede Datei angewendet. Eine Regel hat Bedingungen (alle müssen
passen) und eine Aktion.

**Bedingungen**

- **Im Ordner** - die Datei liegt in diesem Ordner oder einem Unterordner.
- **Pfad-Muster** - `*` steht für beliebige Zeichen innerhalb eines Ordners, `**` für beliebig
  viele Ordner, `?` für ein Zeichen. Ein Muster ohne `/` prüft nur den Dateinamen (`*.pdf`).
  Beispiele: `Fotos/20??/*`, `**/Lager/**`.
- **Dateiname (regulärer Ausdruck)** - z. B. `^IMG_\d+` oder `(?i)protokoll`. Rückverweise und
  Lookarounds werden aus Sicherheitsgründen nicht unterstützt.
- **Dateityp** - Bilder, Dokumente oder beide.

**Aktionen**

| Aktion | Wirkung |
|---|---|
| Tags hinzufügen | Tags aller passenden Regeln werden zusammengeführt. |
| Aufnahmedatum setzen, wenn es fehlt | Nur Bilder. Gilt nur, wenn die Datei selbst kein Aufnahmedatum hat, und erscheint als «geschätzt». Passen mehrere Regeln, gilt die erste (andere werden als Konflikt angezeigt). |
| Nicht importieren | Gewinnt immer. Die Datei wird weder übertragen noch importiert. |
| In Album einordnen | Nur Bilder, nur mit eingeschalteter Option «Bilder per Regel in Alben einordnen»: in ein bestehendes oder ein neues Album. |
| Album nach Ordnernamen | Nur Bilder, nur mit eingeschalteter Option: ein Album je Ordner (direkter oder oberster Ordner). |

**Alben sind standardmässig aus.** Ohne die Option kommen Bilder einfach in die Galerie; sie lassen
sich später über die Mehrfachauswahl einem Album zuordnen. Gibt es im Verein schon ein Album mit
genau diesem Namen, wird es ergänzt statt ein zweites anzulegen (bei mehreren gleichnamigen das
älteste; der Bericht nennt das). Alben anderer Vereine (geteilte Alben) werden nie verändert.

**Aufnahmedatum:** Es gilt immer das Datum aus der Datei (EXIF). Fehlt es, übernimmt hocX bei Google
Takeout das Datum aus der Metadaten-Datei (`photoTakenTime`), sonst das Datum einer Datumsregel. Beide
erscheinen als «geschätzt».

Zusätzlich lassen sich die **Ordnernamen als Tags** übernehmen (nichtssagende Namen wie «Neuer
Ordner» oder «Desktop» werden ausgelassen). hocX kennt keine Ordner in der Ablage: die
Ordnerstruktur bleibt über Tags und Alben erhalten.

## Vorschau, Start, Bericht

Die Vorschau zeigt für jede Datei, ob sie importiert wird, mit welchen Tags, welchem Datum und in
welchen Alben, und welche Regeln getroffen haben. Reicht das Speicherkontingent nicht, lässt sich
der Import nicht starten.

Nach dem Start lassen sich die Regeln nicht mehr ändern. Jede Datei durchläuft die gleichen
Prüfungen wie ein normaler Upload (Virenprüfung, Inhaltstyp, Duplikate, Kontingent). Bereits
vorhandene Dateien werden nicht doppelt gespeichert; sie bekommen aber die Tags und Alben aus den
Regeln dazu (nur ergänzt, nie entfernt) und erscheinen im Bericht als «Duplikat, ergänzt». Ein Import lässt sich jederzeit abbrechen;
bereits importierte Dateien bleiben. Ein unterbrochener Import (z. B. Kontingent voll) lässt sich
fortsetzen.

Der **Bericht** listet jede Datei mit Ergebnis und Grund. Er bleibt erhalten, solange mindestens
eine importierte Datei existiert.
