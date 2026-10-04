# hocX – Hinweise für Claude Code

Monorepo: `frontend/` (Next.js, Hauptapp + Plattform-Admin), `abgabebox-frontend/` (öffentliche Upload-Seite), `backend/` (FastAPI), `design/` (Design-Tokens und -Regeln). Kommentare und Entwicklerdokumentation: Deutsch. UI-Texte: siehe Abschnitt „Internationalisierung / i18n" unten — hocX ist mehrsprachig, kein UI-Text wird mehr direkt auf Deutsch in Komponenten geschrieben.

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

## Internationalisierung / i18n – VERBINDLICH

hocX ist eine mehrsprachige Anwendung (next-intl, ohne URL-Locale-Routing). Die aktuell unterstützten
Sprachen werden **ausschliesslich** aus `i18n/locales.json` bestimmt (Default: `de`) — generiert via
`python3 scripts/sync-i18n-config.py` nach `frontend/i18n/locale-config.generated.ts`,
`abgabebox-frontend/i18n/locale-config.generated.ts` und `backend/app/core/locale_config_generated.py`
(analog zu `design/tokens.css` + `sync-design-tokens.sh`: Quelle einmal ändern, Sync-Skript laufen
lassen, generierte Dateien nie von Hand editieren). Eine Sprachliste wie `["de", "en", "fr", "it"]`
darf an **keiner weiteren Stelle** im Code auftauchen — CI, Tests, Language Selector und
Backend-Validierung lesen immer aus dieser generierten Konfiguration.

Verbindliche Regeln:

1. Kein neuer benutzersichtbarer UI-Text wird direkt in React-/TSX-Komponenten geschrieben.
   Jeder neue Text braucht einen semantischen Translation Key (`participants.delete.confirmTitle`,
   nicht `text1`) in `frontend/messages/<locale>/<namespace>.json` bzw.
   `abgabebox-frontend/messages/<locale>/<namespace>.json`.
2. Bei jeder neuen Funktion/UI-Änderung müssen im selben Change Übersetzungen für **alle** aktuell
   registrierten Sprachen ergänzt werden (`python3 scripts/check-i18n-completeness.py` muss „ok"
   melden) — auch wenn der Auftrag Mehrsprachigkeit nicht ausdrücklich erwähnt. Eine UI-Aufgabe gilt
   nicht als abgeschlossen, solange Übersetzungen fehlen.
3. Client-Komponenten: `useTranslations("<namespace>")` aus `next-intl`. Async Server Components
   (`page.tsx` ohne `"use client"`): `getTranslations("<namespace>")` aus `next-intl/server`. Reine
   Hilfsfunktionen/Modul-Konstanten ohne eigene Komponente (z.B. `section-tabs.ts`) nehmen `t` als
   Parameter entgegen, statt selbst einen Hook aufzurufen — siehe `app-shell-nav.ts::formatRoleLabel`
   und `section-tabs.ts` als Vorbild.
4. Variablen und Pluralisierung immer über ICU-Syntax (`t("key", { count })` mit
   `"{count, plural, one {...} other {...}}"`), nie String-Konkatenation.
5. Datum/Zeit/Zahlen: `formatDateTime`/`formatTime`/`formatWeekdayDate`/`formatRappen` aus
   `frontend/lib/utils/format.ts` nehmen optional die aktuelle UI-Locale (`useLocale()`) entgegen.
   Ausnahme bewusst: `formatDate`/`formatDateInputValue`/`DateInput` bleiben **immer** `TT.MM.JJJJ`
   (siehe `design/DESIGN.md` Abschnitt 6 — das ist ein festes Eingabeformat, keine Sprachfrage).
6. Sprachauswahl persistiert für eingeloggte Nutzer in `app_user.preferred_language` (Pydantic-
   validiert gegen die zentrale Locale-Liste, siehe `backend/app/schemas/user.py`) und wird bei
   Login/Session-Abruf/Self-Update serverseitig in den Cookie `hocx_locale` gespiegelt
   (`issue_locale_cookie` in `backend/app/core/security.py`) — Priorität bei der Ermittlung:
   gespeicherte Präferenz → Cookie → Browser-Sprache → Default. Eine unbekannte/nicht unterstützte
   Locale fällt immer auf `de` zurück, bricht nie die Anwendung.
