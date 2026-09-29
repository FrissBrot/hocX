# Fork G — Finanzen/Bußgelder — Ergebnisse

Scope: `backend/app/api/routes/finance.py`, `fines.py`, `backend/app/repositories/finance_repository.py`,
`fines_repository.py`, `backend/app/schemas/finance.py`, `fines.py`. Kein Service-Layer vorhanden —
Business-Logik liegt direkt in Routes/Repositories. Keine Codeänderungen, keine Commits.

## Ergebnis: keine neuen CONFIRMED/NEEDS_VERIFICATION-Findings

Alle 5 Prüffragen wurden aktiv verifiziert (False-Positive-Check, Abschnitt 28), kein Fund
überlebt die Gegenprüfung.

### 1. Rollen-/Feature-Guards pro Endpoint — konsistent und passend zur Sensitivität

`security.py` definiert die Rollen-Hierarchie eindeutig: `require_reader` (reader/kassier/writer/
admin), `require_writer` (writer/admin), `require_finance_read` (reader/kassier/writer/admin, +
`require_feature(user,"finance")`), `require_finance_write` (**nur** kassier/admin — ein normaler
`writer` kann KEINE Finanz-Mutation auslösen, korrekt getrennt von Protokoll-Schreibrechten),
`require_all_fines_read` (writer/kassier/admin, explizit ohne reader).

Jeder Endpoint in `finance.py` (10 Routen) und `fines.py` (7 Routen) wurde einzeln gelesen: jede
Mutation ruft `require_finance_write`, jeder Read ruft `require_finance_read`/
`require_all_fines_read`/`require_reader`+Feature-Gate passend zur tatsächlichen Sensitivität.
Kein Endpoint mit zu laxer Rolle gefunden.

### 2. `kassier`-Rolle — kein Privilege-Escalation-Pfad

`kassier` ist in `require_reader` (Basis-Lesen) und `require_finance_write` (Finanz-Mutation)
enthalten, aber NICHT in `require_writer` (Protokoll-Schreiben) — ein Kassier kann also Finanzen
verwalten und lesen, aber keine Protokolle/Termine ändern. Kein Pfad gefunden, über den ein
Kassier zusätzliche, nicht vorgesehene Rechte bekäme.

### 3. Business-Logic-Bypass / Race Conditions bei Fine-State-Übergängen

`delete_fine`, `collect_fine`, `reopen_fine` verwenden ALLE identisch `SELECT ... FOR UPDATE`
(Row-Lock) auf die `AttendanceFine`-Zeile, bevor der Status geprüft/geändert wird — verifiziert
für jede der drei Methoden individuell (nicht nur `collect_fine`, wie der Ausgangsverdacht
formulierte). Ein doppeltes Einziehen/Löschen/Reopen durch zwei simultane Requests ist damit
strukturell ausgeschlossen (Postgres READ COMMITTED + expliziter Row-Lock). `create_fine` hat
kein eigenes Row-Lock-Ziel (INSERT), sperrt stattdessen die Eltern-`Protocol`-Zeile
(`with_for_update()`), um `find_existing_fine`+INSERT gegen einen gleichzeitigen zweiten
`create_fine`-Aufruf für dasselbe Protokoll/Teilnehmer/Typ zu serialisieren — Duplicate-Check
somit ebenfalls race-frei.

Freeze-Schutz (`protocol.status == "abgeschlossen"` → Ablehnung) konsistent an allen 4
State-ändernden Fine-Operationen UND an `create_transaction`/`update_transaction`/
`delete_transaction` in `finance_repository.py` geprüft — ein abgeschlossenes Protokoll ist
überall unveränderlich, keine Lücke gefunden. `collect_fine`s `collecting_protocol_id`
(Client-Input) wird korrekt gegen `tenant_id` verifiziert, BEVOR es in `closed_in_protocol_id`
übernommen wird (Kommentar verweist selbst auf einen historischen Fund, 2026-08-25 — Fix
verifiziert, hält).

### 4. Cross-Tenant-Zugriff über Fine-/Transaction-/Account-IDs

`_resolve_fine_id` löst `AttendanceFine.public_id` bewusst OHNE `tenant_id`-Filter auf (Kommentar
erklärt das explizit), delegiert den eigentlichen Tenant-Beweis an die drei Repository-Methoden
(`delete_fine`/`collect_fine`/`reopen_fine`), die jeweils `protocol.tenant_id != tenant_id` prüfen
und in diesem Fall `None`/`False` zurückgeben — die Route mappt das auf denselben 404
("Fine not found or already collected") wie den echten "already collected"-Fall. Kein
Enumerations-Orakel: ein Angreifer kann nicht unterscheiden, ob eine `fine_id` gar nicht
existiert, einem fremden Tenant gehört, oder bereits eingezogen wurde — alle drei Fälle liefern
identisch 404. `FinanceAccount`/`FinanceTransaction` (letztere ohne eigene `tenant_id`-Spalte,
transitiv über `FinanceAccount` gescoped) werden in JEDEM Pfad (`finance.py` Routen,
`finance_repository.py`) korrekt über `FinanceAccount.tenant_id == tenant_id`
gejoint/gefiltert — verifiziert für alle 6 Account-/Transaction-Methoden.

### 5. Geldbeträge — Datentyp und Grenzen

`Decimal` durchgängig (DB `Numeric(15,2)`, siehe Schema-Kommentare), keine Floats im Business-Pfad
(nur `PlainSerializer` zur JSON-Ausgabe, mit `ROUND_HALF_UP`-Quantisierung auf Cent-Genauigkeit —
verhindert Float-Rundungsrauschen in der API-Antwort). `AttendanceFineCreate.amount` hat
`Field(gt=0)` (Bußgelder können nicht negativ/null sein) — bewusst dokumentierter Unterschied zu
`FinanceTransactionCreate.amount`, das explizit auch negativ sein darf (Ausgaben/Rückerstattungen
sind eine Geschäftsanforderung, kein Bug). Keine explizite Obergrenze für Transaktionsbeträge im
Schema, aber die DB-Spalte `Numeric(15,2)` würde einen absurd grossen Wert mit `DataError`
ablehnen — dieser Fehler ist eine `SQLAlchemyError`-Subklasse und wird in
`create_transaction`/`update_transaction` bereits korrekt abgefangen (`except SQLAlchemyError`
→ Rollback → HTTP 400), kein Crash/kein unbehandelter Zustand. Kein Finding (keine praktikable
Ausnutzung eines "zu grossen" Betrags über eine reine Validierungslücke hinaus).

## Fazit

Finance/Fines-Bereich ist bereits sehr sorgfältig gehärtet (sichtbar an den zahlreichen
Code-Kommentaren, die auf frühere Audit-Funde 2026-08-12/08-16/08-25 verweisen und deren Fixes
bei dieser Prüfung alle als weiterhin korrekt verifiziert wurden — keine Regression). Keine
neuen Findings in diesem Fork.

Status: REVIEWED (keine neuen Findings)
