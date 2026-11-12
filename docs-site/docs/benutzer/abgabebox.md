# Abgabebox

Mit der Abgabebox sammelt dein Verein Dateien von Personen, die kein hocX-Konto haben: Fotos
vom Badetag, Lagerberichte, unterschriebene Formulare oder Belege. Die Einreichenden öffnen
einen Link, wählen aus, wofür sie etwas abgeben, und laden ihre Dateien hoch – ohne Anmeldung.

Eingerichtet und ausgewertet wird alles im Bereich **Abgaben** in der Navigation. Eine
**Abgabe** ist dabei ein Auftrag, zum Beispiel «Lagerberichte 2026». Jede Abgabe hat ein oder
mehrere **Abgabefelder**: das, wofür einzeln abgegeben wird – ein Termin, ein Listeneintrag
oder bei einer Einzelabgabe die Abgabe selbst. In der öffentlichen Abgabebox heisst ein
Abgabefeld für die Einreichenden «Dokument» («Welches Dokument reichst du ein?»).

!!! info "Berechtigungen"
    Abgaben ansehen dürfen Konten mit «Abgaben ansehen» (Standardrollen: alle). Abgaben und
    Links anlegen, ändern und löschen braucht «Abgaben verwalten» (Admin, Schreiber). Siehe
    [Rollen & Berechtigungen](rollen.md).

## Erste Abgabe einrichten {#einrichten}

1. Öffne **Abgaben** und klicke auf **+ Abgabe**.
2. **Titel**: Gib der Abgabe einen Namen, z. B. «Badetag-Fotos». Aus dem Titel entsteht beim
   ersten Speichern auch der letzte Teil der Adresse, die oben rechts unter «Öffentlicher Link»
   angezeigt wird.
