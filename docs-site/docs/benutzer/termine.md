# Termine

Termine sind die Anlässe deines Vereins: Sitzungen, Trainings, Lager, Elternabende. Sie
erscheinen an mehreren Stellen:

- **Eigenständige Terminverwaltung** unter *Termine*, für den Gesamtüberblick.
- **In Protokollen**, z. B. als Terminliste-Block oder für Elemente/Blöcke, die sich
  "pro Termin" wiederholen (etwa ein Traktandum, das bei jedem Trainingstermin erneut
  auftaucht).
- **In der Abgabebox**, wenn eine Abgabe pro Termin gesammelt wird (siehe
  [Abgabebox](abgabebox.md)), sowie in Fotoalben und Statistiken.

Im Protokoll-Vorbereitungsmodus (Status *geplant*) werden Termine über ein
Terminübersicht-Popup zugeordnet: bestehende Termine im Zyklus suchen und übernehmen,
oder direkt einen neuen Termin anlegen. Ein Filter-Tag am Block sorgt dafür, dass nur
passende Termine vorgeschlagen werden.

!!! info "Berechtigungen"
    Termine ansehen dürfen Konten mit «Sitzungen ansehen» (Standardrollen: alle). Ohne
    «Sitzungen bearbeiten» zeigt hocX die Termine nur zum Lesen an: ohne Anlegen, Löschen,
    CSV-Import und mit gesperrten Feldern. Siehe [Rollen & Berechtigungen](rollen.md).

## Termin anlegen und bearbeiten {#anlegen}

1. Klicke unter **Termine** auf **Neuer Termin** oder im Kalender auf einen freien Tag.
2. Pflicht sind **Startdatum** und **Titel**. Ein **Enddatum** setzt du nur bei mehrtägigen
   Terminen (z. B. Lager); es darf nicht vor dem Startdatum liegen.
