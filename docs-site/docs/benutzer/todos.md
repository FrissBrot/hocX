# Pendenzen

Pendenzen (Aufgaben), die aus einem Protokoll heraus entstehen, lassen sich zentral unter
*Todos* verfolgen und im Protokoll wieder darstellen – Pendenzen-Blöcke können sich analog zu
Terminen auch «pro Pendenz» wiederholen. Daneben entstehen Pendenzen automatisch aus
[Aufgabenpaketen](aufgabenpakete.md) und aus der [Abgabebox](#abgabe-pendenzen).

## Status und Abhaken {#status}

Jede Pendenz hat einen Status:

| Status | Bedeutung |
|---|---|
| **Offen** | Noch nicht begonnen. |
| **In Arbeit** | Jemand ist daran. |
| **Erledigt** | Abgeschlossen. Das Erledigungsdatum wird gespeichert. |
| **Abgebrochen** | Wird nicht mehr gemacht. Gilt nicht als Verspätung. |

Den Status änderst du direkt in der Liste oder im Pendenz-Popup. Wer eine Pendenz erledigt,
hakt sie damit ab. Wird eine erledigte Pendenz später nochmals bearbeitet (z. B. eine Notiz
ergänzt), bleibt das Erledigungsdatum gleich.

## Fälligkeit {#faelligkeit}

Über das Fälligkeitsmenü einer Pendenz wählst du:

- **Kein Enddatum**: Die Pendenz hat keine Fälligkeit.
- **Nächster Hock**: Ein Sitzungsmarker. Die Pendenz ist auf die nächste Sitzung fällig und
  rutscht automatisch mit, bis sie erledigt ist.
- **Schnellwahl**: «Ende Woche», «Ende Monat» oder «In 2 Wochen» – das berechnete Datum steht
  jeweils daneben.
- **Eigenes Datum**: ein beliebiges Datum (TT.MM.JJJJ).
- **Suche**: Im Feld «Datum oder Termin suchen …» findest du Daten wie «Morgen» oder «Ende
  nächster Monat» und **Termine**. Wählst du einen Termin, ist die Pendenz auf dessen Datum
  fällig und folgt ihm, wenn der Termin verschoben wird.

## Mehrere Verantwortliche {#verantwortliche}

Eine Pendenz kann eine oder mehrere verantwortliche Personen haben. Alle Verantwortlichen sehen
die Pendenz als ihre eigene, bekommen die [Erinnerungen](#erinnerungen) und werden bei einer
[Busse](#busse) je einzeln gebüsst.

## Abgabe-Pendenzen {#abgabe-pendenzen}

Eine Abgabe in der [Abgabebox](abgabebox.md) kann für die verantwortlichen Personen
Pendenzen anlegen. Diese **Abgabe-Pendenzen** werden automatisch erledigt, sobald die passende
Einreichung eingegangen ist («Wird automatisch durch die Abgabe geschlossen»). Ihren Status
kannst du nicht von Hand ändern. Wird eine Abgabe-Pendenz durch eine Einreichung erledigt,
bekommen alle Verantwortlichen eine Mail.

## Erinnerungen {#erinnerungen}

hocX schickt zu offenen Pendenzen E-Mails (siehe [Benachrichtigungen](benachrichtigungen.md)):

- **Neu verantwortlich**: Bei Pendenzen ohne Protokoll (auch aus Aufgabenpaketen und der
  Abgabebox) beim Erstellen bzw. wenn jemand neu verantwortlich wird. Bei Pendenzen aus einem
  Protokoll erst, wenn das Protokoll **abgeschlossen** wird – dann alle offenen auf einmal.
- **Fällig in 3 Tagen**: drei Tage vor der Fälligkeit.
- **Überfällig**: am Tag nach der Fälligkeit.

Die Erinnerungen laufen einmal täglich ab 07:00 Uhr und kommen je Pendenz, Person und
Fälligkeit nur einmal. Wer sich selbst eine Pendenz gibt, bekommt dafür keine Mail. Erledigte
und abgebrochene Pendenzen lösen keine Erinnerung mehr aus.

## Notizen und Dateien

Ein Klick auf eine Pendenz in der Liste öffnet das Bearbeiten-Popup. Dort gibt es:

- **Notizen**: freier Text mit demselben Editor wie im Protokoll (fett, kursiv, Aufzählungen,
  nummerierte Listen). Markdown wird direkt formatiert angezeigt.
- **Dateien**: über das Suchfeld lassen sich bereits hochgeladene Dateien (Dateien- und
  Fotos-Seite) mit der Pendenz verknüpfen. Ein Klick auf eine Datei öffnet sie, das ✕ entfernt
  nur die Verknüpfung, nicht die Datei.

Änderungen werden mit «Speichern» übernommen. **Escape** bricht ab und verwirft die
ungespeicherten Änderungen. Notizen und Dateien sind nur in diesem Popup sichtbar, nicht in der
Liste, der Übersicht, im Protokoll oder in Exporten.

## Busse {#busse}

Mit dem Zusatzmodul [Pendenzen-Bussen](bussen.md) kostet eine zu spät erledigte Pendenz eine
Busse. Solange die Pendenz überfällig ist, läuft die Busse; beim Erledigen wird sie je Person
eingefroren und bleibt danach bestehen – auch wenn die Pendenz wieder geöffnet, verschoben oder
gelöscht wird (siehe [Wann eine Busse eingefroren wird](bussen.md#einfrieren)). Wer eine Busse
wieder entfernen darf, steht unter [Storno](bussen.md#storno).

Im Pendenz-Popup zeigt der Kasten **Busse** den aktuellen Stand. Wer «Finanzen verwalten» hat,
kann dort die Busse [von Hand festlegen](bussen.md#von-hand). Dieser Kasten speichert separat mit
**Übernehmen**, unabhängig vom Speichern der Pendenz.
