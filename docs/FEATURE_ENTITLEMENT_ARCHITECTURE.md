# hocX – Feature- und Abo-Architektur (Entitlements)

Stand: 2026-10-27, **umgesetzt** mit Migration `0158_feature_entitlements`. Ergänzt
`docs/RBAC_ARCHITECTURE_PROPOSAL.md` (Berechtigungen). Grundsatz: so einfach wie möglich – ein
Entitlement-System mit einer Quelle, keine Regel-Engine.

## 1. Begriffe und ihre strikte Trennung

| Begriff | Was es ist | Wo es lebt |
|---|---|---|
| **Modul** | fachlicher Produktbereich (Navigation, Vertrieb, Doku) | `permissions/features.json` (`modules`), `docs/PRODUCT_MODULE_ARCHITECTURE.md` |
| **Feature (Entitlement)** | buchbare Produktfähigkeit eines Mandanten | `permissions/features.json` → Tabelle `feature`, `tenant_feature` |
| **Abonnement (Plan)** | kommerzielles Paket aus Features, Limits, Preis | Tabellen `plan`, `plan_feature`, Spalten am `tenant` |
| **Berechtigung** | was ein Benutzer tun darf (RBAC) | `permissions/catalog.json`, `tenant_role`, `user_role` |
| **Feature-Flag** | technische Rollout-Steuerung | bewusst **nicht** vorhanden (Abschnitt 9) |
| **Nutzungslimit** | quantitative Grenze (Konten, Speicher) | Plan-Spalten, `user_limit_service.py`, `upload_pipeline.py` |

Ein Feature wird nur verwendet, wenn **(1)** das Abo es freigibt, **(2)** der Benutzer die Berechtigung
hat und **(3)** Ressourcenregeln (Mandant, Protokollstatus, eigene Daten; `access_service.py`) erfüllt
sind. Ein Upgrade verleiht nie Benutzerrechte; Rollen bleiben unverändert.

## 2. Einzige Quelle: `permissions/features.json`

```json
{"code": "finance", "module": "finance", "downgrade": "read_only", "read_permissions": ["finances.read"], "requires": []}
```

| Feld | Bedeutung |
|---|---|
| `code` | Feature-Code (= `feature.code` in der DB) |
| `module` | Produktmodul |
| `downgrade` | `read_only`: nach Wegfall Daten lesbar, Änderungen gesperrt · `blocked`: Feature aus (z. B. Domain-Routing) |
| `read_permissions` | Berechtigungen, die im Zustand `read_only` weiter gelten (z. B. `finances.read`) |
| `requires` | Features, die zusätzlich gebucht sein müssen (heute leer; geprüft beim Generieren) |

`python3 scripts/sync-feature-catalog.py` generiert `backend/app/core/features_generated.py` (Enum `F`,
`FEATURES`) und `frontend/lib/features.generated.ts`. `--check` (CI, Pre-Commit) verlangt aktuelle
Dateien, je Feature eine Migration und eine Prüfung im Backend. `sync-permission-catalog.py` liest die
erlaubten Feature-Bindungen ebenfalls aus dieser Datei.

Aktuelle Features: `finance`, `abgabebox`, `custom_domain`, `verify_domain`, `task_packages`,
`custom_roles`, `photo_sharing`, `document_designer`.

## 3. Datenbankmodell

Bestehende Tabellen, erweitert statt ersetzt:

| Tabelle | Spalten (Auszug) | Änderung in 0158 |
|---|---|---|
| `feature` | `code`, `name`, `description`, `standalone_price_monthly_rp` | 4 neue Zeilen |
| `plan` | Preis, `included_user_limit`, `included_storage_bytes`, `load_priority`, `is_bookable` | – |
| `plan_feature` | `plan_code`, `feature_code` | Zuordnung der neuen Features (standard, premium) |
| `tenant_feature` | `tenant_id`, `feature_code`, `enabled_by_admin_id` | **neu:** `access` (`full`/`read_only`), `source` (`plan`/`addon`) |
| `tenant` | `plan_code`, `billing_cycle`, `user_limit_override`, `storage_quota_bytes` | – |

`tenant_feature` hat RLS (Mandantendaten). `source='plan'` folgt Planwechseln, `source='addon'`
(Einzelbuchung oder Bestandsschutz) bleibt bei Planwechseln stehen.

## 4. Abonnement-Zuordnung