3. Optional: genau ein [Tag](#tags), Beschreibung, Standort, Teilnehmerzahl, Personen in den
   [Rollen](#rollen-und-zusatzfelder) und die [Zyklus-Zuordnung](#zyklen).

Ein bestehender Termin öffnet sich per Klick. Änderungen speichert hocX **automatisch**:
Text- und Zahlenfelder kurz nach der letzten Eingabe bzw. sobald du das Feld verlässt,
Auswahlfelder (Datum, Tag, Häkchen, Personen, Zyklen) sofort. Oben im Formular steht, ob
gerade gespeichert wird («Speichert…») oder alles gespeichert ist. Schliesst du den Dialog
oder die Seite, während noch etwas offen ist, sendet hocX es vorher ab.

## Absagen und Löschen {#absagen-und-loeschen}

- **Absagen** (Häkchen «Termin abgesagt» oder Menü der Terminzeile): Der Termin bleibt mit
  allem, was daran hängt, erhalten und wird durchgestrichen angezeigt. Das ist der richtige
  Weg, wenn ein Anlass einfach nicht stattfindet.
- **Löschen** entfernt den Termin endgültig und aus allen Protokollen. Dabei werden auch alle
  **Abgabe-Einreichungen zu diesem Termin samt ihren Dateien unwiderruflich gelöscht**. Die
  Rückfrage nennt die Anzahl der betroffenen Einreichungen und Dateien.

## Tags {#tags}

Ein Tag ordnet einen Termin einer Art zu (z. B. «Sitzung», «Training», «Lager»). Jeder Termin
hat höchstens einen Tag.

- **Farbe und «wichtig»**: In der Seitenleiste markiert der Stern einen Tag als wichtig (er
  steht dann zuoberst); die Farbe lässt sich im Tag-Feld ändern.
- **Filter**: Protokoll-Blöcke und Abgaben wählen Termine über einen Tag-Filter aus. Ein
  Filter trifft jeden Tag, der den Suchtext **enthält** («Training» trifft auch
  «Training U12»).
- **Umbenennen** (im Tag-Feld über das Stift-Symbol): ändert den Tag bei **allen** Terminen
  des Vereins und zieht die Filter der Abgaben mit. hocX fragt vorher nach und nennt die
  Anzahl der betroffenen Termine und Abgaben. Gibt es den neuen Namen schon, werden beide
  Tags **dauerhaft zusammengeführt** – auch darauf weist die Rückfrage hin.

## Zyklen {#zyklen}

Ein Termin gehört standardmässig zu dem [Zyklus](zyklen.md), in den sein Datum fällt (bei
mehreren Zyklus-Definitionen zu je einem pro Definition). Das gilt für neu angelegte, per
CSV importierte und – beim Anlegen eines neuen Zyklus – auch für bereits bestehende Termine.

Im Feld **Zyklen** des Termins kannst du die Zuordnung von Hand ändern, z. B. wenn ein
Anlass im August noch zum alten Vereinsjahr zählen soll. Eine manuelle Zuordnung bleibt auch
bei einer Datumsänderung bestehen; eine unveränderte Standard-Zuordnung wandert mit dem
Datum mit. Die Zuordnung bestimmt, in welchen Zyklusfiltern (Protokolle, Abgaben,
Fotoalben) der Termin erscheint.

## CSV-Import {#csv-import}

Über **CSV Import** lädst du eine ganze Jahresplanung auf einmal:

- Pflichtspalten: **Startdatum** und **Titel**; optional Enddatum, Tag, Beschreibung,
  Teilnehmerzahl. Die Spaltennamen müssen nicht exakt passen, du ordnest sie in der Vorschau
  zu.
- Datumsformate: `2026-04-29`, `29.04.2026`, `29/04/2026`, `2026/04/29`. Trennzeichen Komma,
  Semikolon oder Tab.
- Die Vorschau zeigt jede Zeile mit Fehlern an; importiert wird erst, wenn alle Zeilen gültig
  sind.
- hocX prüft **keine Duplikate**: Wer dieselbe Datei zweimal importiert, hat die Termine
  doppelt.
- Importierte Termine werden ihrem Zyklus nach Datum zugeordnet.

## Ansicht und Kalender {#ansicht}

- Die Liste zeigt standardmässig nur Termine des **aktuellen Zyklus**. Im Menü **Ansicht**
  schaltest du frühere und spätere Zyklen dazu oder wählst einen einzelnen Zyklus.
- Links filtern die Tags, oben Suche und «Kommend / Alle / Vergangen». Die Linie «Heute»
  trennt vergangene und kommende Termine.
- Geladen werden zuerst 100 Termine; weitere lädt die Liste beim Scrollen nach. Suche und
  Filter wirken nur auf geladene Termine – ist noch nicht alles geladen, weist ein Hinweis
  darauf hin und **Alle Termine laden** holt den Rest.
- **Kalender** zeigt Monat oder Jahr. Mit der Tastatur wanderst du mit den Pfeiltasten von
  Tag zu Tag.
- Termine lassen sich im eigenen Kalender abonnieren, siehe
  [Verknüpfungen (Kalender)](verknuepfungen.md).

## Rollen und Zusatzfelder {#rollen-und-zusatzfelder}

Im Reiter **Teilnehmer & Status** ordnest du Personen den Rollen Organisatoren, Leitungsteam
und Teilnehmer zu, dazu drei frei verwendbare Personenfelder («Spezial 1–3»). Im Reiter
**Weitere Felder** gibt es den Standort und drei freie Textfelder («Spezial Text 1–3»).
Wofür die Spezialfelder stehen, legt ihr selbst fest: Unter **Mandant-Einstellungen**
lassen sie sich umbenennen (z. B. «Küche», «Material») oder ausblenden.

## Mobil {#mobil}

Auf dem Smartphone zeigt hocX eine vereinfachte Terminliste mit Tag-Filter. Ein Tipp öffnet
die Details; mit Schreibrecht kannst du dort bearbeiten, absagen oder löschen und über den
runden Plus-Knopf neue Termine anlegen.
