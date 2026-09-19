# hocX Design-Regeln

Verbindlich für **jede** UI-Änderung in `frontend/` und `abgabebox-frontend/` (auch durch Claude Code).
Ziel: neue Oberflächen sehen aus wie die bestehenden, ohne dass jemand nachmessen muss.

Vor dem Commit: `python3 scripts/check-design-rules.py` muss `Design-Regeln: ok` melden (läuft auch in der CI).

## 1. Grundsätze

1. **Erst wiederverwenden, dann bauen.** Gibt es einen Baustein in Abschnitt 4, wird er benutzt. Ein Nachbau mit Inline-Styles ist ein Fehler, auch wenn er "schneller" geht.
2. **Nur Tokens, keine Literale.** Farben, Radien, Schriftgrößen, Abstände, Schatten, z-index und Dauern kommen aus `design/tokens.css`.
3. **Beide Themes.** Jede Änderung muss in Light **und** Dark stimmen. Keine festen Farben, die nur in einem Theme funktionieren.
4. **Tastatur first.** Alles Klickbare ist per Tab erreichbar und zeigt Fokus (Abschnitt 8).
5. **Klasse vor Inline-Style.** `style={{ ... }}` ist nur für dynamische Werte erlaubt (Breite in %, berechnete Position, Laufzeitfarbe), nie für wiederkehrende Optik.

## 2. Tokens

Quelle ist `design/tokens.css`. Nach jeder Änderung: `./scripts/sync-design-tokens.sh` (kopiert nach `frontend/app/tokens.css` und `abgabebox-frontend/app/tokens.css`, die Kopien nie von Hand editieren).

| Bereich | Tokens | Regel |
|---|---|---|
| Fläche/Text | `--bg` `--panel` `--panel-solid` `--text` `--muted` `--border` `--border-strong` | Seite = `--bg`, Karten/Panels = `--panel`, Eingabefelder/Dropdowns = `--panel-solid` |
| Akzent | `--accent` `--accent-strong` `--accent-soft` | Auswahl, Links, Fokus. `--accent-soft` für aktive/gewählte Hintergründe |
| Status | `--success` `--warning` `--danger` (Vollton), `-bg`/`-fg` (Fläche/Text darauf), `--info-*`, `--neutral-*` | Bedeutung immer über diese Tokens, nie über Tailwind-Hex |
| Auf Vollfarbe | `--on-solid` | Textfarbe auf `--accent`/`--success`/Scrims. Statt `#fff` |
| Primärbutton | `--primary` `--primary-strong` `--primary-contrast` | Nur für `.button-primary` |
| Diagramme | `--chart-1..5`, Bedeutungsfarben via Status-Tokens | Gemeinsame Zuordnung: `lib/constants/chart-colors.ts` |
| Radius | `--radius-xs` 4 · `-sm` 8 · `-md` 12 · `-lg` 16 · `-xl` 24 · `-pill` | Eingabefelder/Buttons `sm`, Karten `md`–`lg`, Modals `xl`, Chips/Badges `pill`. Kreise: `50%` |
| Schrift | `--text-xs` 12 · `-sm` 13 · `-base` 14 · `-md` 15 · `-lg` 16 · `-xl` 20 · `-2xl` 24 · `-3xl` 32 | Fließtext/Felder `base`, Hilfetexte `sm`/`xs`, Überschriften `xl`+ |
| Gewicht | 400 Text · 500 Betonung · 600 Buttons/Labels · 700 Überschriften | Kein 650/800 |
| Abstand | `--space-1` 4 · `-2` 8 · `-3` 12 · `-4` 16 · `-5` 24 · `-6` 32 | `gap`, `padding`, `margin` in diesen Stufen. 1–3 px Feinabstände und Werte >36 px sind frei |
| Schatten | `--shadow-soft` (Karte) · `--shadow` · `--shadow-popover` (Dropdowns) · `--shadow-overlay` (Modals) | Kein eigenes `rgba(...)` |
| Fokus | `--focus-ring` (Felder) · `--focus-ring-color` (Outline) | Abschnitt 8 |
| Bewegung | `--dur-fast` 120 · `-base` 160 · `-slow` 240 ms, `--ease-out` | Kein `0.15s` |
| Ebenen | `--z-dropdown` < `--z-sticky` < `--z-flyout` < `--z-popover` < `--z-overlay` < `--z-modal` < `--z-confirm` < `--z-portal` < `--z-fullscreen` < `--z-menu` < `--z-toast` | Lokales Stapeln (0–5) darf literal bleiben, alles darüber ist ein Token |
| Tabellenbreite | `--table-max-width` 1200 px | Gemeinsame Maximalbreite für `.table-shell`, in beiden Themes gleich |
| Breakpoints | `max-width: 640px` (Smartphone) · `900px`/`901px` (Tablet/Desktop) | Keine weiteren Werte. Media Queries können keine Variablen, daher hier festgelegt |

