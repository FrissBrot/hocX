# hocX – Hinweise für Claude Code

Monorepo: `frontend/` (Next.js, Hauptapp + Plattform-Admin), `abgabebox-frontend/` (öffentliche Upload-Seite), `backend/` (FastAPI), `design/` (Design-Tokens und -Regeln). Sprache in UI-Texten und Kommentaren: Deutsch.

## Codebase-Navigation und Kontext

- Für Exploration und das Auffinden relevanter Implementierungen zuerst `context-engine`/CCE verwenden, statt breite `grep`-, `find`- oder Verzeichnis-Scans auszuführen.
- CCE dient zur Navigation und Kontextauswahl. Bevor Code geändert wird, die konkret betroffenen Dateien normal lesen und die tatsächliche Implementierung sowie relevante Aufrufer/Tests verstehen.
- Keine großen Dateien, Logs, Testausgaben oder Verzeichnisbäume vorsorglich vollständig einlesen. Nur den für die Aufgabe benötigten Kontext laden.
- Bestehende Implementierungen und Tests bevorzugt über CCE auffinden; `grep`/`rg` gezielt einsetzen, wenn eine exakte Textsuche sinnvoller ist.
- Tests zunächst möglichst nah an der Änderung und gezielt ausführen. Breitere Suites und E2E erst verwenden, wenn die Änderung oder Verifikation sie erfordert.

## Design-Regeln (verbindlich)

@design/DESIGN.md

Kurzfassung, falls die Datei nicht geladen wurde:

- Bei jeder UI-Änderung zuerst `design/DESIGN.md` lesen. Standardbausteine (`Modal`, `useConfirm`, `useToast`, `SearchableSelect`, `ActionMenu`, `DataTable`, `Badge`, …) statt Nachbauten. Dropdown-Entscheidungsbaum steht in Abschnitt 5, Datumsfelder (`DateInput`) in Abschnitt 6.
- Nur Tokens aus `design/tokens.css` (Farben, `--radius-*`, `--text-*`, `--space-*`, `--shadow-*`, `--z-*`, `--dur-*`). Keine Hex-Farben, keine Radius-/Schrift-/z-index-Literale, keine `var(--x, #hex)`-Fallbacks.
- Neue Optik als Klasse in `frontend/app/globals.css`, nicht als Inline-Style. Light **und** Dark prüfen.
- Tokens nur in `design/tokens.css` ändern, danach `./scripts/sync-design-tokens.sh` (die Kopien in `frontend/app/tokens.css` und `abgabebox-frontend/app/tokens.css` nie von Hand bearbeiten).
- Vor jedem Commit mit UI-Änderung: `python3 scripts/check-design-rules.py` muss `Design-Regeln: ok` melden. Ausnahmen nur mit `design-ok`-Kommentar in derselben Zeile und kurzer Begründung.

## Prüfen

Projektabhängigkeiten und Projektbefehle laufen in Containern. Auf dem Host installiertes Node/Python dient auch Dev-Tools und ist kein Grund, Frontend- oder Backend-Abhängigkeiten auf dem Host zu installieren oder Projektbefehle dorthin zu verlagern.

- Typecheck/Tests Frontend: `docker compose exec frontend node_modules/.bin/tsc --noEmit` bzw. `.../vitest run`
- E2E-Stack (eigene DB, Wegwerf-Konten): `./scripts/e2e.sh up` / `test` / `down`
- Für visuelle Vergleiche Playwright-Screenshots gegen den E2E-Stack (`mcr.microsoft.com/playwright:v1.55.0-noble`), Light/Dark, 1440 und 390 px.
- Zuerst die kleinste relevante Prüfung ausführen; vollständige Test- oder E2E-Suites nur, wenn sie für die Änderung sinnvoll sind.

## Sonstiges

- Nichts committen oder pushen, ohne dass es verlangt wurde.
- Zugangsdaten der laufenden Dev-Instanz (`.env`) nicht auslesen oder weitergeben. Für Tests den E2E-Stack nutzen.