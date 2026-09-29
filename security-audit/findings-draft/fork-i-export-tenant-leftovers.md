# Fork I — Export-Regression + Restliche Tenant-Isolation-Callsites

Scope: (1) Regression-Check der 7 historischen Cross-Tenant-PDF-Export-Findings in
`export_service.py` + Rollen-/Tenant-Scoping in `statistics.py`/`exports.py` + LaTeX-Escaping
des Rich-Text-Inhalts; (2) `participant_service.py:137` + `ProtocolImage`/`ProtocolText`/
`ProtocolDisplaySnapshot`-Callsites ausserhalb `files.py`. Keine Codeänderungen, keine Commits.

## Ergebnis: keine neuen Findings — alle Kandidaten geprüft und widerlegt

### EXP-01 — Cross-Tenant-Export-Fixes (2026-08-25): alle 7 Stellen halten stand

Status: FALSE_POSITIVE (Regression nicht bestätigt — Fixes sind intakt)

Geprüfte Stellen in `backend/app/services/export_service.py`:

| Zeile | Funktion | Client-gelieferte ID | Tenant-Check vorhanden? |
|---|---|---|---|
| 1371-1389 | `_finance_balance_content` | `finance_account_id` | ✅ `account.tenant_id != tenant_id` |
| 1391-1398 | `_finance_transactions_content` | `finance_account_id` | ✅ (gleicher Check) |
| 1458-1484 | `_form_row_value` | `participant_id(s)`/`event_id` | ✅ je `.tenant_id == tenant_id`-Filter |
| 1501-1519 | `_form_row_list_entry_label_and_value` (Fallback-Pfad) | `linked_list_id`/`linked_list_entry_id` | ✅ `definition.tenant_id != tenant_id` |
| 1598-1606 | `_linked_list_content` (Standalone-Export) | `list_definition_id` | ✅ `definition.tenant_id != tenant_id` |
| 2020-2039 | `_matrix_single_value` | `participant_id(s)`/`event_id` in Matrix-Zelle | ✅ je `.tenant_id == protocol.tenant_id` |
| 2259-2278 | `_store_generated_file` (SHA-256-Kommentar) | n/a — Doku-Hinweis, kein offener Bug | n/a, bereits als akzeptiert dokumentiert |
| 2279-2290 | (Orphan-File-Kommentar) | n/a — beschreibt Restrisiko, das durch `cleanup_old_generated_exports`-Sweep bereits abgefangen wird | n/a, bereits als akzeptiert dokumentiert |

Alle 5 aktiven Tenant-Checks sind vorhanden und korrekt. Die beiden übrigen Kommentare (2273,
2285) beschreiben bereits akzeptierte Nicht-Sicherheits-Alt-Findings (fehlender Checksum bei
Erst-Erstellung — inzwischen behoben, siehe `checksum_sha256=hashlib.sha256(...)` in Zeile 2276;
Orphan-File-Risiko — durch Retention-Sweep gemildert), keine offene Lücke.

### EXP-02 — `statistics.py`/`exports.py`: Rollen/Tenant-Scoping korrekt

Status: FALSE_POSITIVE (kein Fund)

- `statistics.py::get_statistics_overview`: `require_reader(user)`, JEDE Query filtert explizit
  nach `tenant_id = user.current_tenant_id` (Protocols, CycleConfigs, Attendance, Todos, Fines,
  Finance, Participants). Kein client-gelieferter Fremdschlüssel ungefiltert übernommen.
- `exports.py` (alle 8 Routen): einheitliches Muster über `_resolve()`-Helper
  (`public_id_service.resolve_internal_id(db, Model, public_id, tenant_id=user.current_tenant_id)`
  → 404 bei Miss) für JEDE client-gelieferte ID (`protocol_id`, `template_id`, `participant_id`,
  `list_definition_id`, `filter_event_id`), zusätzlich `access_service.ensure_can_read_protocol`
  wo relevant. `export_latex` bewusst mit `require_admin` (härter als die übrigen `require_reader`
  PDF-Exports) — nachvollziehbare, keine schwächere Prüfung. `record_system_error(...) from exc`
  korrekt verkettet in jedem `except (SQLAlchemyError, RuntimeError)`-Block (CLAUDE.md-Konvention
  eingehalten).

