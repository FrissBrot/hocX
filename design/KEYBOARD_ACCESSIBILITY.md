# hocX Tastaturbedienung

Verbindlich für **jede** neue oder geänderte interaktive Oberfläche in `frontend/` und
`abgabebox-frontend/`, ergänzt `design/DESIGN.md` (Abschnitt 9). Ziel: jede Funktion ist ohne Maus
bedienbar (WCAG 2.2 AA: 2.1.1, 2.1.2, 2.1.4, 2.4.3, 2.4.7, 2.4.11, 3.2.1, 4.1.2), mit einer
zentralen, konsistenten Tastaturlogik statt verstreuter Einzellösungen. Befunde und Stand:
`KEYBOARD_AUDIT.md`.

Automatisch geprüft: `python3 scripts/check-keyboard-a11y.py` (Claude-Hook, Pre-Commit, CI),
Vitest `components/ui/keyboard-contracts.test.tsx`, `lib/keyboard/*.test.ts*`, Playwright
`e2e/keyboard-navigation.spec.ts`.

## 1. Grundregeln

1. **Native Elemente zuerst.** Etwas, das man anklickt, ist ein `<button type="button">` (Aktion)
   oder ein `<a href>`/`<Link>` (Navigation). Kein `div`/`span`/`tr` mit `onClick` als einziger
   Bedienweg. Ganze Tabellenzeilen dürfen zusätzlich klickbar sein, wenn dieselbe Aktion als Knopf
   oder Link in der Zeile steht.
2. **Aktionen auf `onClick`**, nie nur auf `onPointerDown`/`onMouseDown` - Enter/Leertaste lösen
   bei einem fokussierten Knopf `click` aus, sonst nichts. Soll der Fokus beim Klicken in einem
   Feld bleiben: `onMouseDown={(e) => e.preventDefault()}` **plus** `onClick={aktion}`.
3. **Kein positiver `tabIndex`.** Die Reihenfolge kommt aus dem DOM. `tabIndex={-1}` nur für
   programmatische Ziele (Dialog-Container, Hauptinhalt, inaktive Einträge im roving tabindex).
4. **Sichtbarer Fokus.** Buttons/Links/Tabs/Menüeinträge bekommen ihn global (`:focus-visible`,
   `--focus-ring-color`), Felder über `border-color: var(--accent); box-shadow: var(--focus-ring)`.
   `outline: none` in einer `:focus`-Regel nur mit Ersatz in derselben Regel oder `a11y-ok`
   (z. B. Fokus zeigt der Wrapper per `:focus-within`).
5. **Nichts nur bei Hover.** Was beim Überfahren erscheint, erscheint auch bei `:focus-within`
   (Muster: `.record-list-row:hover .subm-row-actions, .record-list-row:focus-within …`).
6. **Unsichtbares ist kein Tab-Ziel.** Ausgeblendete Panels/Seitenleisten mit `hidden`,
   `display: none` oder `visibility: hidden` (bei Animation: `visibility` mit Verzögerung, siehe
   `.sidebar` in `globals.css`), nicht nur `transform`/`opacity`.
7. **Keine Tastaturfalle.** Aus jedem Bereich kommt man mit Tab/Umschalt+Tab oder Escape heraus;
   nur modale Dialoge halten Tab bewusst fest (und schliessen mit Escape).
8. **Bedienelemente haben einen Namen.** Icon-Buttons `aria-label`, Umschalter `aria-pressed`,
   Aufklapper `aria-expanded` (+ `aria-controls`), Menü-Auslöser `aria-haspopup`.

## 2. Bausteine und ihr Tastaturvertrag

Jeder gemeinsame Baustein in `frontend/components/ui/` hat einen Tastaturvertrag. Neue gemeinsame
Bausteine dokumentieren ihren Vertrag hier und testen ihn in `keyboard-contracts.test.tsx`.