- Plan zuweisen (Adminportal, `PATCH /api/admin/tenants/{id}/subscription`) ruft
  `AdminTenantService._apply_plan_features`:
  - Features des neuen Plans → `access='full'`, `source='plan'`.
  - Plan-Features des alten Plans, die fehlen → je `downgrade`: `read_only` oder Zeile löschen.
  - Zusatzmodule (`source='addon'`) bleiben unverändert.
- Feature-Tab (`PUT /api/admin/tenants/{id}/features`): `enabled_codes` (voll) und `read_only_codes`.
  Nicht aufgeführte Zeilen werden gelöscht. `read_only` für ein `blocked`-Feature → 400.
- Neue Mandanten mit Plan durchlaufen denselben Weg (`create_tenant`).

### Öffentliche Website

Die Landing Page liest Abos und Features bei jedem Aufruf aus der Datenbank:
`GET /api/public/plan-comparison` (`routes/public_catalog.py`,
`AdminTenantService.public_plan_comparison`) liefert die buchbaren Abos wie die Preiskarten
und jedes Feature, das in einem davon steckt oder einzeln zubuchbar ist
(`standalone_price_monthly_rp`), mit Name und Beschreibung aus der Tabelle `feature` und dem
Produktmodul aus `features.json` (`MODULES`, Reihenfolge der Gruppen). Daraus entstehen
Preiskarten und Vergleichstabelle (`frontend/components/website/`). Keine internen Felder
(Mandantenzahl, Lastpriorität, nicht buchbare Abos).

## 5. Feature-Prüfung

### Backend (`backend/app/core/security.py`)
- `CurrentUser.current_tenant_features` (voll) und `current_tenant_read_only_features` werden pro
  Request frisch aus `tenant_feature` geladen (Entzug wirkt sofort).
- `CurrentUser.has_feature(code, write=True)`.
- `require_feature(user, code, *, write=True)`: 403 «nicht gebucht» bzw. «nur noch lesend (nicht mehr im Abo)».
- `require_permission(user, P.X)`: bei gebundener Berechtigung `require_feature(..., write=P.X not in read_permissions)`.
- `CurrentUser.can(P.X)`: gleiche Regel ohne Exception.
- Konvention in Routen: `require_permission(...)` zuerst, danach `require_feature(user, F.CODE, write=...)`;
  `write=False` nur für reine Lese-Endpunkte. `permissions/route-map.json` zeigt jede Prüfung,
  «(lesen)» markiert `write=False`.
- Hintergrundjobs prüfen selbst (Beispiel: `task_package_service.run_due_task_packages` verarbeitet nur
  Mandanten mit `access='full'`).
- Dokumente: `documents/permissions.py::require_design` (Designer); die Capability `edit_templates`
  verlangt Berechtigung und Feature, damit das Studio ohne Designer nur Ansehen und Exportieren anbietet.

### Prüfstellen der neuen Features

| Feature | Gesperrt ohne volle Buchung | Bleibt erlaubt |
|---|---|---|
| `task_packages` | alle Schreib-Endpunkte unter `/api/task-packages`, täglicher Job | Lesen im Zustand `read_only`; bestehende Pendenzen |
| `custom_roles` | Rolle anlegen/ändern (`POST/PATCH /api/roles`) | Rollen ansehen, zuweisen, löschen; bestehende Rollen wirken weiter |
| `photo_sharing` | Freigabelink erstellen, Partner einladen/konfigurieren | bestehende Links, Widerruf, Einladungen annehmen |
| `document_designer` | Vorlagen/Bausteine anlegen, Entwurf speichern, veröffentlichen, duplizieren, Revision wiederherstellen, Beispiel importieren, Gestaltung je Sitzungsvorlage | bestehende Vorlagen exportieren, zuweisen, archivieren, löschen; Brand Studio |

### Frontend (`frontend/lib/permissions.ts`)
- Session liefert `current_tenant.enabled_features` und `read_only_features`.
- `featureAccess(session, code)` → `full` · `read_only` · `none`; `can()` folgt derselben Regel wie das Backend.
- `components/ui/feature-notice.tsx` zeigt «nicht im Abo» bzw. «nur noch lesend».
- Frontend-Prüfungen sind nur Benutzerführung; das Backend prüft jede Aktion.

## 6. Zusammenspiel mit RBAC

- Feature und Berechtigung sind orthogonal. Bindung nur, wo eine Berechtigung ausschliesslich ein Feature
  betrifft (`finances.*`, `submissions.*`). Alle anderen Features werden zusätzlich zur Berechtigung
  geprüft (z. B. `templates.manage` + `task_packages`).