**Neues Token** nur, wenn keine Stufe passt und der Wert an mehreren Stellen gebraucht wird: in `design/tokens.css` (Light **und** Dark), Sync ausführen, hier dokumentieren.

Bewusst feste Ausnahmen (mit `design-ok`-Kommentar in derselben Zeile): QR-Code-Weiß, Foto-Viewer-Palette `--pv-*`, Dokumentvorlagen-Mockups (`--dt-accent`), Tag-Farbauswahl, Avatar-Farben, Zeilen, deren Padding an `calc(100vh …)` oder ein Icon gekoppelt ist.

## 3. Verboten

- Hex-/`rgb()`-Farben in Komponenten oder Feature-CSS (Ausnahmen oben)
- `var(--token, #hex)`: Tokens sind immer definiert, ein Fallback verdeckt Tippfehler
- Nicht definierte Variablen (`--surface`, `--fg` …). Der Checker meldet sie
- `border-radius`/`font-size`/`z-index`/`box-shadow`-Literale, Transition-Dauern als Zahl
- Umbenannte Klassen: `button-inline` (heißt `button-secondary`), `btn-icon*` (heißt `button-icon-soft*`)
- `window.confirm/alert/prompt`. Stattdessen `useConfirm()` / `useToast()`
- Eigene Overlays/Modals mit `position: fixed`. Stattdessen `Modal`
- Handgebaute Dropdowns mit Inline-Styles (Abschnitt 5)
- Neue `@media`-Breakpoints außer 640/900

## 4. Standardbausteine

Alle in `frontend/components/ui/` (Import: `@/components/ui/<name>`). Erst hier nachsehen, bevor etwas Neues entsteht.

| Aufgabe | Baustein | Hinweis |
|---|---|---|
| Dialog/Formular im Overlay | `Modal` (`open`, `title`, `onClose`, `size="default"\|"wide"\|"fullscreen"`) | Titel Pflicht. Aktionen unten in `<div className="modal-actions">` |
| Ja/Nein-Rückfrage | `useConfirm()` aus `@/contexts/confirm-context` | `await confirm({ message, tone: "danger", confirmLabel: "Löschen" })`. Löschen immer mit `tone: "danger"` |
| Rückmeldung nach Aktion | `useToast().showToast(text, "success" \| "error" \| "info")` | Fehler immer mit `"error"` und der Meldung aus dem Backend |
| Dauerhafter Hinweis im Inhalt | `StatusBanner` (`tone`, `message`) | Kein `<p style={{color: …}}>` |
| Status/Kategorie-Label | `Badge` (`variant`: success/warning/danger/info/neutral, `dot?`) | Nie eigene Pill-Farben |
| Status direkt ändern | `PillMenu` | Badge, das ein Menü öffnet |
| Auswahl aus Liste (Einzel) | `SearchableSelect` | Standard für Auswahl mit Suche, 73 Verwendungen |
| Auswahl aus Liste (Mehrfach) | `SearchableMultiSelect` | |
| Kurze feste Auswahl (<7 Optionen, ohne Suche) | natives `<select>` | Kein Nachbau |
| Aktionen einer Zeile/Karte | `ActionMenu` (`items: {label, onClick, danger?}[]`) | Kebab-Menü statt vieler Buttons |
| Tags | `TagInput` | Farben aus `TAG_COLORS` |
| Datum | `DateInput` | Nie `<input type="date">` roh |
| Suche | `SearchInput` | Nie eigenes Suchfeld |
| Filter (wenige Werte) | `FilterTabs` (`options`, `value`, `onChange`, optional `count`) | |
| Umschalten von Ansichten | `Tabs` (Inhalt) oder `RouteTabs` (eigene Route) | |
| Tabelle | `DataTable` + `DataToolbar` | Spalten als `columns`, Zeilen als Kinder, `emptyMessage` setzen |
| Paginierung | `Pagination` (`offset`, `limit`, `total`) | |
| Kopierbarer Wert | `CopyField` | |
| Datei ablegen | `file-drop-overlay` | |

