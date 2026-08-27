# Finanzen & Bussen

## Finanzen

Unter *Finanzen* werden Konten und Buchungen für den Verein geführt. `admin` und
`kassier` dürfen Konten und Buchungen lesen und bearbeiten. `reader` und `writer`
dürfen die Finanzdaten nur lesen.

## Bussen

Bussen (`Fines`) lassen sich pro Protokoll bzw. pro Teilnehmer erfassen und
nachverfolgen (offen/bezahlt). Die Bearbeitung ist `kassier` und `admin`
vorbehalten. `writer` darf alle Bussen des aktuellen Vereins lesen, aber nicht
verändern. `reader` sieht ausschliesslich Bussen, die einem mit seinem Konto
verknüpften Teilnehmerdatensatz zugeordnet sind.
