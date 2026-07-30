# Zyklen & Vorlagen

## Zyklen

Ein **Zyklus** (`Cycles`) bündelt eine Vereinsperiode (z. B. ein Vereinsjahr) und liefert
Platzhalter, die in Vorlagen verwendet werden können:

- `{cycle_name}`
- `{cycle_year_start}`
- `{cycle_year_end}`

Diese Platzhalter lassen sich in Elementtiteln und Blocktexten einsetzen (z. B.
`"SOLA {cycle_year_start}"`), sodass ein wiederkehrender Programmpunkt nicht jedes Jahr
neu angelegt werden muss – die Auflösung passiert automatisch beim Erstellen eines
Protokolls aus der Vorlage.

## Vorlagen

Eine **Vorlage** (`Templates`) definiert den Aufbau eines Protokolltyps:

- **Elemente** entsprechen Traktanden/Abschnitten.
- Jedes Element enthält **Blöcke**: Text, Tabelle (`form`), Matrix, Terminliste
  (`event_list`), Bilder, Todos, Anzeige-Inhalte.
- Elemente/Blöcke können sich **pro Termin** oder **pro Todo** wiederholen
  (`repeat_source`).
- Tabellenzeilen können optional fest mit einer Zeile aus einer zentralen [Liste](listen.md)
  verknüpft werden ("Zeile aus Liste") – Änderungen an der Liste spiegeln sich dann live
  im Protokoll, solange es nicht abgeschlossen ist.

Änderungen an einer Vorlage wirken sich **nur auf künftig daraus erstellte Protokolle**
aus, nie rückwirkend auf bestehende (siehe [Snapshot-Prinzip](erste-schritte.md)).