| Baustein | Vertrag |
|---|---|
| `Modal` | Öffnen: Fokus auf `autoFocus`-Feld, sonst auf den Dialog (Titel wird vorgelesen). Tab/Umschalt+Tab bleiben im Dialog (nur sichtbare, aktive Ziele; Popover/Rückfragen aus dem Dialog zählen als innen; auch ein Tab bei verlorenem Fokus landet im Dialog). Escape: `onEscape` bzw. `[data-modal-save]` bzw. schliessen. Schliessen: Fokus zurück auf den Auslöser; gab es ihn nicht mehr (gelöschte Zeile), auf den Hauptinhalt. Benannt über `aria-labelledby` (Titel) und `aria-describedby` (Beschreibung). |
| `useConfirm` | `alertdialog`, Start auf «Abbrechen» bei `tone: "danger"`, sonst auf der Bestätigung. Tab-Falle, Escape = Abbrechen, Fokus zurück auf den Auslöser (oder dessen Menü-Auslöser). |
| `Popover` (+ `Menu`, `MenuItem`) | Öffnen legt den Fokus ins Panel: bei `role="menu"` (Standard) auf den ersten Eintrag, sonst auf das erste Feld. Menü: Pfeil hoch/runter (zyklisch), Pos1/Ende, Buchstabe springt; Tab verlässt das Menü hinter dem Auslöser und schliesst es. Dialog-Panels (`role="dialog"`, `"presentation"`): Tab läuft durch, am Ende hinter dem Auslöser weiter, Umschalt+Tab am Anfang zurück auf den Auslöser. Escape/Auswahl: Fokus zurück auf den Auslöser. `MenuItem` mit `selected` ist `menuitemradio`. Eigene Panels nutzen `usePopoverFocus`. |
| `ActionMenu`, `PillMenu`, Benutzermenü | Menü-Button (APG): Enter/Leertaste/Pfeil runter öffnen (eigene Auslöser: `menuButtonKeyDown` aus `ui/popover.tsx`), Vertrag wie `Popover`. `aria-haspopup="menu"`, `aria-expanded`. |
| `SearchableSelect` / `SearchableMultiSelect` | Auslöser: Enter/Leertaste/Pfeile öffnen. Fokus im Suchfeld (`role="combobox"`), Optionen sind keine Tab-Halte; Pfeile, Bild auf/ab, Pos1/Ende bewegen die Markierung (`aria-activedescendant`), Enter wählt (Mehrfach: schaltet um, Liste bleibt offen). Escape/Tab schliessen, Fokus zurück auf den Auslöser. |
| `Select` | Echtes `<select>`, Fokus bleibt darauf: Pfeile/Leertaste/Enter/F4 öffnen, Pfeile/Bild/Pos1/Ende/Buchstaben wählen, Enter übernimmt, Tab/Escape schliessen. Touch: native Liste. |
| `DateInput` / `DatePicker` | Datum per Tastatur tippen (`TT.MM.JJJJ`). Kalender-Knopf öffnet; Pfeile Tag/Woche, Bild auf/ab Monat (+Umschalt: Jahr), Pos1/Ende Wochenanfang/-ende, Enter wählt, Escape/Tab-Ende zurück zum Knopf. |
| `TimeInput` | Freie Eingabe, Enter/Verlassen korrigiert. Knopf: Pfeile öffnen und wählen, Enter übernimmt (Fokus bleibt auf dem Knopf, `aria-activedescendant`). |
| `ColorInput` | Fläche und Farbton sind `slider` mit Pfeiltasten; Tab läuft durch Hex-Feld und Farbfelder, am Ende zurück hinter den Auslöser. |
| `TagInput` | Tippen + Enter legt an, Rücktaste löscht das letzte Tag. Pfeil runter springt in die Vorschläge, Pfeile wandern, Enter/Leertaste wählt, Pfeil hoch aus dem ersten Vorschlag zurück ins Feld. Entfernen-Knöpfe der Tags sind Tab-Halte. Verlassen per Tab schliesst die Vorschläge. |
| `KeywordInput` | Tippen + Enter oder Komma übernimmt den Begriff, Rücktaste im leeren Feld entfernt den letzten. Jeder Begriff hat einen Entfernen-Knopf (Tab-Halt), danach bleibt der Fokus im Feld. Verlassen per Tab übernimmt angefangenen Text. Test: `components/ui/keyword-input.test.tsx`. |
| `HelpPopover` | Nicht-modaler Dialog: Fokus auf die Erklärung (wird vorgelesen), Tab zum Doku-Link und danach hinter dem «?» weiter, Escape zurück aufs «?». |
| `ColumnFilter` | Dialog-Panel (`aria-haspopup="dialog"`), Optionen als Knöpfe mit `aria-pressed`. |
| `Tabs` | APG Tabs mit automatischer Aktivierung: ein Tab-Halt (roving tabindex), Pfeile links/rechts, Pos1/Ende; Panel mit `aria-labelledby`. |
| `FilterTabs` | Wie `Tabs` (Filter wechselt mit dem Pfeil sofort), ein Tab-Halt. |
| `RouteTabs` | Tabs als Links mit manueller Aktivierung: Pfeile verschieben nur den Fokus, Enter öffnet die Route; aktive Route `aria-current="page"`. |
| `DataTable` | Sortierknöpfe im Kopf, `aria-sort` an der sortierten Spalte. Zeilenaktionen als Knöpfe/`ActionMenu`. |
| `ReorderButtons` | Sichtbare Alternative zum Ziehen: «nach oben/unten», Fokus bleibt auf dem Knopf der verschobenen Zeile, neue Position wird angesagt. |
| `RichTextEditor` | Werkzeugleiste `role="toolbar"`, Knöpfe mit `aria-pressed`; Formatierung auch per Strg/⌘+B/I (Editor). Tab verlässt den Editor (kein Tab-Einfügen). |
| App-Shell | Erster Tab-Halt «Zum Inhalt springen» → `<main id="main-content">`. Aktive Navigation `aria-current="page"`. Einklappbare Seitenleiste: Menü-Knopf mit `aria-expanded`, per Tastatur geöffnet geht der Fokus hinein, Escape schliesst und gibt ihn an den Knopf zurück. |

