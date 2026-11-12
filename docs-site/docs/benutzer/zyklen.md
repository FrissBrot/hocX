# Zyklen

Ein **Zyklus** ist eine wiederkehrende Vereinsperiode, meist das Vereins- oder Scharjahr.
hocX nutzt Zyklen, um Termine, Protokolle und Abgaben sauber nach Jahren zu trennen:
Protokolle werden pro Zyklus nummeriert, Terminlisten zeigen den aktuellen Zyklus, und
Abgaben können auf Termine bestimmter Zyklen beschränkt werden.

Zyklen verwaltest du unter **Konfiguration → Abläufe → Zyklen**. Dafür braucht es das Recht «Vorlagen
verwalten» (Standardrolle: Admin).

## Stichtag {#stichtag}

Jeder Zyklus hat einen **Stichtag** (Reset-Monat und -Tag). Ein neuer Zyklus beginnt am Tag
danach. Beispiele:

| Stichtag | Ein Zyklus dauert |
|---|---|
| 31. Dezember | 1. Januar – 31. Dezember (Kalenderjahr) |
| 31. Juli | 1. August – 31. Juli (z. B. Scharjahr nach dem Sommerlager) |

Existiert der Tag in einem Monat nicht (z. B. 30. Februar), gilt der letzte Tag des Monats.

**Was beim Anlegen und Ändern passiert:**

- Ein **neuer Zyklus** ordnet sich sofort allen bestehenden Terminen zu – jeder Termin landet
  in dem Zyklus, in den sein Datum fällt.
- Wird der **Stichtag geändert**, wandern alle Termine mit, deren Zuordnung noch dem Standard
  entsprach. Termine, die du von Hand einem anderen Zyklus zugeordnet hast, bleiben, wie sie
  sind.

## Namensmuster {#namensmuster}

Das Namensmuster bestimmt, wie ein einzelner Zyklus heisst. Platzhalter:

- `[cy]` – Startjahr (z. B. 2025)
- `[cy_end]` – Endjahr (z. B. 2026)

Beispiel: `Scharjahr [cy]/[cy_end]` ergibt «Scharjahr 2025/2026». Ohne Muster heisst ein
Zyklus einfach «2025/2026».

## Aktueller Zyklus {#aktueller-zyklus}

Die Terminliste zeigt standardmässig nur Termine des **aktuellen Zyklus** – also des
Zyklus, in den das heutige Datum (Schweizer Zeit) fällt. Ein Termin gehört dazu, wenn er
zeitlich hineinfällt (auch mehrtägig überlappend) oder ausdrücklich diesem Zyklus zugeordnet
ist. Unter **Ansicht** blendest du frühere und spätere Zyklen ein; gibt es mehrere
Zyklus-Definitionen, kannst du dort eine davon wählen.

Wie du einen Termin von Hand einem Zyklus zuordnest, steht unter
[Termine → Zyklen](termine.md#zyklen).

## Zuordnung zu Vorlagen und Abgaben {#verwendung}

- **Vorlagen**: Eine Protokollvorlage kann einen Zyklus verwenden. Daraus ergeben sich die
  Protokollnummer pro Zyklus und die Platzhalter für Titel (siehe
  [Zyklen & Vorlagen](vorlagen.md)). Im Protokoll zeigt das Terminübersicht-Popup
  standardmässig die Termine des Zyklus, in den das Protokolldatum fällt.
- **Abgaben**: Eine Abgabe pro Termin kann auf Termine bestimmter Zyklen eingeschränkt werden
  (z. B. «nur aktueller Zyklus»), siehe [Abgabebox](abgabebox.md).

## Löschen {#loeschen}

Ein Zyklus lässt sich nur löschen, solange ihn keine Vorlage und keine Abgabe mehr verwendet.
Sonst meldet hocX, dass er noch in Gebrauch ist. Die Zuordnungen der Termine zu diesem Zyklus
verschwinden beim Löschen mit; die Termine selbst bleiben erhalten.
