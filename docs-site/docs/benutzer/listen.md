# Stammlisten

Unter *Stammdaten → Stammlisten* pflegt der Verein frei aufgebaute Tabellen mit zwei Spalten,
z. B. eine Vorstandsliste (Funktion, Person), eine Ämtliliste oder ein Inventar. Die Seite steht
allen offen, die Protokolle bearbeiten dürfen.

## Liste anlegen {#anlegen}

*Neue Liste* öffnet das Formular: Name, optional eine Beschreibung und die zwei Spalten mit
Titel und Datentyp. Die Vorschau zeigt, wie die Tabelle aussehen wird. Mit dem Schalter *Aktiv*
lässt sich eine Liste stilllegen, ohne sie zu löschen.

## Datentypen {#datentypen}

Jede Spalte hat einen von vier Datentypen:

| Datentyp | Inhalt |
|---|---|
| **Text** | freier Text, z. B. «Kassier» oder «Zelt 3» |
| **Eine Person** | eine Person aus den Mitgliedern |
| **Mehrere Personen** | mehrere Personen aus den Mitgliedern |
| **Termin** | ein Verweis auf einen Termin |

Personen- und Termin-Spalten bleiben mit dem Mitglied bzw. Termin verbunden: eine
Namensänderung erscheint automatisch. Zeilen, in denen eine Person oder ein Termin noch fehlt,
zählt der Filter *Nicht zugewiesen*.

Wird der Datentyp einer Spalte nachträglich geändert, leert hocX die bisherigen Werte dieser
Spalte, weil sie zum neuen Typ nicht mehr passen.

## In Vorlagen verknüpfen {#verknuepfen}

Eine Liste kann in Vorlagen auf zwei Arten eingebunden werden:

- **Ganze Liste gekoppelt**: die komplette Liste erscheint live als Tabelle im Protokoll.
  Änderungen an der Liste wirken sich sofort aus.
- **Einzelne Zeile aus Liste**: eine Tabellenzeile in einer Vorlage wird fest mit einem
  Listeneintrag verknüpft. Pro Spalte lässt sich wählen, ob sie «fix» ist (übernimmt den Wert
  aus der Liste, mit optionalem Alias-Text) oder «variabel» (im Protokoll frei editierbar).

In beiden Fällen bleibt die Verknüpfung **live**, solange das Protokoll nicht abgeschlossen ist.
Ein abgeschlossenes Protokoll behält den Stand vom Abschluss.

## Quelle für Abgaben und Aufgabenpakete {#abgaben}

Eine Liste kann Quelle einer [Abgabe](abgabebox.md#quelle) sein: Jede Zeile bekommt ein eigenes
Abgabefeld, die Person aus der Personenspalte wird verantwortlich. Neue, geänderte und gelöschte
Zeilen führen die Abgabe-Todos sofort nach.

## Historische Ansicht {#historisch}

Oben rechts lässt sich statt der aktuellen Liste der Stand eines früheren Zyklus anzeigen. Gibt
es für diesen Zyklus einen gespeicherten Stand, zeigt hocX ihn schreibgeschützt; nach einer
Rückfrage lässt er sich trotzdem korrigieren. Fehlt ein gespeicherter Stand, kann hocX ihn aus den
damaligen Protokollen **rekonstruieren**: die Vorschau zeigt die gefundenen Zeilen, gespeichert
wird erst nach der Bestätigung.

## Exportieren {#export}

Über das Aktionsmenü der Liste → *Exportieren* entsteht ein Dokument mit dem Inhalt der Liste,
gestaltet mit den Vorlagen aus dem [Document Studio](dokumente.md).

## Gruppen für die Statistik {#gruppen-statistik}

Mit dem Schalter *Quelle der Gruppenstatistik* im Listenformular wird eine Liste zur Quelle der
Gruppen in der [Statistik](statistik.md#gruppen). Ihre Einträge (Text in einer der zwei Spalten)
gelten dann als Gruppennamen; gezählt werden Termine, deren Tag einem Eintrag entspricht. Der Name
der Liste spielt keine Rolle mehr.

## Löschen {#loeschen}

Eine Liste lässt sich nur löschen, solange kein Baustein und kein Protokoll mehr auf sie
verweist. Sonst nennt hocX die betroffenen Bausteine und Protokolle. Dort die Verknüpfung
entfernen oder die Liste stattdessen auf *inaktiv* stellen. Inaktive Listen bleiben mit allen
Einträgen erhalten.