## 3. Shortcut-Architektur

**Eine Registry, ein Dispatcher, eine Hilfe.**

- `frontend/lib/keyboard/registry.ts` - alle Produktivitäts-Shortcuts deklarativ: `id`, `keys`
  (`"Mod+K"`, `"Mod+Alt+T"`, `"/"`, `"?"`), `scope` (`global` | `page` | `component`), `group`
  (Hilfe), `inInputs`, `whenOverlayOpen`, `overridesBrowser`. Beschreibung unter
  `common.keyboard.shortcuts.<id mit _>` in allen Sprachen. Standard-Interaktionen der Bausteine
  stehen mit `kind: "standard"` nur zur Anzeige drin.
- `frontend/lib/keyboard/use-shortcut.ts` - `useShortcut(id, handler, { enabled, scopeRef })`. Ein
  einziger `keydown`-Listener; Vorrang: 1. oberstes Overlay (dessen eigene Tasten, Escape über
  `usePopupEscape`), 2. Bindung mit `scopeRef`, die den Fokus enthält, 3. `page`, 4. `global`.
  Genau eine Bindung wird ausgeführt; ein Handler gibt `false` zurück, wenn er nicht zuständig ist
  (dann die nächste bzw. der Browser).
- `frontend/components/ui/shortcut-help.tsx` - Hilfe mit «?» oder Benutzermenü › Tastenkürzel.
  Zeigt globale Kürzel, Standardtasten und nur die Seiten-Kürzel, die gerade gebunden sind.
- Beschriftung: `formatCombo`/`comboParts` (Registry) bzw. weiter `useShortcutLabel()` aus
  `@/lib/search/shortcuts` für Texte mit `{shortcut}`; `aria-keyshortcuts` über `ariaKeyShortcuts(id)`.

