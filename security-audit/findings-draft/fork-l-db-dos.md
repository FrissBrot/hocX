# Fork L — DB-Constraints (Abschnitt 18/19) + Denial-of-Service-Sweep (Abschnitt 22)

Scope: `backend/sql/baseline_schema.sql`, Migrationen `0090`-`0096`, Pagination/Regex/Concurrency-
Grep über `backend/app`. Keine Codeänderungen, keine Commits.

## Ergebnis: 0 neue Findings

## Teil 1 — DB-Constraints

- **`tenant_id` NOT NULL + FK CASCADE**: für alle geprüften tenant-gescopten Tabellen vorhanden
  (`event`, `protocol`, `stored_file`, `participant`, `list_definition`, `finance_account`,
  `template`, `submission_assignment`, `word_import_document`, u. a. — durchgehend
  `FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE`). Nullable `tenant_id`
  existiert nur dort, wo es fachlich korrekt ist (`audit_log.tenant_id` mit `ON DELETE SET NULL`
  — ein Log-Eintrag soll einen gelöschten Tenant überleben; `system_error_log.tenant_id` analog;
  `document_template`/`cycle_config` nullable aus historischen Gründen, aber ausserhalb des
  Kern-Scopes dieses Forks — keine Sicherheitsrelevanz identifiziert, da Zugriff über
  `access_service`/Route-Ebene ohnehin tenant-geprüft wird, nicht über NULL-Semantik).
- **`system_error_log.source` CHECK-Constraint**: exakt `CHECK (source = ANY (ARRAY['backend',
  'abgabebox-backend']))` — bestätigt konsistent mit CLAUDE.md-Beschreibung. Für den Fall, dass
  BG-01 (photo-analysis-worker) durch Ergänzung eines dritten `source`-Werts gefixt wird, müsste
  diese Constraint erweitert werden — bereits in BG-01s Recommended-Fix-Text vermerkt, kein
  separates Finding hier nötig.
- **Geldbeträge**: `attendance_fine` hat `CHECK (amount > 0)` auf DB-Ebene (Defense-in-Depth
  zusätzlich zu Pydantic `Field(gt=0)`, von Fork G bereits auf App-Ebene verifiziert).
  `finance_transaction.amount` hat bewusst KEINE CHECK-Constraint — verifiziert als korrekt: laut
  Fork G sind negative Beträge für Ausgaben/Buchungen fachlich vorgesehen, eine CHECK-Constraint
  würde das legitime Verhalten brechen. Kein Fund.
- **UNIQUE-Constraints für Tokens/Slugs**: `submission_link.token` (`submission_link_token_key`,
  Migration `0075`), `share_link.token` (`uq_share_link_token`, Migration `0093`),
  `tenant_domain.domain` (`uq_tenant_domain_domain`), `tenant.public_slug`
  (`uq_tenant_public_slug`) — alle auf DB-Ebene erzwungen, nicht nur applikationsseitig geprüft.
  Kein Race-Condition-Risiko durch fehlendes UNIQUE.
- **Neueste Migrationen (`0090`-`0096`)**: alle gelesen. `0090` ist der bereits bekannte,
  eigenständig dokumentierte historische Audit-Fix (Abgabebox-Quota-Grant). `0091` rein kosmetisch
  (Feature-Beschreibungstext). `0092` legt zwei `SECURITY DEFINER`-SQL-Funktionen an
  (`upload_storage_usage`, `upload_path_referenced`) — korrekt gehärtet: `SET search_path =
  pg_catalog, public` (verhindert die klassische `SECURITY DEFINER`-`search_path`-Injection),
  `REVOKE ALL ... FROM PUBLIC` gefolgt von gezieltem `GRANT EXECUTE` nur an die zwei
  benötigten Rollen, parametrisierte Queries (kein SQL-Injection-Vektor). `0093`-`0096` (Share-Link,
  Photo-Album-Tenant-Share, Tenant-Trust, Album-Item-Share-Pending): durchgehend `NOT NULL` +
  sinnvolle `server_default` (nie `TRUE`/offen für ein neues Sicherheits-Feature), `tenant_trust`
  hat sogar eine eigene `CHECK (tenant_low_id < tenant_high_id)`-Constraint, um Duplikate/
  vertauschte Paare auf DB-Ebene strukturell auszuschliessen — gut durchdacht, kein Fund.

