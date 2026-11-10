# hocX Security Audit

Vollständiges, repository-weites Security Audit von hocX (Backend, Frontend, Abgabebox,
Photo-Analysis-Worker, Infra/Deployment). Auftrag und Methodik: siehe Anfrage vom
2026-09-30 (Auszug in STATE.md zusammengefasst).

## Persistenter Zustand

Dieses Verzeichnis ist das Gedächtnis des Audits über mehrere Sessions hinweg. Bei jedem
Start (auch nach Context-/Token-Verlust) zuerst lesen:

1. `STATE.md` — aktueller Stand, zuletzt untersuchte Datei, nächste Schritte
2. `INVENTORY.md` — vollständiges Repo-Inventar mit Review-Status
3. `FINDINGS.md` — bestätigte und zu verifizierende Findings
4. `TODO.md` — Audit-Queue

Dann fortsetzen, nicht neu beginnen. Bei geändertem Git-HEAD (siehe STATE.md) betroffene
Bereiche als `NEEDS_REVIEW` markieren und neu prüfen.

## Vereinbarte Rahmenbedingungen (mit Nutzer geklärt, 2026-09-30)

- Commits während des Audits: **nur lokal auf `main`**, kein Push zu `origin`.
- Verifikation: wo sinnvoll (Race Conditions, Tenant-Isolation, IDOR) zusätzlich praktisch
  gegen den E2E-Stack (`./scripts/e2e.sh up`, Wegwerf-Konten) testen, nicht nur statisch.
- `.env` und andere reale Secrets/Credentials: niemals inhaltlich lesen oder zitieren (nur
  prüfen, welche ENV-Variablen referenziert werden und ob Secret-Handling im Code sauber
  ist). Gilt zusätzlich zur CLAUDE.md-Regel für die laufende Dev-Instanz.
- Am Ende: alle bestätigten Findings selbst fixen und committen (lokal, main). Fixes, die
  eine Produkt-/Business-Entscheidung erfordern (z. B. Breaking Change, Feature-Entfernung,
  Preis-/Limit-Logik), NICHT eigenmächtig entscheiden, sondern in FINAL_REPORT.md unter
  "Entscheidungen erforderlich" auflisten.
- Am Ende: Übersicht für den Nutzer über (a) was gefixt wurde, (b) was noch Entscheidungen
  braucht.

## Ordnerstruktur

- `STATE.md` — Recovery-Datei, immer zuerst lesen
- `INVENTORY.md` — Repo-Inventar
- `SECURITY_MODEL.md` — Actors, Assets, Trust Boundaries, Invarianten
- `ATTACK_SURFACE.md` — alle erreichbaren Interfaces (Tabelle)
- `FINDINGS.md` — alle Findings, laufend ergänzt
- `TODO.md` — Audit-Queue
- `TEST_RECOMMENDATIONS.md` — fehlende Security-Regressionstests
- `FINAL_REPORT.md` — Abschlussbericht (erst am Ende)
- `evidence/` — Belege zu Findings (Codepfade, ggf. Testausgaben, keine Secrets)
- `components/` — ein Checkpoint pro Komponente
