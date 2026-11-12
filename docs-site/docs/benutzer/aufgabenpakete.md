# Aufgabenpakete

Ein **Aufgabenpaket** bündelt wiederkehrende Aufgaben, die in jedem Zyklus wieder anfallen –
zum Beispiel «Sommerlager» mit «Lagerplatz reservieren», «Anmeldung verschicken» und
«Lagerbericht schreiben». Weist du das Paket einem [Zyklus](zyklen.md) zu, entstehen daraus in
jedem Zyklus automatisch echte [Pendenzen](todos.md). Die Verantwortlichen kommen auf Wunsch
direkt aus einer Liste wie der Ämtliliste.

Eingerichtet wird alles unter **Aufgabenpakete** in der Navigation.

!!! info "Berechtigungen"
    Aufgabenpakete ansehen und verwalten braucht «Vorlagen verwalten» (Admin, Schreiber). Die
    erzeugten Pendenzen bearbeitest du wie alle anderen Pendenzen. Siehe
    [Rollen & Berechtigungen](rollen.md).

## Paket anlegen

1. Unter **Aufgabenpakete** auf **Neues Paket** klicken.
2. **Name** (z. B. «Sommerlager») und optional eine **Beschreibung** eintragen.
3. **Aktiv** lassen: Nur aktive Pakete erzeugen und aktualisieren Pendenzen. Mit **Pausieren**
   im Aktionsmenü hältst du ein Paket an, ohne es zu löschen; **Fortsetzen** startet es wieder.