## Teil 2 — Denial-of-Service-Sweep

- **Pagination-Limits**: alle geprüften Listen-Endpoints (`fines.py`, `finance.py`, `files.py`,
  `events.py`, `protocols.py`, `participants.py`, `todos.py`) haben `Query(..., le=200..2000)` im
  Route-Signatur selbst. `admin.py:187,211` (`list_error_logs`, `get_upload_pipeline_status`)
  haben KEIN `le=` im `Query(...)`-Deklarator (nur `gt=0`), ABER der jeweilige Service-Aufruf
  clamped explizit mit `limit=min(limit, 200)` (Zeilen 194, 222) — False-Positive nach Lesen des
  vollständigen Aufrufpfads, kein Fund. Zusätzlich ohnehin nur für Platform-Admin (`owner`-Rolle)
  erreichbar, also kein Angriffspfad für einen normalen Tenant-User.
- **ReDoS**: alle gefundenen `re.compile`/`re.match`-Stellen in `word_import_service.py`,
  `export_service.py`, `domain_verification_service.py` sind linear-zeitige Muster ohne
  verschachtelte/überlappende Quantifizierer (kein `(a+)+`- oder `(.*)+`-artiges Konstrukt). Der
  komplexeste Fund, `_HOSTNAME_RE` (`^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$`),
  hat eine wiederholte Gruppe, aber deren Inhalt ist eindeutig vom Trennzeichen (`.`) abgegrenzt —
  kein Backtracking-Explosionspotential, da jede Wiederholung genau ein `.`-Segment konsumiert
  ohne Mehrdeutigkeit zur nächsten. Kein Fund.
- **PDF-Export-Concurrency**: `export_service.py` hat bereits ALLE drei erwarteten Schutzschichten
  implementiert (im Code selbst mit explizitem Kommentar zur Bedrohung): `RLIMIT_AS` (2 GB pro
  Compile-Prozess), `RLIMIT_CPU` (90s), UND einen globalen `asyncio.Semaphore(4)`
  (`_COMPILE_CONCURRENCY_LIMIT`), der verhindert, dass mehr als 4 `pdflatex`-Prozesse gleichzeitig
  laufen — unabhängig davon, wie viele Export-Requests eingehen. Kein fehlender
  Concurrency-Schutz, wie ursprünglich vermutet. Kein Fund.
- **Tenant-Clone/-Import (`admin.py:534,603`)**: kein App-seitiges Rate-Limit auf diesen teuren
  Operationen gefunden — ABER beide sind ausschliesslich für Platform-Admin mit `owner`-Rolle
  erreichbar (von Fork B bereits vollständig verifiziert). Ein bösartiger externer Angreifer kann
  das nicht auslösen; das verbleibende Risiko ist ein kompromittierter/böswilliger Owner-Account,
  der bereits umfassenden Zugriff auf die gesamte Plattform hätte — kein eigenständiges Finding,
  da ausserhalb des realistischen Bedrohungsmodells für DoS durch einen externen/normalen
  Tenant-User (Abschnitt 22 fokussiert auf genau dieses Szenario).

## Fazit

Sowohl DB-Constraints als auch DoS-Angriffsfläche sind bereits gut gehärtet, teils mit explizit
im Code dokumentierter Bedrohungsanalyse (Export-Concurrency-Kommentar liest sich wie eine
Threat-Model-Notiz aus einem früheren Audit). Keine neuen Findings in diesem Fork.

Status: REVIEWED (0 Findings)
