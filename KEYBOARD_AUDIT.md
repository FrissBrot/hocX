# hocX Keyboard-Accessibility-Audit

Stand: 2026-11-20, Branch `feat/keyboard-a11y` (Basis `origin/main` 2e6b41ea). Massstab: WCAG 2.2 AA
(2.1.1, 2.1.2, 2.1.4, 2.4.3, 2.4.7, 2.4.11, 3.2.1, 4.1.2; 2.4.12/2.4.13 als Qualitätsziel) und
WAI-ARIA Authoring Practices. Regeln und Architektur für die Zukunft:
`design/KEYBOARD_ACCESSIBILITY.md`.

**Kennzeichnung der Befunde** - wie bestätigt:
`[C]` Codeanalyse · `[U]` automatisierter Test (Vitest/jsdom) · `[B]` echte Browserinteraktion
(Playwright, Chromium, nur `page.keyboard`) · `[S]` statischer Check `scripts/check-keyboard-a11y.py`.
Nicht im Browser bestätigte Befunde sind ausdrücklich nur `[C]`.

**Schweregrad:** P0 ohne Maus unbenutzbar / Falle / Dialog unbedienbar · P1 Fokusführung,
unerreichbare Aktion, Konflikt in wichtigem Workflow · P2 inkonsistent/unpraktisch · P3 Komfort.

## 1. Abdeckung

| Bereich | Umfang | Methode |
|---|---|---|
| Gemeinsame Bausteine `frontend/components/ui/*` | alle 60 Dateien gelesen, interaktive vollständig (Modal, Confirm, Popover/Menu, ActionMenu, PillMenu, SearchableSelect/Multi, Select, DateInput/DatePicker, TimeInput, ColorInput, TagInput, HelpPopover, ColumnFilter, Tabs, FilterTabs, RouteTabs, DataTable, Pagination, LightboxImage, RichTextEditor, SearchInput, App-/Admin-Shell) | Code, Vitest, Teile Browser |
| Shortcuts | alle `keydown`/`keyup`/`addEventListener`/`ctrlKey`/`metaKey`/`altKey`-Stellen in `frontend/` und `abgabebox-frontend/` (46 Dateien mit Tastatur-Handlern, 197 Modifier-/Key-Vergleiche) | Code, Inventar Abschnitt 3 |
| Klickbare Nicht-Buttons, Pointer-only-Aktionen, positive tabIndex, Fokus-CSS | ganzes Frontend inkl. Abgabebox, alle CSS-Bundles | statischer Scanner `[S]` |
| Drag-and-Drop | alle 12 Dateien mit `draggable`/`onDragStart`/dnd-kit | Code |
| Workflows | App-Shell (Sprunglink, Navigation, Benutzermenü, Hilfe, Suche), Pendenzenliste, Protokoll-Editor, Document Studio, Fotos/Viewer, öffentliche Abgabebox | Code; Shell-Workflows Browser |
| Gesperrte Dateien (parallel umgebaut, siehe Abschnitt 7) | erfasst, nicht geändert | Code |

Nicht vollständig auditiert: jede einzelne Fachseite Zeile für Zeile (über 300 Komponenten). Die
fachlichen Seiten wurden über den Scanner, die gemeinsamen Bausteine (die sie fast überall
verwenden) und Stichproben abgedeckt.

## 2. Ausgangslage (vor der Umsetzung)

Stark: native Buttons fast überall, globaler `:focus-visible`-Ring, `Modal` mit Fokus-Rückgabe und
Tab-Falle, ein gemeinsamer Escape-Stapel (`usePopupEscape`), `Select`/`TimeInput`/`DatePicker` mit
sauberem APG-Verhalten, `aria-activedescendant` in der globalen Suche, plattformgerechte
Kürzelbeschriftung (`useShortcutLabel`).

Schwach: Tastaturbehandlung **dezentral** - 12 globale `keydown`-Listener mit je eigener Logik für
«nicht beim Tippen» und «nicht im Dialog» (teils fehlend), kein gemeinsamer Fokus-Baustein für
Popover, keine Shortcut-Übersicht, keine automatische Prüfung.

## 3. Shortcut-Inventar (vorher → nachher)

