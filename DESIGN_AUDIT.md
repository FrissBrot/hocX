# hocX Design Audit

Stand: 2026-09-30. Basis: `main`-Branch, vollständige Durchsicht von `frontend/` (Hauptapp + Plattform-Admin) und `abgabebox-frontend/` gegen die verbindlichen Regeln in `design/DESIGN.md`. Vorgehen: Inventar aller Routen/Komponenten über Codesuche, danach gezielter Line-by-Line-Vergleich vergleichbarer Seiten (Listen-Manager, Admin-Seiten, Modals, Tabellen, Lösch-Bestätigungen, Icon-Buttons). `python3 scripts/check-design-rules.py` meldet aktuell `Design-Regeln: ok` — die Token-Ebene (Farben, Radien, Schriftgrössen, z-index) ist sauber durchgesetzt. Die gefundenen Probleme liegen fast ausschliesslich **eine Ebene darüber**: bei Komponenten-/Muster-Entscheidungen, die der Checker nicht prüfen kann (welche Button-Klasse für die Hauptaktion, welches Wort für „löschen“, welches Icon für „bearbeiten“).

Kein Code wurde in diesem Schritt geändert. Dies ist ausschliesslich der Audit-Bericht gemäss Auftrag.

## Executive Summary

hocX hat bereits ein ungewöhnlich diszipliniertes Fundament: ein zentrales Token-System (`design/tokens.css`), ein durchgesetzter Linter, 73 `SearchableSelect`-Verwendungen, 46 Dateien mit `useConfirm`, praktisch kein `window.confirm`, und ein fast überall wiederverwendetes `page-header`/`page-title`-Skelett (27 Fundstellen). Das Problem ist nicht fehlende Struktur, sondern **unvollständig durchgezogene Konventionen**: Regeln, die in `DESIGN.md` klar stehen oder die sich aus der Mehrheit der Seiten klar ablesen lassen, werden an einzelnen Stellen anders gehandhabt — und zwar oft nicht zufällig verteilt, sondern konsistent falsch innerhalb ganzer Module (z. B. Finanzen, Abgaben, Templates).

Die vier grössten Hebel:

1. **Primäre Seitenaktion uneinheitlich gestylt.** In mind. 7 von 12 untersuchten Listen-/Manager-Seiten ist der einzige „Neu anlegen“-Button im `page-header` ein `button-secondary`, obwohl `DESIGN.md` §7/§8 genau dafür `button-primary` vorschreibt — und in der `EmptyState`-Variante *derselben Seite* wird für *dieselbe Aktion* korrekt `button-primary` verwendet. Der Benutzer sieht also je nachdem, ob eine Liste leer ist oder nicht, zwei verschiedene Button-Gewichte für denselben Klick.
2. **Kein gemeinsames Icon-Set für Zeilen-/Objekt-Aktionen.** Es gibt `frontend/components/ui/nav-icons.tsx` für die Sidebar (22 saubere SVG-Icons), aber keine äquivalente Bibliothek für Bearbeiten/Löschen/Schliessen/Kopieren auf Zeilenebene. Stattdessen: rohe Unicode-Zeichen (`✎`, `✕`, `＋`) in mindestens 6 Dateien, eigene Inline-`<svg>` in 29 weiteren Dateien, und `ActionMenu`-Textlabels als dritte Variante für dieselbe Funktion.
3. **Löschen-Terminologie uneinheitlich.** „Löschen“, „Entfernen“ und „Widerrufen“ werden für echte, unwiderrufliche Löschvorgänge gemischt verwendet; die Bestätigungstexte variieren zwischen „X löschen?“, „X endgültig löschen?“ und „X wirklich löschen?“ ohne erkennbare Regel, wann welche Formel gilt.
4. **Ein Seiten-Header ist auf Englisch.** `frontend/app/templates/[id]/page.tsx` zeigt „Template Detail“ und einen englischen Fliesstext, obwohl CLAUDE.md UI-Texte verbindlich auf Deutsch vorschreibt und jede andere Seite im Produkt Deutsch ist.

Keiner dieser Punkte ist gross im Umfang der Korrektur (fast alles ist `small`/`medium`), aber jeder ist für Benutzer sofort sichtbar, weil er eine bereits gelernte Erwartung bricht.

## Design System Inventory

**Tokens** (`design/tokens.css`, synchronisiert nach `frontend/app/tokens.css` und `abgabebox-frontend/app/tokens.css`, Diff aktuell leer → in Sync): Fläche/Text, Akzent, Status (success/warning/danger/info/neutral), `--on-solid`, Primärbutton-Trio, 5 Chart-Farben, 6 Radius-Stufen, 8 Schriftgrössen, 6 Abstandsstufen, 4 Schatten-Stufen, Fokus-Ring, 3 Bewegungsdauern, 10 z-Index-Ebenen, Tabellenbreite, 2 Breakpoints. `check-design-rules.py` meldet aktuell keine Verstösse gegen Hex-Farben, Radius-/Schrift-/z-index-Literale oder `var(--x, #fallback)`.

**Bausteine in `frontend/components/ui/`** (37 Dateien): `Modal`, `useConfirm`/`ConfirmProvider`, `useToast`, `Badge`, `PillMenu`, `SearchableSelect`, `SearchableMultiSelect` (impliziert, gleiche Datei-Familie), `ActionMenu`, `TagInput`, `DateInput`, `SearchInput`, `FilterTabs`, `Tabs`/`RouteTabs`, `DataTable`, `Pagination`, `CopyField`, `EmptyState`, `StatusBanner`, `AppShell`/`AdminShell`, `NavIcon`-Set, `Popover`, `LightboxImage`, `SnapshotSwitcher`, `FileDropOverlay`, `RichTextEditor`, `DomainWizardModal`, `ProfileModal`, `ShareLinkModal`.