### EXP-03 — LaTeX-Escaping des Rich-Text/Markdown-Inhalts: robust, kein Injection-Vektor

Status: FALSE_POSITIVE (kein Fund)

`_escape_latex()` (`export_service.py:2315-2330`) escaped in einem Single-Pass-Zeichen-Mapping
u. a. `\`, `%`, `$`, `#`, `_`, `{`, `}`, `&`, `~`, `^` — inklusive der für `\input{}`/`\include{}`
nötigen Zeichen `\`, `{`, `}`. `_markdown_to_latex`/`_inline_markdown_to_latex` routen JEDEN
Klartextabschnitt durch `_escape_latex`, bevor er in den generierten LaTeX-Quelltext eingefügt
wird — ein Nutzer, der `\input{/etc/passwd}` in den Rich-Text-Editor tippt, bekommt im PDF
buchstäblich `\textbackslash{}input\{/etc/passwd\}` angezeigt, kein ausführbares LaTeX-Kommando.
Kombiniert mit den von Fork C bereits verifizierten `-no-shell-escape`/`openin_any=p`/
`openout_any=p`-Flags (zweite Verteidigungslinie) ist LaTeX-Injection über Rich-Text-Inhalt nicht
möglich. Auch die Frage "wird der Export von anderen Usern/Tenants ausgelöst" ist irrelevant, da
ohnehin kein Injection-Vektor besteht.

### TEN-03 — `participant_service.py:137`: korrekt abgesichert

Status: FALSE_POSITIVE (kein Fund)

`create_participant()` ruft `resolve_internal_id(db, AppUser, payload.app_user_id)` ohne
`tenant_id=`, aber die UNMITTELBAR nächste Zeile (140) ruft
`self._ensure_app_user_belongs_to_tenant(db, app_user_id, tenant_id=tenant_id)`, das
`app_user.tenant_id != tenant_id` prüft und mit 400 abbricht. Identisches Muster zu allen von
Fork A bereits verifizierten Stellen.

### TEN-04 — `ProtocolImage`/`ProtocolText`/`ProtocolDisplaySnapshot` ausserhalb `files.py`: kein direkter Client-Resolve-Pfad gefunden

Status: FALSE_POSITIVE (kein Fund — Sorge war unbegründet)

Repo-weiter Grep über alle drei Modelle (ausserhalb `files.py`/`models/`) zeigt: **keine** Route
oder Service-Funktion ruft `public_id_service.get_by_public_id`/`resolve_internal_id` mit einem
dieser drei Modelle UND einer client-gelieferten `public_id` auf. Alle Vorkommen sind entweder:
- interne Joins über bereits tenant-verifizierte `protocol_element_block_id`
  (`access_repository.py`, `export_repository.py`, `file_repository.py`-interne Queries,
  `protocol_service.py`, `autosave_service.py`, `word_import_service.py`),
- Tenant-Admin-Operationen auf Gesamt-Tenant-Ebene (`tenant_export_service.py`,
  `tenant_clone_service.py`, `tenant_import_service.py`, `tenant_cleanup_service.py`) — diese
  operieren ohnehin auf dem gesamten, bereits als Einheit autorisierten Tenant, kein
  Einzelobjekt-IDOR-Risiko,
- der bereits als TEN-01 dokumentierte tote Code (`file_repository.py::ProtocolImageRepository.
  get_by_public_id`, Zeile 566-571) — kein zusätzlicher Fund, deckt sich mit Fork A.

## Fazit

Beide Teilaufgaben ergeben **keine neuen Findings**. Die 7 historischen Cross-Tenant-Export-Fixes
sind intakt, `statistics.py`/`exports.py` sind sauber gescoped, LaTeX-Escaping ist robust, und die
verbliebenen Tenant-Isolation-Zweifel aus Fork A (`participant_service.py:137`,
`ProtocolImage`/`ProtocolText`/`ProtocolDisplaySnapshot`) bestätigen sich nicht als Lücke.

Status-Update `security-audit/components/backend.md`: Abschnitt "Phase 3 Fork I" ergänzt,
keine neuen Findings.