Standard-Interaktionen der Bausteine (Tab, Enter/Leertaste, Escape, Pfeile in Listen/Kalender/
Select) sind hier nicht aufgeführt, nur Produktivitäts-Kürzel.

| Kombination | Aktion | Scope | Ort (vorher) | Problem | Jetzt |
|---|---|---|---|---|---|
| Strg/⌘+K | globale Suche auf/zu | global, auch in Feldern | `lib/search/shortcuts.ts` | – | Registry `global.search`, Hilfe |
| Strg/⌘+F | Listensuche, zweites Mal Browsersuche | global | `lib/search/shortcuts.ts` + Marker `data-own-find` | Vorrang über DOM-Marker | `global.listSearch`; Seiten-Scope gewinnt automatisch |
| Strg/⌘+F im Suchfenster | Begriff in die Listensuche übernehmen | Suchfenster | `global-search.tsx` (User-Entscheid, kein Listeneintrag mehr) | – | nur dokumentiert (`search.toListSearch`), Datei unverändert |
| `/` | Listensuche, sonst globale Suche | global, nicht in Feldern | `lib/search/shortcuts.ts` | Checkbox galt als «Feld» | `global.quickSearch` |
| `?` | Shortcut-Hilfe | global, nicht in Feldern | – (neu) | – | `global.help` |
| Strg/⌘+F | Kapitelsuche Protokoll | Seite | `protocol-editor.tsx` (window) | feuerte auch in offenen Dialogen | `protocol.find` |
| Strg/⌘+Enter, +Umschalt | nächster/vorheriger Abschnitt (am Ende: Protokoll schliessen!) | Seite, auch in Feldern | `protocol-editor.tsx` | **feuerte in Dialogen über dem Editor** (P1: Strg+Enter in einem Dialog schloss das Protokoll) | `protocol.nextElement`/`previousElement`, im Dialog gesperrt |
| Pfeil hoch/runter | Abschnitt wechseln | Seite, nicht in Feldern | `protocol-editor.tsx` | **ignorierte `defaultPrevented` und Widgets**: Pfeile in TimeInput-Liste, Menüs, Popovern bewegten zusätzlich den Abschnitt (P1) | `protocol.elementDown/Up`, Widgets/Overlays haben Vorrang |
| Strg/⌘+Alt+T / +N | Pendenz / Notizen in der Sitzungsleiste | Seite | `protocol-editor.tsx` | **`event.key === "t"`: auf macOS ⌥T = «†» → nie ausgelöst** (P2) | `event.code` über `matchesCombo`; AltGr ausgeschlossen |
| 1–4 | Anwesenheitsstatus (Hover/Fokus/Menü) | Komponente | `attendance-board.tsx` (window) | – | `protocol.attendanceStatus`; im Menü über das Menü selbst |
| Strg/⌘+S, Z, Umschalt+Z, Y, D; Entf/Rücktaste; Alt+Pfeil; Escape | Speichern, Undo/Redo, Duplizieren, Löschen, Verschieben, Auswahl aufheben | Seite | `designer.tsx` (window) | Strg+D/Strg+S überschreiben Browser-Standards ohne Kennzeichnung; Strg+S wirkte auch bei offenem Dialog | Gruppe `designer.*`, `overridesBrowser` dokumentiert, Dialog sperrt |
| Pfeil links/rechts, J/L | Foto blättern | Viewer | `photo-viewer.tsx`, `public-share-gallery.tsx` (window) | öffentliche Galerie ohne «nicht beim Tippen» | `media.previous/next` mit `scopeRef` |
| Pfeil links/rechts | Datei blättern | Datei-Detail | `file-detail-modal.tsx` (window) | eigene Logik | `media.previous/next` mit `scopeRef` (Integration 1.4.3) |
| Escape | Fotoauswahl aufheben | Seite | `photos-view.tsx` (window) | eigener Escape-Listener neben dem Overlay-Stapel | `usePopupEscape` (Integration 1.4.3) |
| Escape | Datums-Tooltip schliessen | Komponente | `photo-date-marker.tsx` (document) | schloss zusätzlich den Dialog darunter | `usePopupEscape` |
| Tippen nach Strg+K | Zeichen puffern bis Suchfeld da ist | intern | `app-shell.tsx` | kein Shortcut | bleibt, `a11y-ok` |
| Enter in leerem Listenpunkt | Liste verlassen | Editor-intern | `rich-text-editor.tsx` | kein Shortcut | bleibt, `a11y-ok` |
| Strg/⌘+B/I | fett/kursiv | Editor | Tiptap | – | Standard des Editors (Titel der Knöpfe) |