## 5. Dropdowns und Vorschlagslisten

Entscheidungsbaum, von oben nach unten:

1. **Auswahl eines Datensatzes aus einer Liste** → `SearchableSelect` / `SearchableMultiSelect`.
2. **Aktionen zu einem Objekt** → `ActionMenu`.
3. **Status eines Objekts ändern** → `PillMenu`.
4. **Wenige feste Werte** → natives `<select>`.
5. **Autocomplete unter einem Textfeld** (Vorschläge erscheinen beim Tippen) oder eine Liste, die keiner der Bausteine abdeckt → CSS-Klassen `.dropdown-*` aus `globals.css`:

```tsx
<div style={{ position: "relative" }}>            {/* einziger erlaubter Inline-Style */}
  <input className="dropdown-search-input" value={q} onChange={…} />
  {open && (
    <div className="dropdown-panel dropdown-panel-down">
      <div className="dropdown-panel-scroll">
        {options.length === 0 ? (
          <div className="dropdown-empty">Keine Treffer</div>
        ) : options.map((o) => (
          <button key={o.id} type="button" onClick={…}
                  className={selected === o.id ? "dropdown-option dropdown-option-selected" : "dropdown-option"}>
            {o.label}
          </button>
        ))}
      </div>
    </div>
  )}
</div>
```