7. Prüfungen vor Abschluss jeder UI-Aufgabe (siehe auch Abschnitt „Prüfen" unten):
   `python3 scripts/check-i18n-completeness.py`, `python3 scripts/check-i18n-hardcoded-text.py`
   und `python3 scripts/check-i18n-key-resolution.py` müssen „ok" melden. Ein echter Fund im
   Hardcoded-Text-Check wird übersetzt; ein False Positive (kein UI-Text) wird mit
   `// i18n-ok: <Begründung>` in derselben Zeile markiert. Completeness/Hardcoded-Text prüfen nur
   Key-Parität zwischen Locales bzw. hartcodierten Text — ein `t("key")`-Aufruf, der syntaktisch
   korrekt aussieht, aber den falschen Namespace oder einen nicht existierenden Key trifft (z. B.
   `useTranslations("nav")` gefolgt von `t("breadcrumbNav")`, obwohl der Key in `common.json`
   liegt), fällt erst zur Laufzeit mit next-intls `MISSING_MESSAGE` auf — das deckt
   `check-i18n-key-resolution.py` ab, mit der bekannten Grenze, dass mehrstufige
   Parameter-Weiterleitung (TFunc-Muster, siehe unten) nicht immer statisch auflösbar ist; solche
   Fälle werden übersprungen statt geraten, nie als Fehlalarm gemeldet.
8. Neue Sprache hinzufügen: ausschliesslich `i18n/locales.json` ergänzen, `sync-i18n-config.py`
   laufen lassen, dann für jeden registrierten Namespace eine `messages/<neue-locale>/<namespace>.json`
   anlegen. Language Selector, CI und Tests erkennen sie danach automatisch — kein Code in
   Komponenten, CI-Workflows oder Testdateien wird dafür angepasst.
9. Bei UI-Reviews explizit auf i18n-Vollständigkeit achten (fehlende Keys, hart codierte Strings,
   fehlende Pluralregeln).

## Zentrale Fehlererfassung (verbindlich)

Unerwartete Backend-Fehler laufen in `system_error_log` zusammen und werden ausschliesslich im Platform-Admin-Panel angezeigt (`backend/app/core/error_log.py`, Tabelle `system_error_log`; für `abgabebox-backend` analog über `insert_error_log` in `abgabebox-backend/app/repository.py`). Das passiert **automatisch**, aber nur solange der folgende Kettenmechanismus nicht unterbrochen wird:

- Der globale `Exception`-Handler in `main.py` fängt alles, was eine Route nicht selbst behandelt hat, und loggt es (Sicherheitsnetz).
- Der globale `HTTPException`-Handler loggt zusätzlich jede Route, die eine unerwartete Exception abfängt und als `raise HTTPException(status_code=..., detail="<kuratierte Meldung>") from exc` weiterwirft — er prüft `exc.__cause__`. **Ohne `from exc` (bzw. `from e`) ist `__cause__` immer `None` und der Fehler verschwindet spurlos**, obwohl die Response unverändert aussieht. Das ist der häufigste Bugtyp hier: beim Refactoring von `except ...: raise HTTPException(...)` das `from exc` zu vergessen.
- `ValueError` ist die Konvention für bereits kuratierte, erwartete Validierungsfehler und wird bewusst NICHT geloggt — nur andere Exception-Typen zählen als „unerwarteter Fehler“.

Beim Schreiben oder Ändern von Backend-Code (Routen, Services) gilt deshalb:

1. Jedes neue/geänderte `except Exception as exc: raise HTTPException(...)` bekommt **immer** `from exc` (nie nacktes `raise HTTPException(...)`, nie `raise HTTPException(...) from None`, ausser der Fehler ist wirklich erwartet/kuratiert).
2. Code, der **ausserhalb** eines HTTP-Request/Response-Zyklus läuft — Background-Loops (`app/core/background_loops.py`, `abgabebox-backend/app/main.py::quarantine_cleanup_loop`), WebSocket-Handler (`collaboration_ws.py`), Queue-/Batch-Worker, `asyncio.create_task`, Startup/Lifespan-Tasks — wird von den globalen Handlern **nicht** erreicht (Starlettes `ExceptionMiddleware`, die `@app.exception_handler` trägt, greift nur im `http`-Scope, nie bei WebSockets oder Tasks ausserhalb eines Requests). Dort muss jeder `except Exception`-Block, der den Fehler nicht weiterwirft, ihn explizit selbst loggen: `record_system_error(db, exc=exc, tenant_id=..., actor_email=...)` in `backend/`, `insert_error_log(db, tenant_id=None, request_method=None, request_path=None, status_code=None, ...)` in `abgabebox-backend/` (Muster siehe `background_loops.py`, `collaboration_ws.py::_record_ws_error`, `abgabebox-backend/app/main.py::_record_background_error`).
3. **`source` nie selbst überschreiben.** `system_error_log.source` hat ein DB-`CHECK` (`ck_system_error_log_source`, siehe `sql/baseline_schema.sql`), das nur `"backend"` und `"abgabebox-backend"` erlaubt — genau die zwei Werte, die die Frontend-Filterliste (`admin-error-log.tsx`, `SOURCE_LABELS`) kennt. `record_system_error(...)`/`insert_error_log(...)` immer mit dem Default aufrufen, nie ein drittes `source=` erfinden (z. B. `"background_loop"`): ein abweichender Wert lässt den `INSERT` an der `CHECK`-Constraint scheitern, was `record_system_error` selbst abfängt (rollback + nur `logger.exception`) — der Fehler verschwindet dann für den Aufrufer unsichtbar ein zweites Mal, obwohl der Code "sich richtig anfühlt". Genau dieser Bug (`source="background_loop"` in `background_loops.py`) war die Hauptursache dafür, dass sämtliche Wartungs-Loop-Fehler nie in der Admin-Page ankamen — bei jeder neuen `source=`-Angabe zuerst die Constraint in `sql/baseline_schema.sql` prüfen, nicht raten.
4. Ein `except Exception`-Block, der eine Exception **schluckt** (nur `logger.exception(...)`, `pass`, oder in eine Ergebnisliste/Toast-Text umwandelt, ohne erneut zu raisen) — auch innerhalb eines Requests — verliert den Fehler ebenfalls für `system_error_log`. Sofern es sich nicht um einen bewusst harmlosen Best-Effort-Fall handelt (z. B. optionale EXIF-Metadaten, DNS-Lookup mit Fallback), zusätzlich `record_system_error(...)`/`insert_error_log(...)` aufrufen.
5. Nach jeder Änderung an einem `except Exception`-Block in `backend/`/`abgabebox-backend/` kurz gegenprüfen: landet ein hier auftretender, bislang unbekannter Fehler tatsächlich in `system_error_log` (inkl. eines Blicks auf den tatsächlich verwendeten `source`-Wert), oder wird die Kette (raise mit `from exc` / expliziter Logging-Call / Constraint) unterbrochen?

## Prüfen

Projektabhängigkeiten und Projektbefehle laufen in Containern. Auf dem Host installiertes Node/Python dient auch Dev-Tools und ist kein Grund, Frontend- oder Backend-Abhängigkeiten auf dem Host zu installieren oder Projektbefehle dorthin zu verlagern.

- Typecheck/Tests Frontend: `docker compose exec frontend node_modules/.bin/tsc --noEmit` bzw. `.../vitest run`
- i18n (vor jedem Commit mit UI-Änderung): `python3 scripts/check-i18n-completeness.py`, `python3 scripts/check-i18n-hardcoded-text.py` und `python3 scripts/check-i18n-key-resolution.py`, nach jeder Änderung an `i18n/locales.json` zusätzlich `python3 scripts/sync-i18n-config.py`
- E2E-Stack (eigene DB, Wegwerf-Konten): `./scripts/e2e.sh up` / `test` / `down`
- Für visuelle Vergleiche Playwright-Screenshots gegen den E2E-Stack (`mcr.microsoft.com/playwright:v1.55.0-noble`), Light/Dark, 1440 und 390 px.
- Zuerst die kleinste relevante Prüfung ausführen; vollständige Test- oder E2E-Suites nur, wenn sie für die Änderung sinnvoll sind.

## Sonstiges

- Nichts committen oder pushen, ohne dass es verlangt wurde.
- Zugangsdaten der laufenden Dev-Instanz (`.env`) nicht auslesen oder weitergeben. Für Tests den E2E-Stack nutzen.