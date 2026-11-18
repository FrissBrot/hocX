# Auftrag: Berechtigungs-Plan Phasen 0–8 (Release 1.4.0)

- Basis: Commit `5c55886d` auf `feat/navigation-redesign` (Worktree zuerst hart darauf setzen, `git log -1` prüfen), dann Zweig `feat/permissions`. Ein Commit je Phase («perm(phase N): …»), lokal, nie pushen, nie `--no-verify`. Commit-Nachrichten enden mit
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` und `Claude-Session: https://claude.ai/code/session_01C1XdC1MkeJNgDhXQZpPGG2`.
- Plan und alle Entscheide: `docs/permissions-plan.md` – vollständig lesen. Verbindlich: `CLAUDE.md`, `SECURITY-RULES.md`, `design/DESIGN.md`, `docs/RBAC_ARCHITECTURE_PROPOSAL.md`, `docs/FEATURE_ENTITLEMENT_ARCHITECTURE.md`.
- Englische Schlüssel beibehalten; neue Rechte im bestehenden Schema (z. B. `todos.complete_own`, `protocols.approve`, `sharing.public`, `activity_log.read`, `participants.contacts_read`, `personal_data.export`, `fines.manage`, `files.photos_view`, `submissions.review`); deutsch nur in Übersetzungen (4 Sprachen).
- Bestehendes ergänzen statt neu bauen: `permissions/catalog.json` + Sync, `require_permission`/`user.can`, `permissions/route-map.json`, `tests/test_route_permission_inventory.py`, `services/role_service.py`, `services/access_service.py`, `backend/app/public_links/providers.py`. Kein zweites Prüfsystem.
- Eigene Pendenzen abhaken = neues Recht (alle Rollen inkl. Leser bei der Migration, entziehbar → read-only). Zentrale Frontend-Stelle «darf abhaken» heisst nach dem Pendenzen-v2-Merge vermutlich `canToggleTodo` (siehe `frontend/components/todos/`); dort einhängen, sonst in `frontend/app/my-tasks`.
- Vier-Augen-Prinzip: Mandanten-Einstellung (Standard aus), Abschliessen braucht `protocols.approve`.
- «Gruppen» = Rollen. Keine Ordner-Freigaben.
- Migrationen ab **0189**, jede reversibel, Datenmigrationen mit Dry-Run-Report + Test; neue Mandanten-Tabellen mit `tenant_id NOT NULL` + RLS (Vorlagen 0132–0134), `tests/test_tenant_rls.py` deckt sie ab.
- Rollen-UI (Phase 7) in die bestehenden Komponenten unter `frontend/components/roles/` bzw. `users/` einbauen (Seite heisst jetzt «Zugriff»).
- Abweichungen Plan↔Code in `docs/permissions-plan-deviations.md`; Fachliches, das nicht entschieden ist: sicherste Variante ohne Verhaltensänderung, als OFFEN markieren. Phase-0-Lücken nur dokumentieren (`docs/permissions-inventory.md`), echte Sicherheitslücken oben im Bericht.
- Prüfen nach jeder Phase, NIE parallel, immer gesperrt und atomar (gemeinsame Test-Images!):
  `flock /docker/.hocx-heavy.lock sh -c 'C="docker compose -p hocx-tests -f docker-compose.tests.yml --project-directory . --profile tests"; $C down --volumes >/dev/null 2>&1; $C build test-migrations backend-test frontend-test >/dev/null 2>&1; $C run --rm backend-test pytest -q <dateien>'`
  Danach Matrix-Test, `test_route_permission_inventory`, `test_tenant_rls`, `test_public_link_registry`; nach Phase 3 und am Ende komplette Backend-Suite, tsc, Vitest, E2E `rbac-roles`. Statisch: `check-security-rules.py`, `sync-permission-catalog.py --check`, `sync-route-permissions.py --check` (Diff lesen), `check-design-rules.py`, drei `check-i18n-*.py`.
- `.env` nie lesen, kein Push/PR.
- Bericht (max. ~600 Wörter): SHA je Phase, Sicherheitslücken, neue Rechte + Mapping alt→neu (Dry-Run je Standardrolle), Migrationen, geänderte UI-Dateien, OFFEN-Punkte, Ergebnis jeder Prüfung ehrlich.