4. Unter **Aufgaben** mit **Aufgabe hinzufügen** die einzelnen Aufgaben erfassen (siehe
   [Wiederholung](#wiederholung), [Fälligkeit](#faelligkeit) und
   [Verantwortliche](#verantwortliche-aus-listen)). Jede Aufgabe kann auch einen Link und Tags
   haben, die in die Pendenz übernommen werden.
5. Das Paket einem [Zyklus zuweisen](#zyklus).

## Zyklus und Zyklusjahr {#zyklus}

Mit **Zyklus zuweisen** legst du fest, in welchem Zyklus das Paket gilt und **ab welchem
Zyklusjahr**:

- **laufender Zyklus**: Die Pendenzen entstehen sofort.
- **nächster Zyklus**: Die Pendenzen entstehen erst beim Zykluswechsel.

Danach wiederholt sich das Paket in jedem Zyklus automatisch. Ein Paket kann mehreren Zyklen
zugewiesen sein.

hocX erzeugt immer nur die Pendenzen des **laufenden** Zyklus. Das passiert beim Zuweisen, beim
Ändern des Pakets, bei Änderungen an den verknüpften Listen und Terminen und einmal täglich.
Beim Zykluswechsel legt der tägliche Lauf die Pendenzen des neuen Zyklus an. Mit **Jetzt
nachführen** im Aktionsmenü stösst du das von Hand an.

Die **Vorschau** zeigt für ein wählbares **Zyklusjahr**, welche Pendenzen entstehen und mit
welchen Verantwortlichen (so, wie sie heute in den Listen stehen). «Vorhanden» heisst, die
Pendenz wurde schon erzeugt, «Neu», dass sie noch entsteht.

## Wiederholung {#wiederholung}

Je Aufgabe bestimmst du, wie oft sie im Zyklus entsteht:

| Wiederholung | Es entsteht eine Pendenz … |
|---|---|
| **Einmal pro Zyklus** | einmal je Zyklus. |
| **Monatlich** | an einem **Tag im Monat**, in jedem Monat des Zyklus. Gibt es den Tag nicht (z. B. 31.), gilt der Monatsletzte. |
| **Wöchentlich** | an einem **Wochentag**, jede Woche des Zyklus. |
| **Pro Termin** | für jeden Termin mit dem gewählten **Termin-Tag** im Zyklus – auch für später erfasste Termine. Abgesagte Termine zählen nicht. |

## Fälligkeit {#faelligkeit}

| Fälligkeit | Bedeutung |
|---|---|
| **Keine** | Die Pendenz hat kein Fälligkeitsdatum. |
| **Festes Datum im Zyklus** | Tag und Monat, z. B. 15. Juni. hocX nimmt das Datum, das in den Zyklus fällt. Nur bei «Einmal pro Zyklus» möglich. |
| **Relativ** | Eine Anzahl Tage **vor** oder **nach** einem Bezugsdatum. |

Das Bezugsdatum bei «Relativ» hängt von der Wiederholung ab:

- **Einmal pro Zyklus**: der Zyklusbeginn,
- **Pro Termin**: das Datum des Termins,
- **Monatlich** und **Wöchentlich**: das jeweilige Wiederholungsdatum.

**Beispiel:** Aufgabe «Lagerbericht schreiben», Wiederholung *Pro Termin* mit Tag «Lager»,
Fälligkeit *Relativ, 14 Tage nach dem Termin*. Für das Lager am 20.07. entsteht eine Pendenz,
die am 03.08. fällig ist.

## Verantwortliche aus Listen {#verantwortliche-aus-listen}

Unter **Verantwortlich** gibt es zwei Arten von Einträgen, die du mischen kannst:

- **+ Aus Liste**: eine Zeile aus einer [Liste](listen.md) (z. B. das Ämtli «Kassier» aus der
  Ämtliliste). Verantwortlich sind die Personen, die dort eingetragen sind. In Frage kommen
  Listen mit einer Text- und einer Personenspalte.
- **+ Person**: eine feste Person, die immer gleich bleibt.

Ändert sich die Liste, passen sich die **offenen** Pendenzen des **laufenden** Zyklus an.
Pendenzen vergangener Zyklen bleiben, wie sie waren. Neu verantwortliche Personen werden
benachrichtigt.

### Was das Paket überschreibt

Änderungen an einer Aufgabe gelten für offene Pendenzen im laufenden Zyklus und alle künftigen.
Unverändert bleiben:

- **erledigte** und **abgebrochene** Pendenzen,
- Felder, die jemand an einer Pendenz **von Hand geändert** hat. Das betrifft Text, Link, Tags,
  Fälligkeit und Verantwortliche. Hast du zum Beispiel bei einer Paket-Pendenz die Fälligkeit
  verschoben, überschreibt das Paket sie danach nicht mehr; die übrigen Felder pflegt es
  weiterhin.

hocX löscht Paket-Pendenzen nie von selbst – auch nicht, wenn ein Termin wegfällt. Gelöscht wird
nur beim [Entfernen](#loeschen).

## Aufgabe, Zyklus oder Paket entfernen {#loeschen}

- **Aufgabe entfernen**: Die Aufgabe verschwindet aus dem Paket. Bereits erzeugte Pendenzen
  bleiben als normale Pendenzen bestehen.
- **Zuweisung zu einem Zyklus entfernen** (✕ am Zyklus) oder **Paket löschen**: hocX fragt,
  was mit den bereits erzeugten Pendenzen passieren soll.

| Auswahl | Wirkung |
|---|---|
| **Alle Aufgaben löschen** | Alle Pendenzen des Pakets (bzw. dieses Zyklus) werden gelöscht – **auch erledigte** und solche aus vergangenen Zyklen, samt ihren Notizen. |
| **Nur Aufgaben ab dem nächsten Zyklus löschen** | Nur Pendenzen künftiger Zyklen werden gelöscht. Die des laufenden und vergangener Zyklen bleiben als normale Pendenzen. |
| **Keine Aufgaben löschen** | Alle Pendenzen bleiben als normale Pendenzen bestehen. |

Behaltene Pendenzen sind danach vom Paket gelöst: Eine spätere Zuweisung überschreibt sie nicht
mehr.

!!! warning "Erledigte Pendenzen gehen verloren"
    «Alle Aufgaben löschen» entfernt auch erledigte Pendenzen mit ihren Notizen endgültig.
    Willst du die Geschichte behalten, wähle «Nur Aufgaben ab dem nächsten Zyklus löschen».
    Bereits eingefrorene [Pendenzen-Bussen](bussen.md#einfrieren) bleiben in jedem Fall
    erhalten.
