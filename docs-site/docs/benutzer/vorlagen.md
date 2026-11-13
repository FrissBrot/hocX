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

## Vorlagen {#vorlagen}

Eine **Vorlage** (`Templates`) definiert den Aufbau eines Protokolltyps:

- **Elemente** entsprechen Traktanden/Abschnitten.
- Jedes Element enthält **Blöcke**: Text, Tabelle (`form`), Matrix, Terminliste
  (`event_list`), Bilder, Todos, Anzeige-Inhalte.
- Elemente/Blöcke können sich **pro Termin** oder **pro Todo** wiederholen
  (`repeat_source`).
- Tabellenzeilen können optional fest mit einer Zeile aus einer zentralen [Stammliste](listen.md)
  verknüpft werden ("Zeile aus Liste", siehe [Stammlisten](listen.md#verknuepfen)) – Änderungen an der Liste spiegeln sich dann live
  im Protokoll, solange es nicht abgeschlossen ist.

Änderungen an einer Vorlage wirken sich **nur auf künftig daraus erstellte Protokolle**
aus, nie rückwirkend auf bestehende (siehe [Snapshot-Prinzip](erste-schritte.md)).

## Bausteinbibliothek {#bausteine}

Unter *Bausteine* liegen wiederverwendbare Elemente mit ihren Blöcken. Ein Baustein lässt sich in
mehrere Vorlagen einfügen; Änderungen am Baustein gelten für künftig erstellte Protokolle. Ist ein
Baustein mit einer [Stammliste](listen.md#verknuepfen) verknüpft, lässt sich diese Liste nicht
löschen, solange die Verknüpfung besteht.

## Bussenliste {#bussenliste}

Der Baustein **Bussenliste** zeigt im Protokoll und im PDF die Bussen aller Mitglieder. Anlegen,
einstellen (Konto, Zeitraum, nur offene, nach Person) oder als Baustein aus der Bibliothek in eine
Vorlage einfügen kann ihn deshalb nur, wer Zugriff auf die Finanzen hat (Berechtigung
«Kassenbuch ansehen»).
Titel und Darstellung ändern und den Baustein entfernen geht auch ohne.

## Bussentarif {#bussentarif}

Über *Bussentarif* in der Vorlage legt man fest, welche Bussen die Anwesenheitsblöcke dieser
Vorlage verwenden: den Tarif des Vereins (*Finanzen › Bussen*) oder einen eigenen Tarif nur für
diese Vorlage. Änderungen gelten sofort für alle offenen Protokolle der Vorlage; bereits erfasste
Bussen behalten ihren Betrag. Mehr dazu unter [Finanzen & Bussen](finanzen.md).

## Anliegen und Traktanden {#anliegen}

Die sichtbaren Elemente einer Vorlage sind die Traktanden, unter die [Anliegen](anliegen.md)
eingeordnet werden. Die Vorlage braucht dafür keinen eigenen Block: Anliegen erscheinen
automatisch unter ihrem Traktandum, ohne Traktandum unter «Weitere Anliegen».

## Sitzungs-Design {#design}

Wie das PDF eines Protokolls aussieht (Titelseite, Kopf- und Fusszeile, Darstellung der Blöcke),
legt eine Dokumentvorlage im [Document Studio](dokumente.md#vorlagen) fest. Dort lässt sie sich im
[Visual Designer](dokumente.md#designer) in den Modi «Einfach», «Erweitert» oder «Experte»
anpassen.