**Route-Inventar:** 39 `page.tsx` unter `frontend/app/` (11 davon Plattform-Admin unter `/admin/*`), plus 3 Katalogrouten (`abgabebox-frontend`: 8 Dateien, 640 Zeilen gesamt, eigenständige öffentliche Upload-App ohne Zugriff auf `frontend/components/ui/`).

**Bereits konsistente, positive Muster** (zur Einordnung, damit die Kritik unten nicht overclaimt): Zwei-Stufen-Empty-State ist absichtlich und einheitlich — Seiten mit 0 Datensätzen zeigen `EmptyState` oberhalb der Tabelle, gefilterte/leere Ergebnismengen zeigen `DataTable`s `emptyMessage` (6 Dateien nutzen beides bewusst nebeneinander: `shared-links-view.tsx`, `fines-view.tsx`, `participant-manager.tsx`, `todo-list-view.tsx`, `submission-assignment-manager.tsx`, `document-template-manager.tsx`). `useConfirm` wird 46-mal verwendet, `window.confirm` kommt genau einmal vor (`connectivity-status.tsx:39`) und ist korrekt mit `// design-ok`-Kommentar als bewusste Ausnahme (Seitenverlassen-Warnung, kein Produkt-Dialog) markiert.

## Critical Inconsistencies

Die Probleme mit der grössten sichtbaren Wirkung, sortiert nach Reichweite.

1. **Primärbutton vs. Sekundärbutton für die Hauptaktion einer Seite.** Siehe Abschnitt „Button & Action Inconsistencies“ — betrifft 7+ Seiten und widerspricht `DESIGN.md` §7/§8 direkt.
2. **Kein gemeinsames Aktions-Icon-Set.** Siehe „Icon Inconsistencies“ und „Duplicate Components“.
3. **Englischer Seiten-Header** in `frontend/app/templates/[id]/page.tsx:32-34` — einzige Stelle im Produkt.
4. **Löschen-Terminologie** („Löschen“ vs. „Entfernen“ vs. „Widerrufen“, plus drei verschiedene Bestätigungsformeln) — siehe „Terminology Inconsistencies“.
5. **Icon-Only-Buttons ohne `aria-label`** in `finances-view.tsx` (5 Stellen) — einziger Ort im untersuchten Code, an dem `title` ohne `aria-label` gesetzt wird, während `action-menu.tsx:18` das korrekte Muster (`title` + `aria-label` gleichzeitig) zeigt.
6. **Drei verschiedene Klassennamen für denselben Header-Aktionsleisten-Wrapper** (`table-toolbar-actions`, `page-header-actions`, `subm-toolbar-actions`) für exakt dieselbe visuelle Rolle.
7. **Gleicher Text, zwei Formulierungen, in derselben Datei:** `protocol-editor.tsx:1586` „← Zurück zu Protokollen“ vs. `protocol-editor.tsx:1984` „← Zurück zu den Protokollen“ — gleicher Zielort, gleiche Komponente.

## Page Layout Inconsistencies

| Seite / Datei | Header-Aufbau | Abweichung |
|---|---|---|
| `participant-manager.tsx:318-336`, `event-manager.tsx:646-665`, `todo-list-view.tsx:404-418`, `files-view.tsx:182-198`, `photos-view.tsx:363-382` | `page-header` → `table-toolbar-actions` | Referenzmuster (5 Treffer), gilt als De-facto-Standard |
| `admin-tenant-management.tsx:313-326` | `page-header` → `page-header-actions` | Eigener Klassenname für identische Rolle, einzige Fundstelle |
| `submission-assignment-manager.tsx:596-614` | `page-header` → `subm-toolbar-actions` | Wieder ein eigener Klassenname, zusätzlich mit ClamAV-Status-Pill und `Links (n)`-Button vermischt, die in keinem anderen Header vorkommen |
| `frontend/app/templates/[id]/page.tsx:32-34` | Kein `page-header`/`page-title`, stattdessen `eyebrow` + nackter `<h1>{template.name}</h1>` direkt in der `page.tsx`-Routendatei | Einzige Detailseite, deren Kopfbereich nicht in einer `components/`-Datei liegt; einzige Seite ohne `page-header`-Grid; Text auf Englisch |
| `finances-view.tsx:241-246`, `fines-view.tsx:156-161`, `shared-links-view.tsx:56-61`, `dashboard-view.tsx:98-103` | `page-header` ohne jede Aktion (auch im nicht-leeren Zustand) | Inkonsistent zu allen anderen Listen-Seiten, die mindestens eine Sekundäraktion im Header zeigen — bei Finanzen liegt „Konto erstellen“ separat in der Sidebar (`finances-view.tsx:282`), nicht im Seiten-Header wie überall sonst |
| `element-definition-manager.tsx:1863-1868` | Zwei `<p className="muted">`-Absätze hintereinander | Einzige Seite mit zweizeiliger Beschreibung; überall sonst genau ein Satz, wie `DESIGN.md` §8 vorgibt („Ein Satz, was man hier tut“) |