Ergebnis: alle Produktivitäts-Kürzel laufen über **eine**
Registry und **einen** Dispatcher; die Hilfe («?») zeigt sie aus derselben Quelle.

## 4. Befunde

### P0 - ohne Maus unbenutzbar

| # | Befund | Dateien | Reproduktion | Ursache | Lösung | Status |
|---|---|---|---|---|---|---|
| K-01 | **Einträge aller Popover-Menüs per Tastatur praktisch unerreichbar** (ActionMenu in jeder Zeile, PillMenu, Benutzermenü, Spaltenfilter …); in Dialogen gar nicht | `ui/popover.tsx` (+ alle Nutzer) | Kebab-Menü fokussieren, Enter, Tab → Fokus läuft über die ganze Seite bis ans Ende von `<body>`; im Dialog nie | Panel als Portal am Ende von `<body>`, kein Fokus beim Öffnen, kein Tab-Umleiten | `usePopoverFocus`: Startfokus ins Panel, Pfeile/Pos1/Ende/Buchstabe im Menü, Tab verlässt hinter dem Auslöser, Escape/Auswahl → Fokus zurück | behoben `[C][U][B]` |
| K-02 | **TagInput: Vorschläge, Farbfelder, «Umbenennen», «+ neu» reagieren nicht auf Enter/Leertaste** | `ui/tag-input.tsx` (Pendenzen, Termine, Fotos, Abgaben …) | Tag-Feld, Tab auf einen Vorschlag, Enter → nichts | Aktionen nur auf `onPointerDown` | `onMouseDown` hält Fokus, Aktion auf `onClick`; Pfeile zwischen Feld und Vorschlägen; Tags entfernbar per Tab; Tab schliesst | behoben `[C][U]` |
| K-03 | **Pendenz aus der Liste öffnen nur per Mausklick auf die Zeile** | `todos/todo-list-view.tsx` | Liste per Tab: kein Ziel zum Öffnen | `<tr onClick>` ohne Tastatur-Gegenstück | Titel als `button.table-row-link` | behoben `[C][S]` |
| K-04 | Mandant (Plattform-Admin) öffnen, Audit-/Fehlerprotokoll und Joblauf-Details aufklappen nur per Maus | `admin/admin-tenant-management.tsx`, `admin-audit-log.tsx`, `admin-error-log.tsx`, `admin-job-status.tsx` | wie K-03 | `<tr onClick>` | `table-row-link` (Aufklappen mit `aria-expanded`) | behoben `[C][S]` |

### P1 - Fokusführung, unerreichbare Aktionen, Konflikte

