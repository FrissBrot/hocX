# Upload-Verlauf

Jeder Upload ist in hocX ein **Vorgang**: alles, was du in einem Durchgang hochlädst, gehört
zusammen – auch wenn hocX grosse Auswahlen intern in mehrere Pakete teilt, Duplikate gar nicht erst
überträgt oder der Browser einzelne Dateien ablehnt. Den Verlauf findest du unter
**Fotos › Uploads** bzw. **Ablage › Uploads**.

## Liste der Uploads {#liste}

Je Upload siehst du Zeitpunkt, Person (bzw. «Abgabebox», «Persönlicher Link», «Plattform-Import»),
den Weg (Foto-Upload, Ablage, Pendenz, Datei-Import, Word-Import, Abgabe …), den Bezug (Termin,
Abgabe, Zyklus, Protokoll) und das Ergebnis, z. B. «48 hochgeladen · 3 Duplikate · 1 abgelehnt».

- **Meine / Alle:** Alle Uploads siehst du mit dem Recht des Bereichs (Fotos bzw. Ablage verwalten).
  Ohne dieses Recht siehst du nur deine eigenen.
- **Weg, Zeitraum, nur mit Problemen** grenzen die Liste ein. «Mehr laden» holt ältere Uploads.
- Abgabebox und persönliche Abgabe-Links sehen die Verantwortlichen der Abgabe (Leserecht der
  Abgaben, bei «nur zugewiesene» nur ihre Abgaben). Protokollbilder erscheinen nur, wenn du
  ausdrücklich nach ihnen filterst; je Protokoll und Tag gibt es einen Upload.

## Einen Upload bearbeiten {#bearbeiten}

Nach jedem Upload bietet die Zusammenfassung **Bearbeiten** an; zusätzlich erscheint oben auf der
Seite ein Hinweis «48 Fotos hochgeladen – Bearbeiten» (24 Stunden, mit ✕ ausblendbar).

Im Upload findest du:

- **Fotos:** das bekannte Raster, nur mit den Fotos dieses Uploads. **Alle dieses Uploads
  auswählen** wählt auch die noch nicht geladenen Fotos (bis 10 000). Tags, Alben, Keywords, Beste,
  Termin, Aufnahmedatum und Papierkorb wirken wie gewohnt; grosse Auswahlen werden in Teilen
  gespeichert, du siehst den Fortschritt («Tags werden gesetzt … 400/1240») und kannst abbrechen.
  Fotos, die du nicht ändern darfst, bleiben ausgenommen – hocX nennt die Anzahl.
- **Ergebnisliste:** jede Datei mit Ergebnis und Grund: hochgeladen, Duplikat (mit Link auf die
  vorhandene Datei), Metadaten ergänzt, abgelehnt (zu gross, Format …), Virenfund, verworfen
  (Abbrechen in der Pendenz). «vom Browser gemeldet» heisst: der Browser hat die Datei gar nicht erst
  gesendet. Später gelöschte Dateien erscheinen als «im Papierkorb» bzw. «Datei gelöscht».
- **Datumskorrekturen:** alle Änderungen am Aufnahmedatum für diesen Upload, mit **Rückgängig**.
- **Kameras:** jede Kamera mit Anzahl Fotos und Zeitraum. Zwei Geräte desselben Modells
  unterscheidet hocX über ein verschlüsseltes Kürzel der Seriennummer (die Seriennummer selbst wird
  nie gespeichert). «Nur diese auswählen» wählt die Fotos einer Kamera, «Zeit verschieben …» öffnet
  die Datumskorrektur dafür. Liefert die Kamera GPS-Zeit, schlägt hocX einen Versatz vor
  («geht vermutlich 1 h 14 min vor»).

**Termin zuordnen:** In der Auswahlleiste ordnet **Termin** Fotos fest einem Termin zu oder gibt sie
an die automatische Zuordnung nach Aufnahmedatum zurück.

## Aufnahmedatum verschieben {#verschieben}

Typisch bei einer falsch gestellten Kamera: Fotos auswählen, **Aufnahmedatum › Verschieben**.

- **Um einen Versatz:** Richtung **früher** oder **später**, dazu Tage, Stunden und Minuten.
  «früher, 1 Std. 15 Min.» verschiebt alle gewählten Fotos um 1 h 15 min nach vorne.
- **Nach Referenzfoto:** ein Foto der Auswahl wählen und entweder die richtige Uhrzeit eingeben
  (z. B. ein Foto einer Uhr oder des Anpfiffs) oder ein Foto einer richtig gestellten Kamera, das
  denselben Moment zeigt. hocX berechnet den Versatz sekundengenau und wendet ihn auf die Auswahl an.
- **Vorschau** zeigt vorher, wie viele Fotos sich ändern, welche übersprungen werden (ohne
  Aufnahmedatum), wie viele den Kalendertag oder den automatisch zugeordneten Termin wechseln, und
  einige Beispiele mit «vorher → nachher». **Übernehmen** wendet genau diese Einstellung an.
- Fotos **ohne Uhrzeit** (nur geschätztes Datum) verschieben sich nur um ganze Tage.
- Gerechnet wird in Kamerazeit; die gespeicherte Zeitzone der Kamera bleibt unverändert, auch über
  eine Sommerzeit-Umstellung hinweg. Wiederholtes Verschieben summiert sich.
- **Rückgängig:** direkt im Hinweis nach dem Anwenden oder später im Reiter «Datumskorrekturen».
  Zurückgesetzt wird jedes Foto auf seinen Stand davor – ausser es wurde inzwischen anders geändert.
  Rückgängig geht, solange die Fotos existieren.

Die Foto-Ansicht zeigt beim Feld «Hochgeladen» einen Link auf den Upload («über Upload mit 48
Dateien»), sofern du ihn sehen darfst.

## Aufbewahrung {#aufbewahrung}

Ein Upload bleibt im Verlauf, solange mindestens eine seiner Dateien existiert (auch im
Papierkorb). Ist die letzte Datei endgültig gelöscht, verschwindet der Upload sofort. Uploads ohne
gespeicherte Datei (nur Duplikate oder Ablehnungen) bleiben 30 Tage. Uploads vor Version 1.6 hat
hocX nachträglich rekonstruiert; sie tragen den Hinweis «rekonstruiert», ihre Zusammensetzung ist
ungefähr und Duplikate oder Ablehnungen sind dafür nicht bekannt.