**Back-Navigation:** uneinheitlich implementiert — `protocol-editor.tsx` verlinkt mit rohem `<a href="/protocols">` (volles Page-Reload) an zwei Stellen mit unterschiedlichem Text, während `admin-shell.tsx:216` für dieselbe Rolle (Zurück zur Übersicht) ein Next.js `<Link href="/admin">` innerhalb einer echten Breadcrumb-Komponente (`topbar-breadcrumb`) verwendet. Die Hauptapp (`app-shell.tsx:326`) hat ebenfalls eine Breadcrumb-Leiste (`topbar-breadcrumb`) — Protokoll-Detail nutzt sie nicht und baut stattdessen einen eigenen Text-Link nach.

- Datei: `frontend/components/protocol/protocol-editor.tsx:1586,1984`
- Vergleich: `frontend/components/ui/admin-shell.tsx:213-219`, `frontend/components/ui/app-shell.tsx:326-333`
- Problem: Zurück-Navigation ist auf Protokoll-Detailseiten ein handgebauter Link statt der vorhandenen Breadcrumb-Komponente, mit zwei unterschiedlichen Texten für denselben Sprung
- Empfehlung: Bestehende `topbar-breadcrumb` aus `AppShell` auch für den Protokoll-Editor aktivieren (oder, falls das aus Layoutgründen nicht geht, einen Text vereinheitlichen und auf `<Link>` statt `<a>` umstellen)
- Aufwand: small

## Navigation & Menu Inconsistencies

- **Header-Icon vs. Header-Text für „Neu anlegen“:** `submission-assignment-manager.tsx:610-612` kombiniert `<PlusIcon />` (inline SVG) mit Text „Abgabe“; alle anderen Seiten mit „+“-Präfix (`list-manager.tsx:432`, `cycle-config-manager.tsx:253`, `protocol-builder.tsx:224`, `todo-list-view.tsx:415`, `finances/fines-view.tsx:170`, `document-template-manager.tsx:1404`, `files-view.tsx:194`) verwenden das literale Zeichen `+` als Teil des Textstrings, kein Icon-Element. `submission-assignment-manager.tsx` ist der einzige Ort mit echtem SVG-Plus.
  - Empfehlung: einheitlich literales `+` im Label lassen (10 von 11 Stellen tun das bereits) oder projektweit auf eine `PlusIcon`-Komponente umstellen — nicht beides. Aufwand: small.
- **ActionMenu-Schwelle wird nicht überall eingehalten:** `DESIGN.md` §8 sagt „bis zu 2 direkt als Button, mehr als 2 im `ActionMenu`“. `admin-tenant-management.tsx` zeigt Zeilenaktionen über `ActionMenu` korrekt gebündelt; `finances-view.tsx:307-308` und `:405-406` zeigt dagegen zwei rohe Icon-Buttons direkt (kein `ActionMenu` vorhanden — das ist bei nur 2 Aktionen erlaubt, aber die beiden Buttons folgen nicht dem `button-icon-soft`+`aria-label`-Muster, das andere 2-Aktionen-Zeilen verwenden, siehe Accessibility unten).
- **`ActionMenu` selbst ist konsistent implementiert** (`action-menu.tsx`), nur 8 Verwendungen — viele Tabellen mit mehr als 2 Zeilenaktionen bauen stattdessen eigene `mini-menu`-Klassen nach (`event-manager.tsx:661`: `mini-menu mini-menu-compact mini-menu-end`). Das ist eine zweite Dropdown-Implementierung parallel zu `ActionMenu`, die in `DESIGN.md` §4 nicht als Baustein gelistet ist.
  - Datei: `frontend/components/events/event-manager.tsx:661-665`
  - Vergleich: `frontend/components/ui/action-menu.tsx`
  - Problem: Eigene `mini-menu`-Klassenfamilie statt des vorhandenen `ActionMenu`-Bausteins für ein Kebab-artiges Menü
  - Empfehlung: prüfen, ob `mini-menu` durch `ActionMenu` ersetzt werden kann; falls `mini-menu` einen echten Zusatzbedarf abdeckt (z. B. Ansichts-Umschalter statt Objekt-Aktionen), als eigenständigen, dokumentierten Baustein in `DESIGN.md` §4 aufnehmen statt stillschweigend zu duplizieren
  - Aufwand: medium

## Button & Action Inconsistencies

Kernbefund: die **eine** Hauptaktion einer Seite (der Fall, den `DESIGN.md` §7 explizit mit `button-primary` belegt) ist nur in der Minderheit der Seiten tatsächlich `button-primary`.

| Datei:Zeile | Aktion | Tatsächliche Klasse | Regelkonform? | Vergleich |
|---|---|---|---|---|
| `admin-tenant-management.tsx:322` | „+ Neuer Mandant“ | `button-primary` | ✅ | — |
| `document-template-manager.tsx:1404` | „+ Neues Layout“ | `button-primary` | ✅ | — |
| `list-manager.tsx:432` (Header) | „Neue Liste“ | `button-secondary` | ❌ | `list-manager.tsx:439` EmptyState, **gleiche Aktion**: `button-primary` |
| `user-management.tsx:183-185` (Header) | „Neuer Benutzer“ | `button-secondary` | ❌ | EmptyState-Variante direkt darunter: `button-primary` |
| `cycle-config-manager.tsx:245-254` | „+ Neuer Zyklus“ | `button-secondary` | ❌ | sollte laut §7 primary sein (einzige Seitenaktion) |
| `template-builder.tsx:523-525` | „+ Vorlage“ | `button-secondary` | ❌ | einzige Seitenaktion |
| `element-definition-manager.tsx:1869-1881` | „Neues Element“ | `button-secondary` | ❌ | einzige Seitenaktion |
| `protocol-builder.tsx:223-225` | „+ Neues Protokoll“ | `button-secondary` | ❌ | einzige Seitenaktion |
| `files-view.tsx:193-195` | „+ Dateien hochladen“ | `button-secondary` | ❌ | einzige Seitenaktion |