| # | Befund | Dateien | Ursache | Lösung | Status |
|---|---|---|---|---|---|
| K-10 | Rückfrage (`useConfirm`) ohne Tab-Falle: Tab läuft auf die Seite dahinter; nach dem Schliessen Fokus auf `<body>` | `contexts/confirm-context.tsx` | keine Falle/Rückgabe | `useFocusTrap`, Auslöser merken (`stableFocusTarget`), `aria-labelledby/-describedby` | behoben `[C][U]` |
| K-11 | Modal-Tab-Falle zählt unsichtbare, deaktivierte und `tabindex=-1`-Elemente: steht das letzte gezählte Element nicht im Tab-Fluss, entkommt Tab aus dem Dialog; Tab bei verlorenem Fokus (`<body>`) landet hinter dem Dialog | `ui/modal.tsx` | einfacher Selektor, nur React-`onKeyDown` | `getTabbables` (sichtbar, aktiv, Radiogruppen), `useFocusTrap` auf `document` inkl. Fokus-Rückholung | behoben `[C][U][B]` |
| K-12 | Nach Schliessen eines Dialogs, dessen Auslöser gelöscht wurde, Fokus auf `<body>` | `ui/modal.tsx` | Rückgabe nur an verbundenes Element | Fallback `#main-content`; `useFocusRescue` für entfernte Elemente allgemein | behoben `[C][U]` |
| K-13 | Menüeintrag öffnet Dialog → nach dem Dialog Fokus auf `<body>` (Eintrag existiert nicht mehr) | Popover + Modal | Dialog merkte sich den Menüeintrag | Rückgabeziel = Menü-Auslöser (`registerReturnTarget`) | behoben `[C][B]` |
| K-14 | Eigene Vollbild-Dialoge (Foto-Viewer, öffentliche Galerie, Lightbox) ohne Startfokus, Falle und Rückgabe; Lightbox ohne Dialog-Rolle | `photos/photo-viewer.tsx`, `share/public-share-gallery.tsx`, `ui/lightbox-image.tsx` | eigene Overlays | `useModalFocus`, `role="dialog"` | behoben `[C]` |
| K-15 | Protokoll-Editor: Strg+Enter/Pfeile lösen in Dialogen/Menüen/Listen über dem Editor aus (siehe Inventar) | `protocol/protocol-editor.tsx` | eigener window-Listener | Registry + Dispatcher | behoben `[C][U]` |
| K-16 | Reihenfolge nur per Ziehen: Protokoll-Schnellnavigation, Blöcke einer Elementdefinition, Zeilen/Spalten im Tabellen-/Matrix-Designer (WCAG 2.1.1/2.5.7) | `protocol-editor.tsx`, `template/element-definition-manager.tsx`, `template/element-editor/row-designer.tsx` | keine Alternative | Alt+Pfeil (`reorderKeyDown`, `aria-keyshortcuts`) bzw. `ReorderButtons`, Ansage per `announce()` | behoben `[C]` |
| K-17 | Ausklappbare Seitenleiste (901–1100 px, Schreibmodus 901–1720 px) bleibt geschlossen im Tab-Fluss → Fokus unsichtbar (2.4.7/2.4.11) | `app/globals.css`, `ui/app-shell.tsx` | nur `transform` | `visibility` (verzögert), Menü-Knopf `aria-expanded`/`aria-label`, Fokus hinein, Escape | behoben `[C][B]` |
| K-18 | Kein Sprunglink, `<main>` umschloss die ganze App inkl. Navigation | `ui/app-shell.tsx`, `admin-shell.tsx`, `mobile/mobile-shell.tsx` | – | `SkipLink`, `<main id="main-content">` nur um den Inhalt | behoben `[C][B]` |
| K-19 | SearchableSelect: Optionen als Tab-Halte, Markierung nur optisch (Screenreader hört sie nicht), Mehrfachauswahl ohne Pfeiltasten, Fokus nach Auswahl auf `<body>` | `ui/searchable-select.tsx` | kein Combobox-Muster | `role="combobox"`, `aria-activedescendant`, Optionen `tabIndex=-1`, Pfeile/Bild/Pos1/Ende, Enter schaltet (Mehrfach), Auslöser öffnet mit Pfeil | behoben `[C][U]` |
| K-20 | Rich-Text-Werkzeugleiste: Knöpfe nur auf `onMouseDown` - per Tab erreichbar, aber Enter tut nichts; Listen-Knöpfe ohne Namen | `ui/rich-text-editor.tsx` | Pointer-only | `onClick` + Fokus halten, `aria-pressed`, `aria-label`, `role="toolbar"` | behoben `[C][S]` |
| K-21 | Zuweisung in der Sitzungsleiste, Datei-Vorschläge der Pendenz: Optionen nur per `onMouseDown` | `protocol/session-panel.tsx`, `todos/todo-file-picker.tsx` | Pointer-only | wie K-20 | behoben `[C][U][S]` |
| K-22 | HelpPopover: Doku-Link im Panel nur über die ganze Seite erreichbar | `ui/help-popover.tsx` | Portal ohne Fokus | Fokus aufs Panel (wird vorgelesen), Tab weiter hinter das «?» | behoben `[C][U]` |
| K-23 | DatePicker/ColorInput: Tab am Ende des Panels springt ans Ende von `<body>` | `ui/date-picker.tsx`, `ui/color-input.tsx` | Portal | `usePopoverFocus` (Modus Dialog) | behoben `[C]` |
| K-24 | Personen in der Zugriffsübersicht nur per Zeilenklick zu öffnen | `users/access-overview.tsx` | `<tr onClick>` | Name als Link | behoben `[C][S]` |