3. **Verknüpfung (Quelle)**: Wähle, wofür abgegeben wird – *Termine*, *Liste* oder
   *Einzelabgabe*. Was das bedeutet, steht unter [Quelle](#quelle). Schneller geht es mit einer
   der Vorlagen unter «Schnellstart mit Vorlage» (z. B. «Berichte pro Termin»); sie füllen
   Quelle, Zeitraum und Dateiregeln vor, du kannst danach alles anpassen.
4. **Zeitraum**: Lege bei Terminen das [Zeitfenster](#zeitfenster) fest, bei Listen und
   Einzelabgaben den [Stichtag](#stichtag). Beides darfst du leer lassen, dann bleibt die
   Abgabe offen, bis du sie von Hand schliesst.
5. Optional: eine [verantwortliche Person](#verantwortliche) und unter **Erweitert** die
   **Beschreibung** (erscheint für die Einreichenden über dem Upload-Feld),
   [Dateitypen und Grössen](#dateien) und [automatisches Schliessen](#automatisch-schliessen).
   Die Zeile «Erweitert» zeigt die aktuellen Dateiregeln auch im zugeklappten Zustand.
6. **Erreichbar über**: Hake rechts mindestens einen [Link](#links) an. Der Standard-Link ist
   bei neuen Abgaben schon ausgewählt. Ohne Link ist die Abgabe nicht erreichbar.
7. Rechts unter «So verhält sich die Abgabe» fasst hocX in einem Satz zusammen, was du
   eingestellt hast. Lies ihn kurz durch und klicke auf **Abgabe erstellen**.
8. **Link teilen**: Nach dem Erstellen zeigt hocX den fertigen Link der Abgabe zum Kopieren an,
   dazu den Knopf «Abgabebox öffnen». Später findest du ihn jederzeit in der Detailansicht der
   Abgabe (Klick auf die Zeile). Schick ihn den Einreichenden, z. B. per Chat oder Elternbrief.

Solange etwas Wichtiges fehlt (Titel, Tag oder Liste), steht neben dem gesperrten Knopf, was
noch offen ist. Die kleinen **?** neben den Feldern erklären die Einstellung kurz und führen
direkt zum passenden Abschnitt dieser Anleitung.

!!! tip "Erst testen, dann verschicken"
    Öffne den Link selbst in einem privaten Browserfenster. Du siehst dann genau, welche
    Abgaben und Abgabefelder gerade offen sind.

## Wofür wird abgegeben? {#quelle}

Unter **Verknüpfung** wählst du die Quelle der Abgabefelder:

| Quelle | Abgabefelder | Zeitraum |
|---|---|---|
| **Termine** | Ein Abgabefeld je Termin mit dem gewählten **Tag**, z. B. alle Termine mit dem Tag «Badetag». | [Zeitfenster](#zeitfenster) je Termin |
| **Liste** | Ein Abgabefeld je Eintrag der gewählten [Liste](listen.md), z. B. je Lagergruppe. | ein gemeinsamer [Stichtag](#stichtag) |
| **Einzelabgabe** | Genau ein Abgabefeld, das wie die Abgabe heisst – unabhängig von Terminen und Listen. | optionaler [Stichtag](#stichtag) |

Die Abgabefelder folgen der Quelle laufend: Bekommt ein neuer Termin den Tag oder kommt ein
Listeneintrag dazu, erscheint automatisch ein neues Abgabefeld. Wird ein Termin gelöscht oder
verliert er den Tag, fällt sein Abgabefeld weg.

Mit **Sortierung** legst du fest, in welcher Reihenfolge die Abgabefelder in der Übersicht und
in der öffentlichen Abgabebox stehen: nach Datum, alphabetisch oder nach Nähe zu heute.

!!! note "Namen in Listen-Abgaben"
    Ist die erste Spalte der Liste eine Person, zeigt die öffentliche Abgabebox nur deren
    Initialen (z. B. «M.S.»), nie den vollen Namen.

## Zeitfenster bei Termin-Abgaben {#zeitfenster}

Bei Termin-Abgaben hat jedes Abgabefeld sein eigenes Zeitfenster, berechnet aus dem Datum des
Termins:

- **Tage vor dem Termin**: ab wann das Abgabefeld offen ist.
- **Tage nach dem Termin**: bis wann es offen bleibt. Gezählt wird ab dem **letzten Tag** des
  Termins.

**Beispiel:** Der Badetag ist am 14.03. Du stellst *3 Tage vor dem Termin* und *7 Tage nach
dem Termin* ein. Das Abgabefeld ist dann vom **11.03. bis und mit 21.03.** offen.

**Mehrtägiger Termin:** Das Lager dauert vom 14.03. bis 18.03. Mit denselben Werten öffnet das
Abgabefeld am **11.03.** (3 Tage vor dem ersten Tag) und bleibt bis und mit **25.03.** offen
(7 Tage nach dem letzten Tag).

**Leere Felder** bedeuten «ohne Begrenzung auf dieser Seite»:

| Tage davor | Tage danach | Verhalten |
|---|---|---|
| 3 | 7 | offen vom 11.03. bis 21.03. |
| 3 | leer | öffnet am 11.03. und bleibt offen, bis du es schliesst |
| leer | 7 | sofort offen, schliesst am 21.03. |
| leer | leer | sofort offen, bis du es von Hand schliesst |

Vor Beginn des Zeitfensters sehen die Einreichenden das Abgabefeld noch nicht. Nach dem Ende
verschwindet es aus der Abgabebox, ausser du hast [Nach dem Ende offen halten](#offen-halten)
eingeschaltet.

## Stichtag bei Listen- und Einzelabgaben {#stichtag}

Listen- und Einzelabgaben haben einen gemeinsamen **Stichtag** für alle Abgabefelder. Bis und
mit diesem Tag kann abgegeben werden, danach ist die Abgabe in der Abgabebox nicht mehr
sichtbar.

Lässt du den Stichtag leer, bleibt die Abgabe offen, bis du die Abgabefelder von Hand
[schliesst](#schliessen).

## Nur Termine bestimmter Zyklen {#zyklus}

Bei Termin-Abgaben kannst du unter **Zyklus** die Termine auf bestimmte Zyklen beschränken,
z. B. nur auf den *aktuellen Zyklus* oder zusätzlich den *vorherigen Zyklus (−1)*. Mehrere
Zyklen lassen sich kombinieren.

- Der aktuelle Zyklus richtet sich nach dem heutigen Datum und wechselt automatisch. Eine
  Abgabe «Badetag-Fotos» mit *aktuellem Zyklus* zeigt nach dem Zykluswechsel also von selbst
  die Badetage des neuen Jahres.
- *Alle Zyklen (kein Filter)* berücksichtigt jeden Termin mit dem Tag, egal wie alt.

Wie Zyklen funktionieren, steht unter [Zyklen & Vorlagen](vorlagen.md).

## Dateitypen, Anzahl und Grösse {#dateien}

- **Erlaubte Dateitypen**: Wähle einzelne Typen oder ganze Gruppen (PDF, Office-Dateien,
  Bilddateien, Apple-Dateien). Ohne Auswahl sind alle angebotenen Dateitypen erlaubt. hocX
  prüft zusätzlich, ob der Inhalt einer Datei wirklich zur Endung passt.
- **Max. Dateien**: wie viele Dateien ein Abgabefeld **insgesamt** aufnehmen kann (Standard: 5).
  Gezählt werden alle Dateien aller Einreichungen dieses Abgabefelds, auch Dateien, die
  jemand in der App unter *Dateien* oder *Fotos* mit diesem Abgabefeld verknüpft hat (siehe
  [Ablage](#ablage)). Leer = unbegrenzt.
- **Max. Grösse (MB)**: Höchstgrösse je Datei, zwischen 1 und 100 MB (Standard: 20 MB).

Die Einreichenden sehen in der Abgabebox, wie viele Dateien schon hochgeladen sind. Wäre die
Höchstzahl überschritten, lehnt die Abgabebox den Upload mit einem Hinweis ab, wie viele Dateien
noch möglich sind.

!!! note "Gleiche Datei zweimal"
    Reicht jemand exakt dieselbe Datei für dasselbe Abgabefeld nochmals ein, bestätigt die
    Abgabebox den Upload wie gewohnt, speichert die Datei aber nur einmal. Bei sehr ähnlichen
    Bildern erhalten die Einreichenden einen Hinweis.

## Automatisch schliessen {#automatisch-schliessen}

Unter **Automatisch schliessen** legst du fest, ob ein Abgabefeld nach einer Einreichung von
selbst schliesst:

- **Nie** (Standard): Das Abgabefeld bleibt offen, bis das Zeitfenster bzw. der Stichtag
  vorbei ist oder du es von Hand schliesst. Weitere Dateien kommen einfach dazu.
- **Nach der ersten Abgabe**: Sobald jemand einmal etwas eingereicht hat, schliesst das
  Abgabefeld. Praktisch, wenn je Termin oder Listeneintrag genau eine Einreichung erwartet wird.
- **Sobald Höchstzahl erreicht**: Das Abgabefeld schliesst, wenn die
  [Höchstzahl an Dateien](#dateien) erreicht ist. Dafür muss *Max. Dateien* ausgefüllt sein.

Ein automatisch geschlossenes Abgabefeld kannst du jederzeit
[wieder öffnen](#schliessen).

## Nach dem Ende offen halten {#offen-halten}

Hat die Abgabe ein Ende (Tage nach dem Termin oder einen Stichtag), erscheint im Formular ein
Häkchen, um Abgabefelder **nach dem Ende offen zu halten**. Ist es gesetzt,

- schliesst ein Abgabefeld am Ende des Zeitfensters bzw. am Stichtag **nicht**, sondern erst
  nach den Regeln unter [Automatisch schliessen](#automatisch-schliessen) oder wenn du es von
  Hand schliesst;
- bleibt die [Pendenz](#verantwortliche) trotzdem am Ende fällig und wird danach überfällig.
  So kann jemand verspätet noch abgeben, die Verspätung bleibt aber sichtbar.

## Verantwortliche Person {#verantwortliche}

Bei Termin- und Listen-Abgaben kannst du unter **Verantwortliche Person** festlegen, wer für
die Abgabe zuständig ist:

- **Termine**: ein Personenfeld des Termins (*Spezial 1* bis *Spezial 3*, bzw. die Namen, die
  dein Verein diesen Feldern in den Mandant-Einstellungen gegeben hat).
- **Liste**: eine Listenspalte, die Personen enthält.

Steht dort mehr als eine Person, sind sie gemeinsam verantwortlich. Einzelabgaben haben keine
verantwortliche Person.

Was dann passiert:

1. **Pendenz je Abgabefeld**: Für jedes Abgabefeld mit verantwortlicher Person entsteht eine
   Pendenz unter [Todos](todos.md), z. B. «Badetag-Fotos: Badetag Mai». Fällig ist sie am Ende
   des Zeitfensters bzw. am Stichtag, und sie enthält den direkten Link auf dieses
   Abgabefeld. Titel, Personen, Fälligkeit und Link folgen der Abgabe, wenn du sie änderst.
   Voraussetzung: Die Abgabe ist über mindestens einen [Link](#links) erreichbar.
2. **E-Mails**: Die Personen bekommen eine Mail über die neue Pendenz und, sobald die Pendenz
   durch eine Einreichung erledigt ist, die Mail **«Abgabe eingegangen»**. Beide kommen nur,
   wenn die Person ein Konto mit E-Mail-Adresse hat und die Mails in ihrem Benutzerprofil unter
   **Benachrichtigungen** eingeschaltet sind («Neue Aufgaben», «Abgabe eingegangen»). Auch die
   Erinnerungen vor und nach der Fälligkeit gelten für diese Pendenzen.
3. **Erledigt**: Die Pendenz wird mit der **ersten sauber geprüften Datei** automatisch
   erledigt. Dateien, die noch in der [Virenprüfung](#virenscan) sind, zählen noch nicht;
   die Pendenz wird erledigt, sobald die Prüfung sie freigibt. Als Erledigt-Zeitpunkt gilt die
   Einreichung, nicht das Ende der Prüfung.
4. **Bussen**: Habt ihr unter *Pendenzen-Bussen* Regeln für zu spät erledigte Pendenzen, gelten
   sie auch hier. Wer nach der Fälligkeit abgibt, bekommt die Busse wie bei jeder anderen
   Pendenz (siehe [Bussen](finanzen.md#bussen)).
5. **Von Hand geschlossen**: Schliesst du ein Abgabefeld, ohne dass eine geprüfte Datei
   vorliegt, wird die offene Pendenz **abgebrochen** – ohne Busse. Öffnest du das Abgabefeld
   wieder, ist auch die Pendenz wieder offen.

Fällt ein Abgabefeld weg (Termin gelöscht, Tag oder Zyklus gewechselt, verantwortliche Person
entfernt), verschwindet seine offene Pendenz. Hat jemand in der Pendenz schon Notizen oder
Dateien erfasst, wird sie stattdessen abgebrochen. Erledigte Pendenzen bleiben stehen.

## Upload-Links {#links}

Die öffentliche Abgabebox ist nur über einen Link erreichbar. Die Adresse enthält einen
zufälligen Schlüssel: **Wer den Link hat, kann hochladen** – für alle Abgaben, die über diesen
Link erreichbar sind.

Links verwaltest du in der Abgaben-Übersicht über den Knopf **Links** oben rechts (die Zahl
dahinter zeigt, wie viele es gibt) oder im Abgabe-Formular über **Abgabe-Links verwalten**.
Dort kannst du:

- **mehrere Links** anlegen, jeweils mit einem Namen, den nur ihr seht, z. B. «Eltern» und
  «Leiterteam». So kannst du verschiedenen Gruppen verschiedene Abgaben zeigen;
- einen Link **umbenennen** und die Adresse kopieren;
- einen Link **als Standard festlegen**. Der Standard-Link ist bei neuen Abgaben vorausgewählt.
  Jeder Verein startet mit einem Standard-Link;
- mit **Neuen Schlüssel erzeugen** eine neue Adresse erzeugen. Die **alte Adresse wird sofort
  ungültig**. Das ist der Weg, wenn ein Link in falsche Hände geraten ist. Danach den neuen
  Link wieder verteilen;
- einen Link **löschen**. Auch dann funktioniert die Adresse nicht mehr.

Welche Abgabe über welche Links erreichbar ist, legst du in der Abgabe selbst unter
**Erreichbar über** fest. Pendenzen verweisen immer auf einen gültigen Link: Erzeugst du einen
neuen Schlüssel, passt hocX die Links in den Pendenzen an.

!!! warning "Link vertraulich behandeln"
    Teile den Link nur mit den Personen, die etwas abgeben sollen. Ein Link in einem
    öffentlichen Beitrag oder einer offenen Gruppe erlaubt allen, Dateien hochzuladen.

## Fortschritt und Status {#fortschritt}

Die Übersicht unter **Abgaben** zeigt je Abgabe Titel, Quelle und Zeitraum sowie einen
**Fortschrittsbalken**, z. B. «4 von 6». Gezählt wird jedes Abgabefeld genau einmal:

- **abgegeben**: mindestens eine geprüfte Datei,
- **in Prüfung (Quarantäne)**: Dateien warten noch auf die Virenprüfung,
- **geschlossen**: von Hand geschlossen, ohne Datei,
- **infiziert (Schadware)**: nur infizierte Dateien – zählt nicht als abgegeben,
- der Rest ist noch **offen**.

Ein Klick auf eine Abgabe öffnet die Abgabefelder mit ihrem Status:

| Status | Bedeutung |
|---|---|
| **Abgegeben** | Es liegen Dateien vor, das Abgabefeld nimmt weiterhin Dateien an. |
| **In Quarantäne** | Mindestens eine Datei wartet auf die Virenprüfung. |
| **Prüfung fehlgeschlagen** | Eine Datei konnte nicht geprüft werden. |
| **Geschlossen** | Von Hand oder automatisch geschlossen. |
| **Offen** | Das Zeitfenster läuft, es wurde noch nichts eingereicht. |
| **Ausstehend** | Das Zeitfenster hat noch nicht begonnen. |
| **Nicht abgegeben** | Das Zeitfenster bzw. der Stichtag ist vorbei, ohne Einreichung. |

Bei Abgaben mit verantwortlicher Person steht unter jedem Abgabefeld, wer verantwortlich ist.

## Abgabefeld schliessen und wieder öffnen {#schliessen}

Klicke in einer Abgabe auf ein Abgabefeld. Im Fenster findest du unter den Dateien den Knopf
**Abgabefeld schliessen**. Ein geschlossenes Abgabefeld verschwindet sofort aus der öffentlichen
Abgabebox, auch wenn sein Zeitfenster noch läuft. Bereits eingereichte Dateien bleiben
erhalten.

Mit **Wieder aufschalten** öffnest du ein geschlossenes Abgabefeld wieder – egal ob du es von
Hand geschlossen hast oder ob es [automatisch](#automatisch-schliessen) geschlossen wurde. Die
bisherigen Dateien bleiben, neue kommen dazu. Läuft das Zeitfenster bzw. der Stichtag nicht
mehr, bleibt das Abgabefeld in der Abgabebox trotzdem unsichtbar, ausser
[Nach dem Ende offen halten](#offen-halten) ist eingeschaltet.

Wie sich Schliessen und Öffnen auf die Pendenz auswirkt, steht unter
[Verantwortliche Person](#verantwortliche).

## Virenprüfung {#virenscan}

Jede hochgeladene Datei wird auf Schadsoftware geprüft, bevor sie freigegeben wird. Oben rechts
in der Abgaben-Übersicht siehst du, ob die Virenprüfung gerade aktiv ist.

- **Infizierte Datei beim Hochladen**: Die Abgabebox lehnt den Upload ab, die Datei wird nicht
  gespeichert.
- **Prüfung gerade nicht möglich**: Die Datei wird angenommen, bleibt aber in **Quarantäne**.
  Solange sie geprüft wird, ist sie **gesperrt**: Du siehst ihren Namen, kannst sie aber weder
  öffnen noch herunterladen.
- **Erneute Prüfung**: Dateien in Quarantäne prüft hocX **automatisch** nochmals, bis die
  Prüfung gelingt. Du musst nichts tun. Ist die Datei sauber, wird sie freigegeben (und eine
  zugehörige Pendenz erledigt). Erweist sie sich als infiziert, bleibt sie dauerhaft
  **gesperrt** und ist als «Schadware» markiert.

Im Fenster eines Abgabefelds zeigt das **Log**, was mit jeder Einreichung passiert ist, z. B.
«Datei empfangen», «Scan: Sauber» oder «Rescan: Schadware».

## Dateien ansehen und herunterladen {#herunterladen}

- **Einzelne Dateien**: Klicke in der Abgabe auf ein Abgabefeld. Geprüfte Dateien haben ein
  Häkchen und lassen sich mit einem Klick öffnen oder über das Download-Symbol herunterladen.
  Mit dem Löschen-Symbol entfernst du eine Datei endgültig – sie verschwindet dann auch aus
  Fotos und Alben.
- **Alle herunterladen**: Unten in der Abgabe lädt **Alle Dateien (.zip)** alle Dateien der
  Abgabe als ZIP-Datei herunter. Bei mehreren Abgabefeldern gibt es **einen Ordner je
  Abgabefeld** (z. B. je Termin). Enthalten sind nur **geprüfte** Dateien; Dateien in
  Quarantäne oder mit Schadware fehlen. Auch Dateien bereits geschlossener Abgabefelder und
  Dateien, die in der App mit der Abgabe verknüpft wurden, sind dabei.

## Wo die Dateien landen {#ablage}

Eingereichte Dateien bleiben nicht nur in der Abgabe:

- **Bilder** erscheinen zusätzlich unter **Fotos**, alle anderen Dateien unter **Dateien**
  (siehe [Dateien & Dokumente](dateien.md)). Dort sind sie mit ihrer Abgabe verknüpft, und ein
  Klick auf die Verknüpfung führt zurück zur Abgabe.
- Umgekehrt kannst du beim Hochladen unter **Fotos** oder **Dateien** als **Bezug** ein
  Abgabe-Element wählen, also ein Abgabefeld einer Abgabe. Die Datei zählt dann wie eine
  Einreichung: Sie erscheint im Abgabefeld, zählt zur Höchstzahl an Dateien und erledigt eine
  offene Pendenz, sobald sie geprüft ist. Dabei gelten die Regeln der Abgabe (Dateitypen,
  Grösse, Anzahl). Anders als die öffentliche Abgabebox geht das auch bei geschlossenen
  Abgabefeldern.

## Grenzen und häufige Fragen {#grenzen}

**Wie viel Platz haben wir?**
Die Einreichungen zählen zum Speicherkontingent deines Vereins. Ist es erreicht, lehnt die
Abgabebox weitere Uploads mit einem Hinweis ab. Den Stand siehst du in den Mandant-Einstellungen im Tab [*Abo & Nutzung*](einstellungen.md#abo).

**Wie viele Dateien gehen auf einmal?**
In einem Upload-Vorgang sind höchstens 50 Dateien möglich. Wer mehr hat, lädt in mehreren
Durchgängen hoch – sofern die [Höchstzahl je Abgabefeld](#dateien) das zulässt.

**Was ist der Sicherheitscheck?**
Vor dem Hochladen prüft ein Captcha (Friendly Captcha) ohne Cookies und ohne Tracking, dass ein
Mensch hochlädt. Der Check läuft meist von selbst; er gilt eine Weile, damit nicht jede Datei
einzeln geprüft werden muss. Meldet die Abgabebox «Sicherheitscheck abgelaufen», kurz warten und
nochmals versuchen.

**Kann jemand eine Einreichung zurückziehen?**
Nein. Einreichende können hochgeladene Dateien weder sehen noch löschen. Wurde etwas Falsches
eingereicht, löschst du die Datei in der Abgabe (siehe [Herunterladen](#herunterladen)).

**Sehen Einreichende, was andere hochgeladen haben?**
Nein. Sie sehen nur, wie viele Dateien für ein Abgabefeld schon eingegangen sind.

**Werden GPS-Daten von Fotos übernommen?**
Nur wenn die einreichende Person «GPS-Daten des Bildes mitsenden» angehakt lässt. Ohne Häkchen
werden die Standortdaten vor dem Speichern entfernt.

**Werden Einreichungen irgendwann gelöscht?**
Nur wenn ihr das wollt: In den Mandant-Einstellungen gibt es unter den [Aufbewahrungsfristen](einstellungen.md#aufbewahrung) die
Regel «Einreichungen der Abgabebox nach Abgabeschluss löschen». Sie ist ausgeschaltet, bis ihr
sie einschaltet. Löschst du eine ganze Abgabe, werden alle ihre eingereichten Dateien
mitgelöscht.

**Warum erscheint eine Abgabe nicht in der Abgabebox?**
Prüfe: Ist mindestens ein Link unter *Erreichbar über* angehakt? Hat das Zeitfenster schon
begonnen bzw. ist der Stichtag noch nicht vorbei? Ist das Abgabefeld geschlossen? Gibt es bei
einer Termin-Abgabe Termine mit dem Tag im gewählten Zyklus?

**Ist die Abgabebox vom Rest von hocX getrennt?**
Ja. Die öffentliche Abgabebox läuft als eigene Anwendung mit stark eingeschränkten Rechten. Sie
sieht nur, was für die Einreichung nötig ist, und hat keinen Zugriff auf eure übrigen Daten.