- Problem: Für dieselbe konzeptionelle Aktion („leg einen neuen Datensatz dieses Typs an“) wechselt die visuelle Priorität je nachdem, ob man sie im gefüllten Seiten-Header oder im Empty-State derselben Seite anklickt. Ein Benutzer, der die Seite einmal leer und einmal gefüllt sieht, lernt zwei widersprüchliche Signale für denselben Klick.
- Empfehlung: Seiten mit genau einer Kopfaktion konsequent auf `button-primary` umstellen (wie es `admin-tenant-management.tsx` und `document-template-manager.tsx` bereits richtig machen). Nur Seiten mit mehreren gleichrangigen Kopfaktionen (z. B. `event-manager.tsx` mit CSV-Import + Export + Ansichtsmenü) behalten `button-secondary`/`button-ghost` für die Nebenaktionen und bekommen eine klar erkennbare `button-primary` für die tatsächliche Hauptaktion.
- Aufwand: small (reine Klassenänderung, keine Logik betroffen) — aber **hoher Impact**, da auf fast jeder Listenseite sichtbar.

**Weitere Buttonbefunde:**

- `finances-view.tsx:210` Konto-Erstellen-Button in der Sidebar nutzt `button-icon-soft` mit Zeichen `＋` (Vollbreiten-Plus, U+FF0B) statt des normalen ASCII `+`, das überall sonst verwendet wird (`+ Neue Liste` usw.). Mini-Inkonsistenz, aber leicht sichtbar bei Schriftvergleich. Aufwand: small.
- `finances-view.tsx:307-308,405-406`: Löschen-Button nutzt Zeichen `✕` statt `button-danger`/`ActionMenu`-Text „Löschen“, wie es der Rest der App für Zeilenlöschung nutzt (vgl. `admin-tenant-management.tsx:394`, `protocol-builder.tsx:338` — beide als Textlabel in `ActionMenu`). Aufwand: small–medium (Entscheidung nötig, ob Finanzen-Zeilen auf `ActionMenu` umgestellt werden oder bewusst kompakter bleiben).
- `participant-manager.tsx:325`: Klasse `button-secondary button-ghost` kombiniert zwei Button-Varianten auf einem Element (`CSV-Import`). `DESIGN.md` §7 listet keine Kombination dieser beiden Klassen; `event-manager.tsx:653` und `todo-list-view.tsx:410` nutzen für denselben „CSV Import“/Export-Fall ebenfalls `button-secondary button-ghost`, das Muster ist also mindestens *intern* konsistent (3 Fundstellen), aber nicht in `DESIGN.md` §7 als eigene Kombination dokumentiert. Empfehlung: entweder als offizielle dritte Stufe „button-secondary-ghost“ in `DESIGN.md` aufnehmen, oder klären, ob nur `button-secondary` gemeint war. Aufwand: small.

## Icon Inconsistencies

Es existiert **ein** gepflegtes Icon-System: `frontend/components/ui/nav-icons.tsx` (22 Sidebar-Icons, einheitlich `viewBox 0 0 24 24`, `strokeWidth 1.75`, 18×18px). Für alles ausserhalb der Sidebar-Navigation — Bearbeiten, Löschen, Schliessen, Plus, Kopieren auf Zeilen-/Objektebene — gibt es **kein** gemeinsames Äquivalent. Drei parallele Lösungen existieren nebeneinander:

1. **Rohe Unicode-Zeichen** direkt im JSX: `✎` (Bearbeiten) in `finances-view.tsx:307,405`, `submission-assignment-manager.tsx:666`, `submission-link-manager.tsx:173`, `tag-input.tsx:257`, `checkbox-candidate-modal.tsx:134`, `planning-icon-trigger.tsx:15` (dort sogar als **Default-Prop-Wert** `icon = "✎"` einer wiederverwendbaren Komponente einprogrammiert); `✕` (Schliessen/Löschen) u. a. in `finances-view.tsx:308,406`; `＋` (Plus) in `finances-view.tsx:282`.
2. **Eigene Inline-`<svg>`** in 29 Dateien (`lightbox-image.tsx`, `pill-menu.tsx`, `date-input.tsx`, `copy-field.tsx`, `search-input.tsx`, `file-drop-overlay.tsx`, `domain-wizard-modal.tsx`, `fines-view.tsx`, `word-import-wizard.tsx`, `template-builder.tsx`, `statistics-view.tsx`, `admin-mfa-settings.tsx`, `photo-similar-groups.tsx`, `photo-tile.tsx`, `admin-shell.tsx`, `album-photo-picker.tsx`, `cycle-config-manager.tsx`, `files-table.tsx`, `document-template-manager.tsx`, `submission-assignment-manager.tsx`, `modal.tsx` (Schliessen-X, korrekt zentral), `gallery-upload-modal.tsx`, `document-upload-modal.tsx`, `album-share-modal.tsx`, `file-detail-modal.tsx`, `todo-edit-modal.tsx`, `todo-list-view.tsx` u. a.) — jede mit eigener `viewBox`/`strokeWidth`/Grösse, nicht an `nav-icons.tsx`s Konvention angelehnt.
3. **Textlabel in `ActionMenu`** („Bearbeiten“, „Löschen“, „Duplizieren“) als dritte, textbasierte Variante — die laut Briefing eigentlich bevorzugte Icon-only-Lösung für eindeutige Aktionen wie Edit/Delete/Close wird hier also gerade *nicht* icon-only umgesetzt.