Varianten: `dropdown-panel-up` (öffnet nach oben), `dropdown-trigger` (Auslöser-Button), `dropdown-search` (Suchzeile im Panel), `dropdown-option-active` (Tastaturauswahl), `dropdown-hint` (Tastenhinweis wie „Tab"). Neue Dropdown-Optik = bestehende Klasse erweitern, nicht Inline-Style.

Dropdowns in einem `Modal` oder über anderen Ebenen brauchen die Portal-Ebene (`--z-portal`); `SearchableSelect` macht das schon.

## 6. Buttons

| Klasse | Wofür |
|---|---|
| `button-primary` | Die **eine** Hauptaktion pro Ansicht/Modal (Speichern, Erstellen) |
| `button-secondary` | Gleichrangige Aktion mit Rahmen (z. B. „CSV-Import", Filter- und Zusatzaktionen) |
| `button-ghost` | Nebenaktion ohne Gewicht (Abbrechen, Schliessen, Zurück) |
| `button-danger` | Zerstörerische Aktion (Löschen) |
| `button-toggle` / `-active` | Umschalter mit zwei Zuständen |
| `button-icon` | Quadratischer Icon-Button (36 px, mit Rahmen). Braucht `aria-label` |
| `button-icon-soft` / `-sm` / `-danger` | Kleiner, getönter Icon-Button in Listenzeilen. Braucht `aria-label` |
| `button-pill` | Filter-Chip als Button |

Regeln: Pro Bereich höchstens **ein** `button-primary`. Reihenfolge in Aktionsleisten: Abbrechen (ghost) → Nebenaktion → Hauptaktion (primary), rechtsbündig in `modal-actions`. Löschen ist nie primär hervorgehoben, sondern `button-danger` plus `useConfirm({ tone: "danger" })`. Ein Button, der nur Text und Icon hat, bekommt **keine** eigene Klasse: bestehende Variante wählen.

Native `<button>` ohne Klasse ist ein Primärbutton (globaler Stil). Immer `type="button"` setzen, außer echtes Submit.

## 7. Formulare, Tabellen, Seitenaufbau

**Seitenaufbau**
```tsx
<div className="grid">
  <div className="page-header">
    <div>
      <h1 className="page-title">Titel</h1>
      <p className="muted">Ein Satz, was man hier tut.</p>
    </div>
    <button type="button" className="button-primary">Neu</button>   {/* Hauptaktion der Seite rechts */}
  </div>
  {/* Filter: FilterTabs + SearchInput in .list-filter-row, dann DataTable */}
</div>
```
Karten: `.panel` / `.card` / `.section-card` (Innenabstand kommt aus der Klasse, unter 640 px automatisch 16 px). Kein eigenes `padding` auf Karten.

**Formulare**
```tsx
<label className="field-stack">
  <span className="field-label">Name</span>
  <input value={…} onChange={…} />
  <span className="field-help">Optionaler Hilfetext</span>
</label>
```
- Felder in `.field-stack` mit `.field-label` (oben, Großbuchstaben-Stil kommt aus der Klasse). Kein `placeholder` als Ersatz für das Label.
- Zusammengehörige Felder in `.grid` (Spalten), nicht mit Inline-`gridTemplateColumns`.
- Fehler: `useToast` oder `StatusBanner`, nicht rot eingefärbter Text per Inline-Style.
- Pflichtfeld-Prüfung: Button `disabled`, solange ungültig (wie in den bestehenden Formularen).

**Tabellen**: immer `DataTable` (+ `DataToolbar` für Titel/Aktionen). Zellen-Padding, Zeilenhöhe und Trennlinien kommen aus `.data-table`, nie pro Zelle überschreiben. Sortierbare Spalten über `columns[].sortable/onSort`. Zeilenaktionen: bis zu 2 direkt als Button (`button-danger` für Löschen, sonst `button-secondary`/`button-icon-soft`), mehr als 2 im `ActionMenu`. Leerer Zustand über `emptyMessage`.

**Modals**: `Modal` mit `title`; Inhalt als Formular (oben) und `modal-actions` (unten). Kein zweites Modal im Modal: dafür `useConfirm`.

## 8. Dark Mode, Fokus, Barrierefreiheit

- Farben nur über Tokens (sie haben Dark-Werte). Kein `@media (prefers-color-scheme)` in Komponenten-CSS, das Theme steuert `data-theme`.
- Tastaturfokus: Buttons/Links bekommen ihn automatisch (`:focus-visible` global). Eigene Formularfelder: `outline: none; border-color: var(--accent); box-shadow: var(--focus-ring);`. Nie `outline: none` ohne Ersatz.
- Icon-Buttons haben `aria-label`, Modals einen Titel, Tabellen echte `<th>`.
- Kontrast: Text auf `--x-bg` immer `--x-fg`, Text auf Vollfarbe immer `--on-solid`.
- Interaktive Flächen mindestens 28 px hoch (`button-icon-soft`), Standard 36–48 px.

## 9. Arbeitsablauf bei UI-Änderungen

1. Bestehenden Baustein (Abschnitt 4) oder eine ähnliche Seite suchen und **deren Struktur übernehmen**.
2. Neue Optik als Klasse in `frontend/app/globals.css` (Tokens verwenden), Klassennamen mit Feature-Präfix (`finance-…`).
3. `python3 scripts/check-design-rules.py` ausführen und alle Meldungen beheben.
4. Typecheck und Tests: auf dem Host gibt es kein Node, daher im Container: `docker compose exec frontend node_modules/.bin/tsc --noEmit` und `docker compose exec frontend node_modules/.bin/vitest run`.
5. Bei sichtbaren Änderungen Light **und** Dark bei 1440 und 390 px ansehen (Playwright-Screenshot gegen den E2E-Stack, `scripts/e2e.sh up`).
6. Token geändert → `./scripts/sync-design-tokens.sh`.

Regel unklar oder Wert fehlt? Nächstliegende Stufe nehmen und im Commit erwähnen. Kein Sonderwert.