- Kein Feature pro Berechtigung, keine Berechtigung pro Feature.
- Ein Upgrade ändert keine Rollen. Ein Downgrade entzieht keine Rollen; eigene Rollen bleiben wirksam.

## 7. Abhängigkeitsmanagement

`requires` in `features.json` wird beim Generieren validiert (bekannte Codes, keine Selbstreferenz).
Heute hat kein Feature eine harte Abhängigkeit. Weiche Abhängigkeiten (z. B. Abgabebox-Domain braucht
`abgabebox`) bleiben fachlich in den Services. Erst wenn ein Feature ohne ein anderes technisch nicht
funktioniert, wird `requires` gesetzt und im Admin-Service beim Buchen geprüft (Roadmap).

## 8. Upgrade- und Downgrade-Verhalten

| Feature | Daten | Lesen | Bearbeiten | Export | Laufende Prozesse | Reaktivierung |
|---|---|---|---|---|---|---|
| `finance` | bleiben | ja | nein | ja (Lesen) | – | sofort voll |
| `abgabebox` | bleiben | ja (interne Ansicht) | nein; öffentliche Links 403 | ja | Uploads gestoppt | sofort |
| `task_packages` | bleiben (inkl. erzeugter Pendenzen) | ja | nein | – | Job erzeugt nichts Neues | sofort, Job holt nach |
| `custom_roles` | bleiben | ja | nein (Anlegen/Ändern) | – | Rollen wirken weiter | sofort |
| `photo_sharing` | bleiben | ja | keine neuen Links/Einladungen | – | bestehende Links gültig | sofort |
| `document_designer` | bleiben | ja | nein | ja (bestehende Vorlagen rendern) | – | sofort |
| `custom_domain` / `verify_domain` | Domain-Eintrag bleibt | – | nein | – | Routing sofort aus | Routing sofort wieder |
| Speicher (Limit) | bleiben | ja | neue Uploads abgelehnt | ja | – | bei mehr Kontingent |
| Konten (Limit) | bleiben | ja | keine weiteren Logins aktivierbar | ja | bestehende Logins aktiv | bei höherem Limit |

Einheitliche Regel: **Nie Daten löschen, nie Lesen sperren** (ausser Domain-Routing, das ein Dienst
und kein Datenbestand ist). Löschen ist immer eine bewusste Handlung (Aufbewahrung, Bereinigung).

## 9. Bewusst nicht gebaut

- **Feature-Flags/Rollout:** Kein Bedarf; neue Funktionen werden über Releases ausgerollt. Falls nötig:
  eine globale Tabelle `rollout_flag(code, enabled, tenant_ids)` getrennt von Entitlements – nie in
  `tenant_feature` mischen.
- **Mengenlimits pro Objektart:** nicht nötig (Abschnitt 6 der Abo-Strategie).
- **Regel-Engine/Preislogik im Code:** Preise bleiben Daten im Adminportal.

## 10. Migrationskonzept (umgesetzt)

`0158_feature_entitlements.py`:
1. Spalten `access` (Default `full`) und `source` (Default `addon`) mit CHECK.
2. Backfill `source='plan'` für Features im aktuellen Plan des Mandanten.
3. Neue Features in `feature`; **jeder bestehende Mandant** erhält sie als `addon` (Bestandsschutz,
   Muster 0084/0085).
4. `plan_feature` für `standard` und `premium` (falls Plan vorhanden).
5. Downgrade-Pfad entfernt die neuen Features und Nur-Lesen-Zeilen.

Mandanten-Import: Archive von vor 0158 erhalten die vier Features als Bestandsschutz
(`tenant_import_service._import_tenant_settings`); neuere Archive übernehmen `access`/`source`.

## 11. Teststrategie

| Ebene | Test |
|---|---|
| Katalog | `sync-feature-catalog.py --check` (CI, Pre-Commit) |
| Prüflogik | `backend/tests/test_feature_entitlements.py` (Nur-Lesen, Planwechsel, Admin-Tri-State, Benutzerlimit) |
| Bestehendes Gating | `tests/test_feature_gating.py`, `tests/test_admin_plan_pricing.py` |
| Routen | `tests/test_route_permission_inventory.py`, `permissions/route-map.json` (`--check`) |
| Frontend | `frontend/lib/permissions.test.ts` (Nur-Lesen-Zustand, `featureAccess`) |
| E2E | `frontend/e2e/feature-gating.spec.ts` (bestehend); Erweiterung für Nur-Lesen empfohlen |

Testfabrik: `tests/factories.py::DEFAULT_TEST_FEATURES` entspricht dem Bestandsschutz.