- Datei: `frontend/components/protocol/planning/planning-icon-trigger.tsx:15`
- Vergleich: `frontend/components/ui/action-menu.tsx:18` (SVG-Kebab-Icon über `<Icon>`-artige Struktur wäre der saubere Weg)
- Problem: Eine wiederverwendbare Komponente hardcodet ein Unicode-Zeichen als Default-Icon; jede neue Verwendung erbt eine Nicht-SVG-Optik, die sich nicht an Token-Grösse/Strichstärke hält und auf manchen Systemschriften anders aussieht
- Empfehlung: `nav-icons.tsx`-Muster (`Icon`-Wrapper mit `viewBox`, `strokeWidth`, fixer Grösse) um ein Action-Icon-Set erweitern (`PencilIcon`, `TrashIcon`, `XIcon`, `PlusIcon`, `CopyIcon` — Basis: bereits vorhandene SVGs in `modal.tsx`/`search-input.tsx`/`copy-field.tsx` konsolidieren statt neu zeichnen) und alle 6 Unicode-Stellen plus die Duplikate in den 29 Dateien schrittweise darauf migrieren
- Aufwand: medium (Icon-Set bauen: small; Migration aller Fundstellen: medium, da schrittweise über viele Dateien)

**Icon-Only ohne Tooltip/aria-label:** siehe Accessibility-Abschnitt — direkt daraus folgend, weil Unicode-Zeichen ohne begleitende `ActionMenu`-Infrastruktur leichter vergessen werden.

## Terminology Inconsistencies

| Bedeutung | Vorkommen | Beispieldateien |
|---|---|---|
| Datensatz endgültig löschen (Button/Menü-Label) | „Löschen“ (Mehrheit) | `admin-tenant-management.tsx:394`, `protocol-builder.tsx:338`, `finances-view.tsx:308` |
| | „Entfernen“ | `admin-domain-overview.tsx:127`, `tenant-domains-manager.tsx:81` (Domain-Löschung ist ebenso endgültig wie eine Mandanten-Löschung, bekommt aber ein anderes Wort) |
| Bestätigungsfrage vor destruktiver Aktion | „X endgültig löschen? Dies kann nicht rückgängig gemacht werden.“ | `participant-manager.tsx:243`, `list-manager.tsx:276`, `event-manager.tsx:506`, `protocol-editor.tsx:1115/1178/1465` |
| | „X wirklich löschen?“ | `submission-assignment-manager.tsx:459`, `security/mfa-admin-modal.tsx:53`, `admin-user-management.tsx:172` |
| | „X löschen?“ (ohne Verstärkung) | `fines-view.tsx:117`, `finances-view.tsx:136/191`, `todo-edit-modal.tsx:49`, `matrix-embedded-block-editor.tsx:337/612/1088` |
| Geteilten Link ungültig machen | „Widerrufen“ | `shared-links-view.tsx:43` |
| | „Entfernen“ | `album-share-modal.tsx:144,274` (gleiche Handlung: einen bestehenden Freigabe-/Teilen-Zugriff beenden) |
| Zurück-Navigation | „Zurück zu Protokollen“ | `protocol-editor.tsx:1586` |
| | „Zurück zu den Protokollen“ | `protocol-editor.tsx:1984` (gleiche Datei, gleiches Ziel) |

**UI Vocabulary / Terminology Dictionary (Empfehlung):**

| Bedeutung | Standardbegriff | Nicht mehr verwenden |
|---|---|---|
| Datensatz unwiderruflich entfernen | Löschen | Entfernen (ausser bei echtem „aus Liste/Ansicht entfernen ohne Datenverlust“, z. B. `list-manager.tsx:380/405`) |
| Bestätigungsfrage vor destruktiver Aktion | „<Objekt> endgültig löschen? Dies kann nicht rückgängig gemacht werden.“ (bzw. objektspezifische Konsequenz statt des Nachsatzes, wenn es eine wichtigere Folge gibt, wie bei `admin-tenant-management.tsx:250`) | „wirklich löschen?“, „löschen?“ ohne Verstärkung |
| Freigabe/Teilen-Zugriff beenden | Widerrufen | Entfernen |
| Zurücknavigation zu einer Übersicht | Einheitlicher, pro Zielseite fixer String, über `topbar-breadcrumb` statt Freitext | abweichende Formulierungen derselben Zielseite |
| Bearbeiten (Icon-only) | Pencil-Icon aus neuem Action-Icon-Set + `aria-label="Bearbeiten"` | „✎“, eigene Inline-SVGs |
| Löschen (Icon-only) | Trash-Icon aus neuem Action-Icon-Set + `aria-label="Löschen"` | „✕“ für Löschen (✕ bleibt reserviert für „Schliessen“, vgl. `Modal`) |

*(Die weiteren Begriffspaare aus dem Auftrag — User/Account/Profile, Project/Workspace, Preferences/Settings — konnten nicht als reale Konflikte bestätigt werden: hocX verwendet konsistent „Benutzer“ für Accounts, „Mandant“ für den Tenant-Begriff, und es gibt keine zwei konkurrierenden Begriffe für „Einstellungen“ — `tenant-settings` heisst durchgängig „Einstellungen“/„Mandant-Einstellungen“, `settings/document-template-manager.tsx` ist Teil desselben Einstellungsbereichs. Das ist positiv und sollte so bleiben.)*

## Form Inconsistencies