Schutzregeln des Dispatchers (gelten für jede Bindung, nicht pro Komponente nachbauen):
beim Tippen (Textfeld, Select, Editor, `contenteditable`) nur `inInputs: true`; Tasten ohne
Strg/⌘/Alt in Listen, Menüs, Tabs, Kalendern, Slidern gehören dem Widget; bei offenem Overlay nur
Bindungen in diesem Overlay oder mit `whenOverlayOpen`; IME-Komposition und `defaultPrevented`
werden nie angefasst; AltGr (Windows meldet Strg+Alt) ist nie ein Shortcut.

### Neue Shortcuts

Nur mit echtem Nutzen und bekannter Konvention. Vor dem Eintrag bewerten: Nutzen, Lernaufwand,
Konfliktrisiko (Browser, Betriebssystem, Screenreader, Layouts DE/CH/FR/IT/US), Auffindbarkeit.

- Keine globalen Einbuchstaben-Kürzel ausser `/` und `?` (beide nie beim Tippen).
- Nie belegen: `RESERVED_COMBOS` (Tabs/Fenster, Zwischenablage, Zoom, Zurück/Vor, F-Tasten …).
  Browser-Standards (`Mod+F`, `Mod+S`, `Mod+D`, `Mod+Z` …) nur mit `overridesBrowser: true` und
  Begründung im Review.
