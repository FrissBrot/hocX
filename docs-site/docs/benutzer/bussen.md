# Pendenzen-Bussen

Mit dem Zusatzmodul **Pendenzen-Bussen** büsst hocX automatisch, wenn eine Pendenz zu spät
erledigt wird. Welche Pendenzen wie viel kosten, legst du mit **Regeln** und **Tarifen** fest.
Die Seite **Pendenzen-Bussen** hat dafür drei Tabs: *Bussen*, *Regeln* und *Tarife*.

!!! info "Berechtigungen"
    Regeln, Tarife, Einkassieren, Erlassen und das Festlegen einer Busse von Hand brauchen
    «Finanzen verwalten» (Admin, Kassier). Die Bussen **aller** Personen sieht nur, wer
    «Personenbezogene Daten aller» hat – siehe [Wer sieht was?](#wer-sieht-was) und
    [Rollen & Berechtigungen](rollen.md).

## Überblick {#ueberblick}

hocX kennt zwei Arten von Bussen:

| Art | Entsteht durch | Beschrieben in |
|---|---|---|
| **Anwesenheitsbussen** | «zu spät» oder «unentschuldigt abwesend» im Protokoll | [Finanzen & Bussen](finanzen.md#bussen-einkassieren) |
| **Pendenzen-Bussen** | eine Pendenz, die nach ihrer Fälligkeit erledigt wird | diese Seite |

Beide landen beim Einkassieren als Buchung in der Kasse und zählen, solange sie offen sind, zum
[provisorischen Saldo](finanzen.md#provisorischer-saldo).

## Laufend, eingefroren, erledigt {#laufend-eingefroren}

Eine Pendenzen-Busse durchläuft diese Zustände:

1. **Läuft** – die Pendenz ist offen und überfällig. Der Betrag wächst noch.
2. **Offen (eingefroren)** – die Pendenz ist erledigt, der Betrag steht fest. In der App heisst
   das «Eingefroren». Die Busse wartet jetzt aufs Einkassieren.
3. **Einkassiert** – der Betrag ist als Buchung in der Kasse.
4. **Erlassen** – die Busse wurde mit Begründung erlassen und zählt nicht mehr.

Passen mehrere Regeln auf eine Pendenz, steht statt «Läuft» ein **Konflikt** in der Liste
(siehe [Konflikt](#konflikt)). Über die Filter oberhalb der Liste (Laufend, Konflikte, Offen,
Einkassiert, Erlassen, Alle) zeigst du jeden Zustand einzeln.

## Wann eine Busse eingefroren wird {#einfrieren}

- **Solange eine Pendenz offen und überfällig ist, «läuft» die Busse.** Sie wird jeden Tag neu
  gerechnet (Schweizer Datum) und wächst mit jedem vollen [Intervall](#regeln).
- **Wird die Pendenz erledigt, wird die Busse je verantwortliche Person eingefroren.** Stichtag
  ist das Erledigungsdatum. «Abgebrochen» ist keine Verspätung: eine abgebrochene Pendenz kostet
  nichts.
- **Eingefroren bleibt eingefroren.** Pendenz wieder öffnen, Fälligkeit verschieben,
  Verantwortliche oder Tags ändern und sogar die Pendenz löschen ändern eine eingefrorene Busse
  nicht. Sie bleibt in der Bussenliste, bei einer gelöschten Pendenz mit dem gespeicherten
  Titel. Wird die Pendenz erneut erledigt, entsteht nur für Personen eine neue Busse, die noch
  keine haben.
- **Nachträgliches Bearbeiten** einer erledigten Pendenz (z. B. eine Notiz ergänzen) ändert das
  Erledigungsdatum nicht.
- **Abgabe-Pendenzen** aus der [Abgabebox](abgabebox.md) werden automatisch erledigt. Die Busse
  wird beim nächsten Abgleich genau einmal eingefroren, auch wenn dieser erst später läuft.

**Beispiel:** Die Pendenz «Protokoll schreiben» war am 10.03. fällig und wird am 15.03.
erledigt. Bis zum 15.03. läuft die Busse und steigt. Ab dem 15.03. ist sie eingefroren. Wird
die Fälligkeit danach auf den 20.03. verschoben, bleibt die Busse trotzdem bestehen.

## Wer eine Busse wieder loswerden kann {#storno}

**Eingefrorene Busse:** Entfernen oder ändern kann sie nur, wer «Finanzen verwalten» hat:

- durch **Erlassen** mit Begründung (siehe [Einkassieren und erlassen](#einkassieren-erlassen)),
  oder
- durch **Busse von Hand festlegen** an der Pendenz, womit die Busse neu gerechnet wird
  (siehe [Busse von Hand festlegen](#von-hand)).

Beides steht im Audit-Log.

**Laufende Busse:** Die gebüsste Person selbst kann ihre laufende Busse nicht loswerden.
Fälligkeit verschieben, Verantwortliche oder Tags ändern, auf «abgebrochen» setzen oder die
Pendenz löschen wird dann abgelehnt – die App zeigt einen Hinweis. Das gilt nicht, wenn sie
selbst «Finanzen verwalten» hat. Andere Personen mit Schreibrecht für Pendenzen dürfen solche
Änderungen machen (z. B. den Termin verschieben); sie stehen im Audit-Log.

## Regeln {#regeln}

Unter *Regeln* legst du fest, welche Pendenzen gebüsst werden und wie viel. Eine Regel hat:

- **Name** und **Gilt ab**: Die Regel erfasst nur Pendenzen, die ab diesem Datum **fällig**
  sind (massgebend ist die Fälligkeit, nicht das Erstellungsdatum).
- **Regel aktiv**: Eine pausierte Regel erfasst keine Bussen.
- **Für welche Pendenzen?** – die Filter, siehe unten.
- **Wie wird gebüsst?** – Grundbetrag, Zuschlag und [Tarife](#tarife).
- **Konto**: Ohne eigene Angabe gilt das Bussenkonto des Tarifs.
- **Bei mehreren Verantwortlichen**: siehe [Aufteilen](#aufteilen).

Beim Anlegen einer neuen Regel füllt eine **Vorlage** Intervall und Beträge für alle Tarife vor:
«Fixbetrag pro Tag» (jeder Tag Verspätung kostet gleich viel) oder «Grundbetrag + pro Woche»
(Grundbetrag ab dem ersten Tag, dazu ein Zuschlag je volle Woche). Danach lässt sich alles
anpassen. Filter und Konto stehen unter **Erweitert**; ohne Filter gilt die Regel für alle
Pendenzen, ohne Konto das Bussenkonto des Tarifs.

### Filter

Es gibt vier Filterarten: **Tags**, **Aufgabenpakete**, **Verantwortliche** und **Rollen der
Verantwortlichen**. Dabei gilt:

- Jede **gesetzte** Filterart muss passen.
- Innerhalb einer Filterart genügt **ein Treffer** (z. B. einer von mehreren Tags).
- Eine **leere** Filterart schränkt nicht ein. Ist gar nichts gesetzt, gilt die Regel für alle
  Pendenzen.

**Beispiel:** Tags «Protokoll» und «Lager», Rolle «Vorstand». Die Regel passt auf eine Pendenz
mit Tag «Lager», für die jemand aus dem Vorstand verantwortlich ist – nicht aber auf eine
Pendenz mit Tag «Lager», für die nur Leitende ohne Vorstandsrolle verantwortlich sind.

### Betrag

```
Busse = Grundbetrag + floor(Tage zu spät / Intervall) × Intervallbetrag
```

`floor` heisst: es zählen nur **volle** Intervalle. Schon ein Tag Verspätung kostet den
Grundbetrag.

**Rechenbeispiel:** Intervall 2 Tage, Grundbetrag 5.–, Zuschlag 2.– pro Intervall.

| Verspätung | Rechnung | Busse |
|---|---|---|
| 1 Tag | 5.– + 0 × 2.– | **5.–** |
| 2 Tage | 5.– + 1 × 2.– | **7.–** |
| 5 Tage | 5.– + 2 × 2.– | **9.–** |

Die Vorschau im Regel-Formular zeigt dir die Beträge für einige Verspätungen gleich an.

Die **Reihenfolge der Regeln spielt keine Rolle**: hocX nimmt nie einfach die erste passende
Regel. Passen mehrere, entsteht ein [Konflikt](#konflikt).

## Tarife {#tarife}

Unter *Tarife* legst du Gruppen wie «Lernende» oder «Vollverdiener» an und ordnest Personen zu.
Jede Person zahlt nach ihrem eigenen Tarif, sonst nach dem **Standardtarif**.

In jeder Regel steht je Tarif ein eigener Betrag. **Fehlt in einer Regel der Betrag für einen
Tarif, zahlt diese Gruppe für diese Regel nichts.** Die Regelliste warnt dich in diesem Fall.

## Mehrere Verantwortliche: jede Person oder aufteilen {#aufteilen}

Hat eine Pendenz mehrere Verantwortliche, bestimmt die Regel unter «Bei mehreren
Verantwortlichen»:

- **Jede Person zahlt voll**: Alle Verantwortlichen erhalten den vollen Betrag ihres Tarifs.
- **Betrag wird aufgeteilt**: Der Betrag wird durch die Zahl der Verantwortlichen geteilt.

Bei einem [fixen Betrag](#von-hand) geht ein Rappenrest an die erste Person. Beispiel:
10.– aufgeteilt auf drei Personen ergibt **3.34 + 3.33 + 3.33**.

## Konflikt: mehrere Regeln passen {#konflikt}

Passen im Modus «Automatisch nach Regeln» **mehrere** Regeln auf eine Pendenz, entsteht keine
Busse, sondern ein **Konflikt**. hocX zeigt oben in der Bussenliste einen Hinweis, und der
Filter «Konflikte» listet die betroffenen Pendenzen.

Den Konflikt löst jemand mit «Finanzen verwalten» an der Pendenz von Hand auf: Busse-Kasten im
Pendenz-Popup öffnen und eine bestimmte Regel, einen fixen Betrag oder «Keine Busse» wählen
(siehe [Busse von Hand festlegen](#von-hand)).

## Busse von Hand festlegen {#von-hand}

Im Pendenz-Popup steht rechts der Bereich **Busse**. Ändern dürfen ihn nur Personen mit
«Finanzen verwalten»; alle anderen sehen nur, ob und wie viel Busse läuft.

- **Fixbetrag (optional):** Ein eingetippter Betrag geht immer vor – unabhängig von Regeln und
  Verspätung. Bei mehreren Verantwortlichen wählst du **Je Person** (jede Person zahlt den
  Betrag) oder **Aufteilen** (der Betrag wird geteilt). Feld leeren = wieder nach Regel rechnen.
- **Regel-Zeile** darunter, mit einem Menü:

| Auswahl | Bedeutung |
|---|---|
| **Automatisch** | Standard. Die passende Regel bestimmt die Busse; das Menü zeigt, welche passt. |
| **Regel fest zuweisen** | Diese eine Regel gilt – auch wenn ihre Filter nicht passen (im Menü ohne «passt»). |
| **Keine Busse** | Für diese Pendenz fällt nie eine Busse an, auch wenn eine Regel passt. |

Darunter siehst du pro Person mit Tarif, was die Busse heute kostet, und das Total. Passen
mehrere Regeln, zeigt hocX sie mit ihrem Total zur Auswahl ([Konflikt](#konflikt)).

Gespeichert wird mit **Speichern** der Pendenz. Auf der Seite *Bussen* (Konflikt auflösen)
gibt es dafür den Knopf **Übernehmen**.

Ist die Pendenz bereits erledigt, rechnet hocX dabei die **offenen eingefrorenen** Bussen neu.
Die ersetzten Bussen stehen im Audit-Log.

## Einkassieren, wieder öffnen, erlassen {#einkassieren-erlassen}

- **Einkassieren** bucht den Betrag auf das Konto der Regel bzw., wenn die Regel keines hat,
  auf das Bussenkonto. Die Buchung ist mit der Busse verknüpft und gesperrt.
- **Wieder öffnen** nimmt das Einkassieren zurück und löscht diese Buchung wieder.
- **Erlassen** braucht eine **Begründung**. Die Busse bleibt mit Status «Erlassen» sichtbar.
- **Wiederherstellen** macht das Erlassen rückgängig.

## Regel löschen oder deaktivieren {#regel-loeschen}

Bereits eingefrorene Bussen bleiben bestehen, wenn du eine Regel löschst. Eine Regel, die
Pendenzen **von Hand** zugewiesen ist («Bestimmte Regel»), lässt sich aber nicht löschen.
Deaktiviere sie stattdessen («Regel aktiv» ausschalten).

## Wenn das Modul nur noch lesbar ist {#nur-lesen}

Ist Pendenzen-Bussen nicht mehr im Abo, ist das Modul im Nur-Lesen-Zustand:

- Bestehende Bussen bleiben sichtbar.
- Es wird nichts mehr eingefroren, und es entstehen keine neuen Bussen.
- Eine Pendenz, die in dieser Zeit erledigt wird, wird auch später nicht rückwirkend gebüsst,
  wenn das Modul wieder gebucht ist.

## Wer sieht was? {#wer-sieht-was}

Ohne das Recht «Personenbezogene Daten aller» siehst du nur deine **eigenen** Bussen –
laufende und eingefrorene. Mit diesem Recht siehst du die Bussen aller Personen.
