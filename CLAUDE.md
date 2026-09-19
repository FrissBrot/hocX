# hocX

Mandantenfähige Webanwendung für Sitzungsprotokolle (Next.js 16 / React 19 Frontend, FastAPI Backend). Überblick: `README.md`, Betrieb: `RUNBOOK.md`.

## Design-Regeln (verbindlich bei jeder UI-Änderung)

@design/DESIGN.md

Kurzfassung für den Alltag:

- **Vor dem Bauen** in `design/DESIGN.md` Abschnitt 4 nachsehen: Es gibt fertige Bausteine (`Modal`, `useConfirm`, `useToast`, `Badge`, `SearchableSelect`, `ActionMenu`, `DataTable`, `FilterTabs`, `SearchInput`, `DateInput`, `TagInput` …). Nie nachbauen.
- **Nur Tokens** aus `design/tokens.css` (Farben, `--radius-*`, `--text-*`, `--space-*`, `--shadow-*`, `--z-*`, `--dur-*`). Keine Hex-Farben, keine Pixel-Radien, keine z-index-Zahlen über 5.
- **Dropdowns:** `SearchableSelect` / `ActionMenu` / `PillMenu` / natives `<select>`. Nur für Autocomplete die Klassen `.dropdown-*`. Nie mit Inline-Styles bauen.
- **Buttons:** `button-primary` (eine Hauptaktion), `button-secondary`, `button-ghost`, `button-danger`, `button-icon`, `button-icon-soft`. `button-inline` und `btn-icon*` gibt es nicht mehr.
- **Beide Themes** (Light/Dark) und **Smartphone (390 px)** prüfen.
- **Vor jedem Commit:** `python3 scripts/check-design-rules.py` (muss `Design-Regeln: ok` melden, läuft auch in der CI).
- **Tokens ändern:** nur in `design/tokens.css`, dann `./scripts/sync-design-tokens.sh`. Die Kopien `frontend/app/tokens.css` und `abgabebox-frontend/app/tokens.css` nie von Hand bearbeiten.

## Umgebung

- Node/npm sind auf dem Host **nicht** installiert. Typecheck, Tests und Builds laufen im Docker-Container (`hocx-dev-frontend`) oder per `docker run` mit dem Image `hocx-dev-frontend:latest`.
- Sichtprüfung: E2E-Stack mit `./scripts/e2e.sh up` (Ports 13000/13001), Testdaten und Login siehe `frontend/e2e/auth.setup.ts`. Danach `./scripts/e2e.sh down`.
- Keine Zugangsdaten aus `.env` oder der laufenden Dev-Instanz für Tests verwenden.
