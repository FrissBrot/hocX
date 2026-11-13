# Statistik und Dashboard

hocX zeigt auf zwei Seiten Kennzahlen: das **Dashboard** (Startseite) mit dem, was gerade
ansteht, und die **Statistiken** mit Auswertungen über längere Zeit. Beide lesen dieselben Daten
wie die übrigen Seiten. Es gibt keine eigene Erfassung.

## Dashboard {#dashboard}

Die Startseite fasst den Alltag zusammen. Welche Kacheln erscheinen, hängt von den Rechten und vom
Abo ab:

- **Nächste Sitzung** und **Teilnehmer entschuldigen**: die Anwesenheitsliste des nächsten
  Protokolls. Ein Klick auf einen Namen entschuldigt die Person bzw. hebt das wieder auf. Das geht
  nur mit dem Recht, Protokolle zu bearbeiten; sonst sind die Namen gesperrt und ein Hinweis
  erklärt das.
- **Meine Todos** und **Kommende Termine**.
- **Offene Bussen**: mit dem Recht für persönliche Auswertungen alle offenen Bussen, sonst nur die
  eigenen («Meine offenen Bussen»). Nur sichtbar, wenn Finanzen gebucht sind.
- **Kontostände** für alle, die Finanzen verbuchen dürfen, und **Abgaben mit Frist** für alle,
  die Abgaben verwalten.

## Statistiken {#statistiken}

*Statistiken* (neben dem Dashboard) zeigt:

| Bereich | Inhalt |
|---|---|
| **Kennzahlen** | durchgeführte oder abgeschlossene Protokolle, aktive Mitglieder, Todos (davon offen), Anzahl und Summe der Bussen je Währung |
| **Gruppen** | Termine je Gruppe und durchschnittliche Teilnehmerzahl, siehe [unten](#gruppen) |
| **Zeitverlauf** | Anwesenheit je Monat oder je Person, Einnahmen und Ausgaben je Monat und Konto |
| **Übersicht** | Todos erledigt/offen, Bussen nach Art, Bussen je Person (Top 10) |

Die Zeitreihen lassen sich auf die letzten 3, 6 oder 12 Monate einschränken. Beträge erscheinen
in der Währung des Vereins ([Einstellungen](einstellungen.md#finanzen)).

### Woher die Zahlen kommen {#herkunft}

- **Anwesenheit** stammt aus den Anwesenheitsblöcken der Protokolle, die *durchgeführt* oder
  *abgeschlossen* sind. Vorbereitete Protokolle zählen noch nicht, weil sich die Anwesenheit bis
  zur Sitzung ändern kann.
- **Protokolle** zählt ebenfalls nur durchgeführte und abgeschlossene Protokolle.
- **Todos** umfasst Todos aus Protokollen, freie Todos und Todos aus Abgaben.
- **Bussen** sind die Anwesenheitsbussen aus den Protokollen; begründet gelöschte Bussen zählen
  nicht.
- **Finanzen** sind die Buchungen der Konten. Sie erscheinen nur mit dem Recht, Finanzen zu sehen.

## Gruppen {#gruppen}

Gruppen sind die Einträge einer [Stammliste](listen.md#gruppen-statistik), die im Listenformular
als **Quelle der Gruppenstatistik** markiert ist (z. B. eine Liste mit Stufen oder Teams). Gezählt
werden Termine, deren **Tag** genau einem Eintrag dieser Liste entspricht, und zwar je Zyklus:

- *Termine je Gruppe*: alle Termine mit diesem Tag, davon jene mit erfasster Teilnehmerzahl.
- *Ø Teilnehmer*: durchschnittliche Teilnehmerzahl der Termine, bei denen eine Zahl erfasst ist.

Über die Zyklusauswahl beim Abschnitt lässt sich ein einzelner Zyklus anzeigen. Bleibt der
Abschnitt leer, fehlt entweder die markierte Liste oder es gibt noch keine Termine mit einem
passenden Tag. Der Hinweis auf der Seite sagt, was davon zutrifft.

## Wer was sieht {#sichtbarkeit}

- **Je Person** (Anwesenheit und Bussen je Person): Schreibende, Kassier und Admins sehen alle
  Personen. Mitglieder mit Leserecht sehen nur ihre eigenen Werte, ausser der Verein gibt die
  Ranglisten unter *Einstellungen › Datenschutz* für alle frei. Ein Hinweis oben auf der Seite
  zeigt, wenn nur die eigenen Werte erscheinen.
- **Nur bestimmte Vorlagen**: Wer nur einzelnen Protokollvorlagen zugeordnet ist, sieht auch in
  der Statistik nur Zahlen aus diesen Vorlagen (Protokolle, Anwesenheit, Todos, Bussen). Gruppen
  und Mitgliederzahlen beruhen auf Terminen bzw. Mitgliedern und gelten für den ganzen Verein.
- Dieselben Regeln gelten für Diagramme und Tabellen in [Dokumenten](dokumente.md), die mit dem
  Document Studio erzeugt werden.