- **Feldstruktur ist konsistent:** `.field-stack` + `.field-label` wird flächendeckend verwendet, keine Abweichungen bei Stichproben in `template-builder.tsx`, `finances-view.tsx`, `cycle-config-manager.tsx`, `document-template-manager.tsx` gefunden.
- **Button-Reihenfolge in `modal-actions`:** in den Stichproben (`template-builder.tsx`, `cycle-config-manager.tsx`, `list-manager.tsx`) korrekt Abbrechen → Speichern, rechtsbündig — kein Verstoss gefunden.
- **Pflichtfeld-Validierung über `disabled`** wird konsistent eingesetzt, keine Gegenbeispiele mit Inline-Fehlertext gefunden (passt zu `useConfirm`/`useToast`-Disziplin).
- **Inline-Style statt Klasse für statischen Abstand:** `abgabebox-frontend/components/upload-form.tsx:210` — `style={{ marginTop: "var(--space-4)" }}` auf einem Button. Der Wert selbst ist ein korrektes Token, aber `DESIGN.md` §1.5 verlangt Klasse statt Inline-Style für wiederkehrende, nicht laufzeit-abhängige Optik. In `abgabebox-frontend` gibt es kein Äquivalent zu `frontend/app/globals.css`-Klassen für diesen Fall, weil die App kein eigenes Muster für sekundäre Bestätigungs-Buttons mit Abstand zum vorherigen Element hat.
  - Empfehlung: eigene Klasse (z. B. `.upload-again-button`) mit `margin-top: var(--space-4)` in `abgabebox-frontend/app/globals.css`.
  - Aufwand: small.

## Table/List Inconsistencies

- `DataTable` wird in 20 Dateien verwendet und ist die dominante, korrekte Wahl. Keine eigenen `<table>`-Nachbauten in den Stichproben gefunden (`files-table.tsx`, `structured-list-table.tsx` bauen auf `DataTable` bzw. nutzen das gemeinsame Zellen-CSS).
- **Zeilenaktionen-Schema weicht in Finanzen ab:** `finances-view.tsx` zeigt Zeilenaktionen nicht in einer `DataTable`, sondern in eigenen `finance-account-card`/`finance-tx-*`-Listenzeilen (kein `<table>`, sondern Card-/Flex-Listen). Das ist an sich vertretbar (Konto-Übersicht ist keine klassische Tabelle), aber die zwei Icon-Buttons darin (`✎`/`✕`) folgen nicht dem sonst für 2 Zeilenaktionen etablierten Muster aus `DESIGN.md` §8 (`button-danger` für Löschen, `button-secondary`/`button-icon-soft` sonst — hier fehlt die Klasse `button-icon-soft` nicht, aber Icon und `aria-label` weichen ab, siehe oben).
- **Bulk-Aktionen nur bei Teilnehmern:** `participant-manager.tsx:329-336` hat eine „Auswahl löschen“-Bulk-Aktion mit Checkbox-Selektion; kein anderes untersuchtes `DataTable` (Todos, Termine, Dateien, Benutzer) bietet Mehrfachauswahl, obwohl Löschen in Bulk dort ähnlich sinnvoll wäre (z. B. Todos). Das ist eher eine Funktionslücke als eine Inkonsistenz im engeren Sinn — nur erwähnt, weil der Nutzer, der Bulk-Löschen bei Teilnehmern gelernt hat, es andernorts vermissen könnte.

## Interaction Inconsistencies

- **Löschen-Bestätigung:** durchgängig über `useConfirm({ tone: "danger" })`, keine Abweichung gefunden — das Verhalten selbst ist vorbildlich konsistent, nur der Text variiert (siehe Terminology).
- **Reine Auswahl-Popups** (`DESIGN.md` §8, Vorbild `CheckboxCandidateModal`): `checkbox-candidate-modal.tsx` folgt der Regel „jeder Klick speichert sofort, kein Übernehmen-Button“ korrekt; keine gegenteiligen Funde in Stichproben von `album-photo-picker.tsx`.
- **Back-Link vs. Breadcrumb**, siehe oben unter Page-Layout — ist auch ein Interaktionsbruch: Klick auf Browser-Zurück vs. Klick auf `<a>` mit vollem Reload verhalten sich unterschiedlich (State-Verlust bei `<a>`, kein State-Verlust bei echter Client-Navigation).

## Responsive Inconsistencies

`DESIGN.md` erlaubt ausschliesslich die Breakpoints 640px/900px, keine eigenen `@media`-Regeln — der Linter erzwingt das bereits, und `check-design-rules.py` meldet aktuell keine Verstösse. Für eine vollständige visuelle Verifikation (abgeschnittene Buttons, Wrapping, horizontaler Overflow) wäre ein Playwright-Lauf gegen den E2E-Stack bei 1440px/390px nötig (`./scripts/e2e.sh up`, dann Light/Dark-Screenshots) — das wurde in diesem reinen Code-Audit bewusst nicht ausgeführt, da Abschnitt 17 des Auftrags noch keine Änderungen/keine zusätzliche Infrastruktur-Nutzung vorsieht. Empfehlung: als eigenen Schritt vor Phase 5 der Migration nachholen (siehe unten).

## Accessibility Problems

- **`finances-view.tsx:282,307,308,405,406`**: fünf Icon-only-Buttons mit `title=`, aber **ohne `aria-label`** — direkter Verstoss gegen `DESIGN.md` §9 („Icon-Buttons haben `aria-label`“). Vergleich: `action-menu.tsx:18` setzt beides (`title={ariaLabel} aria-label={ariaLabel}`) korrekt.
  - Aufwand: small (5 Attribute ergänzen).