- **`event.key` vs. `event.code`:** Buchstaben ohne Alt über `event.key` (folgt dem aufgedruckten
  Zeichen, Strg+Z ist auf QWERTZ und QWERTY «Z»). Mit Alt über `event.code` (macOS-Option und AltGr
  verändern das Zeichen: ⌥T = «†»). Satzzeichen (`/`, `?`) über `event.key`, Umschalt ignoriert
  (CH/DE: `/` = Umschalt+7, `?` = Umschalt+'). Das erledigt `matchesCombo` - nie selbst vergleichen.
- Modifier immer `Mod` (Strg und ⌘ gleichwertig), Anzeige plattformgerecht (Apple ⌥⇧⌘, sonst
  Strg/Alt/Umschalt in der UI-Sprache).
- Eintrag + Übersetzung in allen Sprachen + `useShortcut` + ggf. `aria-keyshortcuts` am Auslöser.
  Die Registry-Tests prüfen Dubletten im selben Scope, ungültige Kombinationen, reservierte Tasten,
  fehlende Übersetzungen und die Darstellung auf beiden Plattformen.

`addEventListener("keydown")` ausserhalb von `lib/keyboard/`, `use-popup-escape.ts` und
`use-focus-trap.ts` meldet der Checker (`global-key-listener`). Lokale Tasten eines Widgets
(Pfeile in einer Liste) bleiben `onKeyDown` am Widget - das sind Standard-Interaktionen, keine
Shortcuts.

## 4. Fokusmanagement

Hilfen in `frontend/lib/a11y/`:

| Situation | Lösung |
|---|---|
| Dialog öffnet/schliesst | `Modal`/`useConfirm` erledigen alles. Eigene Vollbild-Dialoge (Viewer, Lightbox): `useModalFocus(open, ref)` + Container `tabIndex={-1}`, `role="dialog"`, `aria-modal`. Neue Dialoge nehmen `Modal`. |
| Startaktion im Dialog | `autoFocus` auf dem ersten sinnvollen Feld; Löschen-Rückfragen starten auf «Abbrechen». |
| Popover/Menü | `Popover` bzw. `usePopoverFocus` (Vertrag oben). Ein Menüeintrag, der einen Dialog öffnet, gibt den Fokus danach an den Menü-Auslöser zurück (`stableFocusTarget`). |
| Element verschwindet (Löschen, Speichern, Seitenwechsel) | `useFocusRescue` in der App-/Admin-Shell: nächster vorhandener Vorfahr → dessen erstes Tab-Ziel, sonst `#main-content`. Wo es ein besseres Ziel gibt (Nachbarzeile), setzt es die Komponente selbst. |
| Zusammengesetzte Widgets | Roving tabindex (`rovingKeyDown` aus `lib/a11y/roving.ts`) für Tab-Schienen/Werkzeugleisten; `aria-activedescendant` für Listen mit Suchfeld (Fokus bleibt im Feld). |
| Reihenfolge ändern | Drag-and-Drop braucht immer eine Tastatur-Alternative: `ReorderButtons` (sichtbar) oder `reorderKeyDown` (Alt+Pfeil am fokussierten Eintrag, `aria-keyshortcuts`), Ansage über `announce()`. |
| Asynchrone Updates | Fokus nicht wegnehmen; Ergebnis per Toast/`announce()`. Ladezustände ersetzen nicht den fokussierten Knopf durch einen Spinner ohne Namen. |

Keine unnötige Fokusmanipulation: nie Fokus «zur Sicherheit» setzen, nie `focus()` in jedem
Render; Mausbedienung darf sich dadurch nicht ändern (programmatischer Fokus nach Klick zeigt
keinen Ring).

## 5. Muster

```tsx
// Aktion, die den Fokus im Feld lässt (Vorschlagsliste)
<button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => pick(option)}>…</button>

// Shortcut einer Seite
useShortcut("designer.save", () => { void save(); });

// Alternative zum Ziehen
<ReorderButtons itemKey={`reorder:block:${block.id}`} name={block.title} index={i} count={n} onMove={(from, to) => move(from, to)} />

// Eigener Popover-Inhalt mit Feldern
<Popover open={open} onOpenChange={setOpen} anchorRef={triggerRef} role="dialog" label={t("filter")}>…</Popover>
```

## 6. Internationale Layouts und Plattformen

- Kürzel nie fest als «Ctrl+…»/«Strg+…» beschriften (DESIGN.md Abschnitt 9, Checker `kuerzel`).
- Tastennamen kommen aus `common.keys.*` (Strg, Umschalt, Entf, Pos1 … je Sprache).
- Getestet in `registry.test.ts`: QWERTZ (Strg+Z über `key`), macOS-Option (`code`), AltGr
  (ignoriert), CH-Satzzeichen (`/`, `?` mit Umschalt).

## 7. Testkonzept

1. **Vitest, Verhalten statt Handler:** Fokuswechsel, `aria-*`-Zustände, ausgelöste Aktionen
   (`keyboard-contracts.test.tsx`, `use-shortcut.test.tsx`, `registry.test.ts`).
2. **Playwright, nur Tastatur:** `e2e/keyboard-navigation.spec.ts` - Sprunglink, Hilfe, Tab-Falle,
   Menü → Dialog → Fokus zurück, Seitenleiste, Tabs. Neue Kern-Workflows bekommen dort einen Test
   mit `page.keyboard` und Fokus-Erwartungen.
3. **Statischer Check:** `check-keyboard-a11y.py` (JSX-Scanner, keine Zeilen-Regex). Altbestand ist
   in `scripts/keyboard-a11y-baseline.json` eingefroren und wird nur kleiner
   (`--update-baseline` verweigert Wachstum).
4. Scanner ersetzen keine echten Tastaturtests - beides gehört zu einer neuen Komponente.

## 8. Checkliste für neue oder geänderte interaktive Komponenten

- [ ] Alles ohne Maus erreichbar und auslösbar (Tab, Enter/Leertaste, Escape, Pfeile wo üblich)
- [ ] Logische Tab-Reihenfolge, kein positiver `tabIndex`, nichts Unsichtbares im Tab-Fluss
- [ ] Sichtbarer Fokus in Light und Dark
- [ ] Gemeinsamer Baustein genutzt (Modal, Popover/ActionMenu, SearchableSelect, Tabs …) statt Nachbau
- [ ] Dialog: Startfokus, Tab-Falle, Escape, Fokus zurück - über `Modal`
- [ ] Drag-and-Drop mit Tastatur-Alternative
- [ ] Neue Tastenkürzel in der Registry, mit Übersetzung, ohne Konflikt, in der Hilfe sichtbar
- [ ] Namen/Zustände: `aria-label`, `aria-expanded`, `aria-pressed`, `aria-current`, `aria-sort`
- [ ] Tests: Vertrag in Vitest; bei neuem Workflow ein Tastatur-Schritt in Playwright
- [ ] `python3 scripts/check-keyboard-a11y.py` meldet `Tastatur-Regeln: ok`
