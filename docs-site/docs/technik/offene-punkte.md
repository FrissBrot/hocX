# Bekannte offene Punkte

## Noch offen

- **Testabdeckung ist noch dünn.** Seit 2026-07-29 gibt es ein erstes Backend-Testfundament
  (`backend/tests/`, pytest, Rollback-sichere DB-Fixture, CI-Gate), aber bisher nur 8 Tests
  für zwei Bereiche: Tenant-Scoping bei Finanzen/Bussen und die Pagination-Logik. Es fehlen
  noch Tests für Protocol/Todo-Tenant-Scoping, Auth-Flows und alles Frontend (kein
  Playwright-Test vorhanden).
- **Audit-Log-Coverage ist nicht vollständig.** Seit 2026-07-29 werden Finanz-Transaktionen,
  Bussen, Todo-Statuswechsel/-Löschungen, alle Export-Routen sowie die wichtigsten
  Admin-Panel-Aktionen (Mandant löschen/exportieren/importieren, User-Merge) protokolliert.
  Nicht erfasst sind bisher: Mandant anlegen/bearbeiten/klonen, Platform-Admin-Konten
  anlegen/bearbeiten, Mandanten-Benutzerrollen ändern.
- **`ensure_runtime_columns()`** in `main.py` ist seit Migration `0007_runtime_columns` nur
  noch ein No-Op (alte Logik liegt zu Referenzzwecken noch als
  `_legacy_ensure_runtime_columns_DO_NOT_USE()` daneben). Aufräumen steht noch aus.
- **`focused-element-editor.tsx`** (nach dem ProtocolEditor-Split, siehe unten) ist mit
  gut 3200 Zeilen weiterhin die mit Abstand grösste Frontend-Datei. Funktioniert, ist aber
  ein Kandidat für eine weitere Aufteilung (z. B. Matrix-Zeilen-Logik vs.
  Formular-Zeilen-Logik vs. Event-Block-Logik als eigene Dateien), falls sie weiter wächst.

## Erledigt

- **Pagination auf List-Endpoints** (2026-07-29): Alle Haupt-Listen (Protokolle, Todos,
  Termine, Finanz-Transaktionen, Bussen, Teilnehmer) laden serverseitig per `skip`/`limit`
  und im Frontend automatisch beim Scrollen nach (`useInfiniteScroll`-Hook,
  IntersectionObserver). Dabei einen Bug gefixt: der laufende Kontosaldo wurde clientseitig
  aus Floats aufsummiert, was mit Pagination sofort falsche Werte gezeigt hätte — jetzt
  server-seitig per SQL-Window-Function über die volle Kontohistorie berechnet.
- **ProtocolEditor aufgeteilt** (2026-07-29): von 6214 auf 1124 Zeilen, aufgeteilt in
  `protocol-editor-shared.tsx`, `matrix-embedded-block-editor.tsx`,
  `chart-block-renderer.tsx`, `focused-element-editor.tsx` und `session-todos-section.tsx`
  (alle unter `frontend/components/protocol/`). Reine Verschiebung ohne Logikänderung.
  `AppShell` (555 Zeilen) wurde bewusst nicht angefasst, war schon klein genug.
- ~~Keine automatisierten Tests~~ — Grundgerüst existiert jetzt, siehe "Noch offen" oben für
  den aktuellen Abdeckungsgrad.
- ~~Async PDF-Export~~ — bei Überprüfung stellte sich heraus, dass der Export bereits
  `asyncio.create_subprocess_exec` nutzt und den Worker-Prozess nicht blockiert.
- ~~Finanzbeträge als `float` statt `Decimal`~~ — bei Überprüfung stellte sich heraus, dass
  die DB-Spalten bereits `Numeric(15,2)` sind und Pydantic intern mit `Decimal` rechnet; nur
  die JSON-Serialisierung rundet zu `float` (Branchenstandard für die Übertragung, kein
  Datenintegritätsproblem).
- ~~N+1-Query in `FinanceRepository.list_accounts`~~ — bei Überprüfung stellte sich heraus,
  dass bereits eine Subquery-Aggregation in einer einzigen Query verwendet wird.
- ~~Protokoll-Todo-Query mit vielen JOINs~~ — per `EXPLAIN ANALYZE` gegen die Produktivdaten
  geprüft: alle Join-Spalten sind sauber indiziert, Ausführungszeit unter 2ms, kein N+1.
  Bei der aktuellen und absehbaren Datenmenge kein Performanceproblem.

!!! info "Diese Seite pflegen"
    Wenn ein Punkt hier umgesetzt wird, bitte diese Seite entsprechend aktualisieren.