- **Breadcrumb ohne `aria-label` in der Hauptapp:** `admin-shell.tsx:213` setzt `aria-label="Brotkrumen"` auf die `<nav>`, `app-shell.tsx:326` (Hauptapp-Breadcrumb) hat in der untersuchten Stelle kein äquivalentes `aria-label` auf dem umgebenden Element.
  - Datei: `frontend/components/ui/app-shell.tsx:326`
  - Vergleich: `frontend/components/ui/admin-shell.tsx:213`
  - Problem: Screenreader-Nutzer bekommen in der Plattform-Admin-Oberfläche eine benannte Breadcrumb-Landmark, in der Hauptapp nicht
  - Empfehlung: `aria-label="Brotkrumen"` (oder äquivalent) ergänzen
  - Aufwand: small
- Ansonsten: `Modal` erzwingt zentral Titel + Fokusverhalten, `ActionMenu` setzt `aria-label` korrekt, keine weiteren `outline: none`-ohne-Ersatz-Stellen in den Stichproben gefunden.

## Duplicate Components

- **Icon-System:** siehe „Icon Inconsistencies“ — `nav-icons.tsx` deckt nur Sidebar ab, 29 Dateien bauen eigene `<svg>`, 6 Dateien nutzen rohe Unicode-Zeichen für dieselben generischen Aktionen (Bearbeiten/Löschen/Schliessen/Plus).
- **Dropdown-/Kebab-Menü:** `ActionMenu` (offizieller Baustein, 8 Verwendungen) vs. `mini-menu`-Klassenfamilie in `event-manager.tsx:661` (nicht in `DESIGN.md` §4 dokumentiert).
- **Header-Aktionsleisten-Wrapper:** `table-toolbar-actions` (5×) vs. `page-header-actions` (1×) vs. `subm-toolbar-actions` (1×) für dieselbe Rolle.
- **Button-Klassenkombination `button-secondary button-ghost`:** 3 Fundstellen (`participant-manager.tsx:325`, `event-manager.tsx:653`, `todo-list-view.tsx:410`), nicht in `DESIGN.md` §7 als eigene, offizielle Kombination benannt — entweder dokumentieren oder vereinheitlichen.

## Design Token Problems

Keine gefunden, die der bestehende Checker nicht ohnehin schon verhindert — `check-design-rules.py` meldet `ok`, und die Stichproben-Dateien (`finances-view.tsx`, `abgabebox-frontend/components/upload-form.tsx`, `event-manager.tsx`) enthalten keine Hex-Farben, undefinierten Variablen oder Radius-/Schrift-/z-index-Literale. Der einzige Token-nahe Fund ist der Inline-Style mit korrektem Token-Wert in `abgabebox-frontend/components/upload-form.tsx:210` (siehe Form Inconsistencies) — kein Token-*Wert*-Problem, sondern ein Klasse-vs-Inline-Style-Problem.

## Recommended Design Rules

```
RULE-001
Die eine Hauptaktion einer Seite/eines Modals ist immer button-primary — auch wenn die Seite
aktuell nicht leer ist. EmptyState- und gefüllter Zustand derselben Seite verwenden für dieselbe
Aktion immer dieselbe Klasse.

RULE-002
Icon-only-Aktionen für Bearbeiten/Löschen/Schliessen/Kopieren/Plus verwenden ausschliesslich das
gemeinsame Action-Icon-Set (SVG, wie nav-icons.tsx), nie rohe Unicode-Zeichen (✎ ✕ ＋ u. ä.) und
keine neu gezeichneten Inline-SVGs für bereits abgedeckte Bedeutungen.

RULE-003
Jedes Icon-only-Element hat gleichzeitig title und aria-label mit demselben Text (Vorbild:
action-menu.tsx).

RULE-004
Ein endgültiger, unwiderruflicher Löschvorgang heisst immer "Löschen" (Button/Menü-Label) und die
Bestätigung lautet immer "<Objekt> endgültig löschen? Dies kann nicht rückgängig gemacht werden."
(oder ein objektspezifischer Nachsatz statt des Standardsatzes, wenn die Konsequenz wichtiger zu
kommunizieren ist als die Endgültigkeit selbst). "Entfernen" ist reserviert für Aktionen, die
Daten NICHT löschen, sondern nur aus einer Ansicht/Zuordnung nehmen.

RULE-005
Objekt-Aktionsmenüs (mehr als 2 Zeilenaktionen) verwenden ausschliesslich ActionMenu, nie eine
eigene mini-menu-o.ä.-Klassenfamilie.

RULE-006
Der Wrapper für Aktionen im page-header heisst immer table-toolbar-actions, unabhängig vom
Seitentyp.

RULE-007
Jede Seite unter frontend/app/**/page.tsx, die sichtbaren Text rendert, ist auf Deutsch. Seiten,
deren Kopfbereich mehr als reines Daten-Fetching enthält (wie ein h1 mit Beschreibungstext),
delegieren den Kopfbereich an eine Komponente in components/ mit dem üblichen
page-header/page-title-Aufbau statt eigenen Markups direkt in page.tsx.

RULE-008
Zurück-Navigation zu einer Listen-/Übersichtsseite nutzt die vorhandene Breadcrumb-Komponente
(topbar-breadcrumb) statt eines frei formulierten Text-Links; wo das (noch) nicht möglich ist,
ist der Linktext pro Zielseite exakt einmal im Code definiert (z. B. als Konstante), nicht an
jeder Verwendungsstelle neu getippt.

RULE-009
Gleiche Funktion = gleiche Bezeichnung + gleiches Icon + gleiche Position + gleiches Verhalten
(übergeordnetes Prinzip aus dem Audit-Auftrag, gilt für jede neue UI-Entscheidung als Prüffrage).
```

