# Finanzen & Bussen

Unter **Finanzen** führt dein Verein seine Kasse: ein oder mehrere **Konten** (z. B. «Kasse»,
«Bank»), darauf die **Buchungen** (Einnahmen und Ausgaben) mit laufendem Saldo. Unter
**Bussen** stehen die Präsenz-Bussen (zu spät, unentschuldigt abwesend) und – falls gebucht –
die Pendenzen-Bussen (Pendenz zu spät erledigt). Einkassierte Bussen landen automatisch als
Buchung auf dem Konto, das im Bussentarif hinterlegt ist.

!!! info "Was hocX nicht abbildet"
    Mitgliederbeiträge, Rechnungen und offene Forderungen gibt es in hocX nicht. Erfasse
    eingegangene Beiträge als gewöhnliche Einnahme.

!!! info "Berechtigungen"
    Konten und Buchungen ansehen braucht «Kassenbuch ansehen» (Standardrollen: alle). Buchen,
    Konten anlegen und Bussen bearbeiten braucht «Finanzen verwalten» (Admin, Kassier). Die
    Bussen **aller** Mitglieder sieht nur, wer «Personenbezogene Daten aller» hat (Admin,
    Schreiber, Kassier) – alle anderen sehen nur ihre eigenen Bussen, auch in Exporten und im
    Dashboard. Siehe [Rollen & Berechtigungen](rollen.md).

## Konten {#konten}

- **Konto anlegen**: In *Finanzen* auf **Konto anlegen** (bzw. **+** neben «Konten»). Der Name
  ist Pflicht, die Beschreibung ist optional und lässt sich jederzeit wieder leeren.
- **Währung**: gilt für den ganzen Verein, also für alle Konten und Bussen. Ändern lässt sie sich
  unter *Mandant-Einstellungen → Allgemein → Finanzen* ([Einstellungen](einstellungen.md#finanzen)).
  Sie ist nur eine Beschriftung (z. B. «CHF», «EUR» oder «Fr.»): hocX rechnet nicht um.
- **Konto löschen** geht nur, solange es keine Buchungen und keine Bussen hat. So geht keine
  Finanzhistorie verloren. Ein Konto mit Buchungen benennst du stattdessen um.

## Einnahmen und Ausgaben erfassen {#buchungen}

1. Konto links auswählen und **Buchung hinzufügen** klicken.
2. Oben **Einnahme** oder **Ausgabe** wählen, Betrag (immer positiv eingeben), Beschreibung und
   Datum eintragen. **Heute** setzt das heutige Datum.
3. **Hinzufügen** – die Buchung erscheint in der Liste, der Saldo wird neu berechnet.

Ändern und löschen geht über den Stift bzw. den Papierkorb in der Zeile – ausser bei
[gesperrten Buchungen](#buchungen-korrigieren).

## Laufender und provisorischer Saldo {#provisorischer-saldo}

- **Saldo**: Summe aller Buchungen des Kontos. In der Liste zeigt jede Zeile den Saldo nach
  dieser Buchung (immer über die ganze Kontogeschichte, auch wenn du nach Jahr filterst).
- **Provisorisch**: Summe der noch **offenen** Bussen (Präsenz- und Pendenzen-Bussen), die auf
  dieses Konto gebucht werden, sobald sie einkassiert sind. Dieser Betrag ist noch nicht in der
  Kasse und deshalb nicht im Saldo enthalten.

## Jahressicht und Kassenbericht {#jahresabschluss}

Über die Jahresauswahl über der Buchungsliste zeigst du nur die Buchungen eines Jahres. Darüber
stehen Anfangssaldo, Einnahmen, Ausgaben und Endsaldo des Jahres – das ist die Grundlage für die
Jahresrechnung. **Exportieren** öffnet das Document Studio mit der Vorlage für Finanzen
(Kassenbericht als PDF, CSV oder Excel) für dieses Konto und Jahr.

## Warum eine Buchung gesperrt ist {#buchungen-korrigieren}

Ein Schloss in der Zeile bedeutet: diese Buchung lässt sich nicht direkt ändern oder löschen.
Fahre mit der Maus darüber (oder tippe darauf), um den Grund zu sehen:

- **Gehört zu einer Busse** bzw. **Pendenzen-Busse**: Die Buchung ist beim Einkassieren
  entstanden. Willst du sie rückgängig machen, öffne unter *Bussen* die Busse wieder
  («Wiedereröffnen»). Dabei verschwindet auch die Buchung, Busse und Kasse bleiben stimmig.
- **Gehört zu einem abgeschlossenen Protokoll**: Abgeschlossene Protokolle sind eingefroren.
  Korrigiere einen Fehler mit einer neuen Gegenbuchung (z. B. Ausgabe mit gleichem Betrag und
  der Beschreibung «Korrektur …»).

## Bussen einkassieren, löschen, wiedereröffnen {#bussen-einkassieren}

Eine Busse durchläuft diese Stationen:

1. **Offen** – erfasst im Protokoll (Präsenz) oder automatisch bei einer verspäteten Pendenz.
   Offene Präsenz-Bussen werden ins nächste Protokoll mitgeführt, bis sie erledigt sind.
2. **Kassiert** – mit **Einkassieren** entsteht eine Buchung auf dem Bussenkonto. Datum ist der
   heutige Tag nach Schweizer Zeit.
3. **Wiedereröffnet** – solange das Protokoll, in dem kassiert wurde, offen ist, lässt sich das
   Einkassieren zurücknehmen; die Buchung wird dabei entfernt.
4. **Gelöscht** – im offenen Ursprungsprotokoll verschwindet eine Busse ganz. Später braucht das
   Löschen eine **Begründung**; die Busse bleibt dann durchgestrichen mit Begründung sichtbar
   und lässt sich wiederherstellen.

## Bussentarif {#bussentarif}

Unter *Bussen → Einstellungen* legst du fest, auf welches Konto Bussen gebucht werden und wie
hoch die Beträge für «zu spät» und «unentschuldigt abwesend» sind. Einzelne Personen können
einen eigenen Tarif haben (z. B. 0 für Ehrenmitglieder).

## Pendenzen-Bussen {#pendenzen-bussen}

Mit dem Zusatzmodul «Pendenzen-Bussen» entsteht automatisch eine Busse, wenn eine Pendenz mit
Bussenregel zu spät erledigt wird. Die Regeln und Tarife pflegst du unter *Bussen →
Einstellungen*. Pendenzen-Bussen erscheinen in derselben Bussenliste und zählen ebenfalls zum
provisorischen Saldo.

## Nach einem Abo-Wechsel {#nur-lesen}

Ist das Modul Finanzen nicht mehr im Abo, bleiben alle Konten, Buchungen und Bussen erhalten und
lesbar («nur lesen»). Buchen, Einkassieren und Ändern sind dann gesperrt; hocX zeigt dazu einen
Hinweis oben auf der Seite.