### P2 - Inkonsistenz, Semantik

| # | Befund | Lösung | Status |
|---|---|---|---|
| K-30 | `Tabs`/`FilterTabs`/`RouteTabs`: `role="tablist"` ohne Pfeiltasten, jeder Tab ein Tab-Halt, keine `aria-controls` | roving tabindex (`rovingKeyDown`), Panel `aria-labelledby`, RouteTabs `aria-current` | behoben `[C][U][B]` |
| K-31 | Benutzermenü/`ActionMenu`/`PillMenu` öffnen nicht mit Pfeil runter (im Browser gefunden); `ActionMenu` ohne `aria-haspopup`/`aria-expanded`; `PillMenu` meldet `listbox`, öffnet ein Menü; `ColumnFilter` meldet `menu`, öffnet Felder; Popover immer `role="menu"` | Rollen korrigiert, `Popover role/label` | behoben `[C][U]` |
| K-32 | Status-Menüeinträge ohne Auswahlzustand für Screenreader | `MenuItem selected` → `menuitemradio` + `aria-checked` | behoben `[C][U]` |
| K-33 | Sortierte Spalte ohne `aria-sort` | `DataTable` | behoben `[C]` |
| K-34 | Navigation: aktive Seite ohne `aria-current` (ausser Einstellungen), Menü-Knopf «☰» ohne Namen | App-/Admin-Shell | behoben `[C]` |
| K-35 | `SearchInput` ohne Namen, wenn kein Label | Platzhalter als `aria-label`-Fallback | behoben `[C]` |
| K-36 | Shortcut-Konflikte und Doppelauslösung nicht systematisch verhindert (Inventar) | Registry + Dispatcher + Registry-Tests | behoben `[C][U]` |
| K-37 | Toast-Meldung mit Navigation (`onMessageClick`) nur per Maus | – | **offen** `[S]` (Toasts verschwinden zeitgesteuert; Knopf-Variante braucht Design-Entscheid) |
| K-38 | Klickbare Zeilen/Karten mit Aktion auch als Knopf in der Zeile, aber ohne Marker: `element-definition-manager` (Definitionen), `template-builder`, `tenant-charges`, `event-overview-modal`, `role-management`, `admin-user-management`, `participant-manager`, `files-table`, `agenda-list-view`, `structured-list-table`, `protocol-builder`, `event-manager` | jeweils prüfen, `table-row-link` ergänzen oder Marker setzen | **Altbestand eingefroren** `[S]` (bedienbar, wo ein Knopf in der Zeile steht - nicht einzeln im Browser verifiziert) |
| K-39 | Drop-Zonen mit `role="button"` ohne Tastatur (`document-upload-modal`, `gallery-upload-modal`) - Dateiauswahl daneben per Knopf erreichbar | Rolle entfernen oder Tastatur ergänzen | **offen**, eingefroren `[S]` |
| K-41 | Weitere eingefrorene Scanner-Funde mit Tastatur-Alternative im selben Bereich: leere Arbeitsfläche im Document Studio abwählen (`canvas.tsx`, Escape wählt ab), Vorlagen-Studio-Fläche (`session-template-studio.tsx`), Word-Import (`word-import-wizard.tsx`), Bild/Leerfläche in der öffentlichen Galerie (`public-share-gallery.tsx`, Blättern per Pfeil/Knöpfen) | einzeln prüfen und markieren oder umbauen | **eingefroren** `[S]` |
| K-40 | Mehrere `<main>` (Document Studio «Arbeitsfläche», Finanzen) innerhalb der App-Shell | Bereich als `<section aria-label>`; Tests verwenden `getByRole("main")` | **offen** `[C]` |

### P3 - Komfort