## Recommended Component Architecture

- **`ActionIcon`-Set** (neu, in `frontend/components/ui/action-icons.tsx`, analog zu `nav-icons.tsx`s `Icon`-Wrapper): `PencilIcon`, `TrashIcon`, `XIcon`, `PlusIcon`, `CopyIcon` mindestens. Ausgangsbasis: vorhandene SVGs aus `modal.tsx` (X), `copy-field.tsx` (Copy) wiederverwenden statt neu zeichnen.
- **`table-toolbar-actions` als einziger Header-Aktions-Wrapper**, `page-header-actions` und `subm-toolbar-actions` darauf migrieren oder entfernen.
- **`ActionMenu` statt `mini-menu`**: entweder migrieren oder `mini-menu` als offiziellen, dokumentierten Zusatzbaustein in `DESIGN.md` §4 aufnehmen (Entscheidung nötig, ob es sich um einen echten zweiten Anwendungsfall handelt — Ansichts-Umschalter statt Objekt-Aktionsmenü).
- Keine neuen Modal-/Tabellen-/Formular-Komponenten nötig — die vorhandenen `Modal`/`DataTable`/`field-stack`-Bausteine sind bereits die einzige Implementierung ihrer Art und werden korrekt breit verwendet.

## UI Vocabulary

Siehe Tabelle in „Terminology Inconsistencies“ oben — hier nicht dupliziert.

## Migration Plan

### Phase 1 – High Impact / Low Risk
- RULE-001: `button-secondary` → `button-primary` auf den 7 identifizierten einzigen Kopfaktionen (`list-manager.tsx`, `user-management.tsx`, `cycle-config-manager.tsx`, `template-builder.tsx`, `element-definition-manager.tsx`, `protocol-builder.tsx`, `files-view.tsx`).
- RULE-003: 5 fehlende `aria-label` in `finances-view.tsx` ergänzen.
- `frontend/app/templates/[id]/page.tsx`: englischen Text übersetzen (schnell unabhängig von RULE-007-Refactor).
- `protocol-editor.tsx`: Zurück-Link-Text vereinheitlichen (RULE-008, kleiner Teil zuerst, volle Breadcrumb-Migration später).
- Terminologie: „Entfernen“ → „Löschen“ bei Domain-Löschung (`admin-domain-overview.tsx`, `tenant-domains-manager.tsx`, `domain-wizard-modal.tsx`), Bestätigungstexte auf die Standardformel vereinheitlichen.

### Phase 2 – Shared Components
- `ActionIcon`-Set bauen (RULE-002/003 strukturell).
- `table-toolbar-actions` als einzigen Wrapper etablieren, die zwei Abweichungen migrieren.
- Entscheidung zu `mini-menu` vs. `ActionMenu` treffen und dokumentieren oder migrieren.

### Phase 3 – Page Migration
- Alle 6 Unicode-Icon-Stellen (`✎`/`✕`/`＋`) auf `ActionIcon`-Set umstellen, inkl. `planning-icon-trigger.tsx`s Default-Prop.
- Schrittweise die 29 Dateien mit eigenen Inline-SVGs auf Deckungsgleichheit mit dem neuen Set prüfen und wo sinnvoll ersetzen (nicht alle 29 sind zwingend Duplikate — Bestandsaufnahme pro Datei nötig, manche sind produktspezifische Illustrationen statt Aktions-Icons).
- `frontend/app/templates/[id]/page.tsx` auf `page-header`/`page-title`-Struktur umstellen, Kopfbereich ggf. in eine `components/template/`-Datei auslagern (RULE-007).

### Phase 4 – Cleanup
- `abgabebox-frontend/components/upload-form.tsx:210` Inline-Style durch Klasse ersetzen.
- `button-secondary button-ghost`-Kombination entweder offiziell in `DESIGN.md` §7 dokumentieren oder durch eine Klasse ersetzen.
- Bulk-Aktionen-Lücke (nur Teilnehmer hat Mehrfachauswahl) als Produktentscheidung klären (Feature, kein reiner Cleanup) — nur aufnehmen, falls gewünscht.

### Phase 5 – Accessibility + Responsive Polish
- Fehlendes `aria-label` auf der Hauptapp-Breadcrumb ergänzen.
- Vollständige Playwright-Verifikation (Light/Dark, 1440px/390px) über `./scripts/e2e.sh up` für alle in Phase 1–3 geänderten Seiten, wie in CLAUDE.md „Prüfen“ vorgeschrieben.
- Erneuter Lauf von `python3 scripts/check-design-rules.py` nach jeder Phase.

---

**Methodischer Hinweis:** Dieser Audit basiert auf Codesuche (Kontext-Engine + gezielte `grep`/`rg`-Abfragen über die 39 Hauptapp-Routen, 11 Admin-Routen und 8 `abgabebox-frontend`-Dateien) plus Line-by-Line-Lesen von ca. 25 repräsentativen Komponenten-Dateien. Es handelt sich um eine repräsentative, keine erschöpfende Zeile-für-Zeile-Prüfung jeder einzelnen der über 39 Seiten — die vier Kernprobleme (Primärbutton, Icon-System, Löschen-Terminologie, Header-Wrapper-Klassen) wurden jedoch durchgängig an mehreren unabhängigen Stellen bestätigt und sind mit hoher Sicherheit repräsentativ für weitere, hier nicht einzeln aufgeführte Stellen im selben Muster.