| # | Befund | Status |
|---|---|---|
| K-50 | Shortcut-Hilfe fehlte | behoben («?», Benutzermenü, Registry) `[B]` |
| K-51 | TimeInput: Pos1/Ende in der Liste, Pfeil im Textfeld öffnet die Liste nicht | offen |
| K-52 | Fokus nach Seitenwechsel bleibt auf dem Navigationslink (Next.js-Routenansage vorhanden) | bewusst so belassen; Sprunglink genügt |
| K-54 | Weitere Menü-Auslöser (`protocol-editor-shared`, `attendance-board`, `todo-fine-section`, `event-manager`, `photo-viewer`) öffnen mit Enter/Leertaste, aber noch nicht mit Pfeil runter | offen; `menuButtonKeyDown` aus `ui/popover.tsx` ergänzen |
| K-53 | `todo-assignee-menu`, Planungs-Popups mit eigener Listenlogik statt `SearchableSelect` | offen (funktional bedienbar) |

## 5. Architektur-Entscheidungen

| Entscheidung | Begründung | Verworfen |
|---|---|---|
| **Eine Registry** `lib/keyboard/registry.ts` (deklarativ, Übersetzungsschlüssel, Scope, `inInputs`, `whenOverlayOpen`, `overridesBrowser`) | eine Quelle für Verhalten, Hilfe, Tests; keine zweite Liste | Shortcut-Bibliothek (neue Abhängigkeit, kein Mehrwert); Konfiguration pro Komponente |
| **Ein Dispatcher** (`useShortcut`) auf `window`, Bubble-Phase | Widgets/Dialoge (React-Handler, Escape-Stapel in Capture) laufen vorher und gewinnen über `defaultPrevented` - Priorität Overlay > Komponente > Seite > global ergibt sich ohne Sonderfälle | Capture-Phase (würde Widgets überstimmen) |
| `usePopupEscape` bleibt der Escape-Stapel | bewährt, berücksichtigt Verschachtelung und laufendes Speichern | Escape in die Registry ziehen |
| `event.key` für Buchstaben ohne Alt, `event.code` mit Alt, Satzzeichen per `key` ohne Umschalt, AltGr ignoriert | QWERTZ/QWERTY-Beschriftung, macOS-Option, CH-Layout (Umschalt+7 = `/`) | nur `code` (Strg+Z läge auf QWERTZ falsch) |
| Fokus-Hilfen in `lib/a11y/` statt Bibliothek (focus-trap, react-aria) | wenige, klar umrissene Fälle; vorhandene Bausteine behalten ihr Verhalten | Austausch der Bausteine |
| Statischer Check als **Python-JSX-Scanner** mit Baseline | ESLint ist im Projekt nicht installiert (nur `next lint`-Skript ohne Paket); `eslint` + `eslint-plugin-jsx-a11y` + TS-Parser wären eine schwere neue Toolchain für Pre-Commit/CI ohne Node auf dem Host. Der Scanner liest Tags strukturiert (Attribute, verschachtelte Ausdrücke, Strings, Regex, Kommentare) - keine Zeilen-Regex - und läuft wie die übrigen `check-*.py` | jsx-a11y (später möglich, Regeln sind kompatibel benannt) |
| **Kein axe-core** | die gefundenen Probleme waren Fokus-/Bedienfehler, die axe nicht erkennt; Tastaturtests prüfen sie direkt. axe wäre eine zusätzliche Abhängigkeit im E2E-Image ohne Nutzen für diesen Auftrag | `@axe-core/playwright` |
| Klickbare Zeilen behalten, Knopf/Link in der Zeile ergänzen (`table-row-link`) | Maus unverändert, Tastatur bekommt ein echtes Ziel; Tabellen-Semantik bleibt (kein `role="button"` auf `<tr>`) | `tr tabIndex` |

## 6. Prüfungen und Ergebnisse

Details und Zahlen: Abschlussbericht des Branches. Dauerhaft eingerichtet:

- `scripts/check-keyboard-a11y.py` - Claude-Hook (`scripts/hooks/design-check-hook.sh`), Pre-Commit,
  CI (`ci.yml`, Schritt mit `check-design-rules.py`), Tests `scripts/tests/test_keyboard_a11y.py`.
  Erster Lauf gegen den Bestand: **50 Funde** (34 klickbare Nicht-Buttons, 7 Pointer-only, 5
  globale Listener, 2 Rollen ohne Tastatur, 2 `outline: none` ohne Ersatz). Davon behoben oder
  begründet markiert: 25; **eingefroren: 25 in 21 Dateien** (`scripts/keyboard-a11y-baseline.json`,
  Liste mit `--list`). Neue Funde blockieren, die Baseline kann nur schrumpfen.
- Vitest: `components/ui/keyboard-contracts.test.tsx`, `lib/keyboard/registry.test.ts`,
  `lib/keyboard/use-shortcut.test.tsx`.
- Playwright: `e2e/keyboard-navigation.spec.ts`.

## 7. Gesperrte Dateien - bei der Zusammenführung (1.4.3) umgesetzt

Diese Dateien werden parallel umgebaut und wurden hier **nicht** inhaltlich geändert. Sie
profitieren automatisch von den korrigierten Bausteinen (Modal, Popover/Menüs, SearchableSelect,
TagInput, DateInput, TimeInput, Confirm). Offen nach dem Merge:

| Datei | Befund | Umsetzung |
|---|---|---|
| `files/file-detail-modal.tsx` | eigener `window`-Listener für Pfeil links/rechts (Blättern) mit eigener «nicht beim Tippen»-Logik | erledigt: `useShortcut("media.previous"/"media.next", …, { scopeRef })`, Listener entfernt, Baseline gesunken |
| `files/document-panel.tsx` | keine Tastaturbefunde im Code | – |
| `photos/photos-view.tsx` (Fotos-Seite) | eigener Escape-Listener (Auswahl aufheben) neben dem Overlay-Stapel | erledigt: `usePopupEscape(selectedIds.size > 0 && viewerIndex === null, clear)`, Baseline gesunken |
| `photos/*` Kopfzeile/Werkzeugleiste/Suche, `photo-bulk-bar.tsx` | Popover «Beste» nutzt `action-menu-item` ohne `role="menuitem"` → keine Pfeiltasten (Startfokus und Tab funktionieren über das Popover) | erledigt: `role="menuitem"` + `menuButtonKeyDown`; Sortier-Menü der Kopfzeile ebenso, Tag- und Album-Panel als `role="dialog"` |
| `events/event-create-modal.tsx`, Bearbeiten, `mobile/mobile-events.tsx` | über `Modal`/Bausteine abgedeckt; `event-manager.tsx` (nicht gesperrt) hat klickbare Zeilen mit Kontextmenü - Knopf vorhanden | geprüft (`event-dialog.tsx`, `photos-header.tsx`, `document-panel.tsx`, `todo-edit-modal.tsx`): keine Funde |
| `todos/todo-edit-modal.tsx` (neuer Knopf) | neuer Knopf mit `type="button"` und Namen; Test `todo-edit-modal.test.tsx` hier minimal angepasst (Datei-Vorschlag per `click` statt `mouseDown`, weil `todo-file-picker` jetzt auf `onClick` reagiert) | übernommen |
| `submission-assignments/submission-assignment-form.tsx` (neues Tag-Feld) | nutzt `TagInput` → K-02 automatisch behoben | Tag-Feld per Tastatur nachtesten |
| `settings/activity-log.tsx` | keine Tastaturbefunde im Code | – |

## 8. Grenzen

- Screenreader-Ausgaben (NVDA/JAWS/VoiceOver) wurden nicht mit echter Hilfstechnik geprüft, nur
  über Rollen/Namen in jsdom und Chromium.
- macOS/Windows-Tastaturen und physische CH/DE-Layouts: über simulierte `KeyboardEvent`s getestet
  (Registry-Tests), nicht an echter Hardware.
- Touch-Bedienung: Verhalten nicht geändert (keine neuen Pointer-Handler), aber nicht auf Geräten
  nachgetestet.
- Fachseiten ausserhalb der Stichproben: abgedeckt durch Bausteine und Scanner, nicht einzeln im
  Browser durchgespielt.
