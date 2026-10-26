# RBAC-Architekturvorschlag für hocX

Stand: 2026-10-26 · Branch-Basis `feat/document-canvas-fidelity` (Alembic-Head `0155_element_library`)
Status: **Umgesetzt** auf Branch `feat/rbac` (Migrationen `0156_rbac`, `0157_drop_legacy_role`), siehe
Abschnitt 12 «Umsetzungsstand». Der Text darunter ist der ursprüngliche Vorschlag; Abweichungen
stehen in Abschnitt 12.
Ursprünglicher Status: **Vorschlag, nicht umgesetzt.** Fachliche Entscheidungen E-4, E-5, E-7, E-10 und E-12 sind am
2026-10-26 getroffen (Abschnitt 10). Für dieses Dokument wurde kein produktiver Code, keine
Migration und keine bestehende Berechtigung geändert.

Kennzeichnungen im Text:

- **[Befund]** steht so im Code (mit Fundstelle).
- **[Annahme]** ist abgeleitet und nicht durch Code oder Doku belegt.
- **[Entscheidung E-n]** braucht eine fachliche Entscheidung (Liste in Abschnitt 10).

Pfade ohne Präfix beziehen sich auf `backend/app/`.

**Analysebasis:** Die Analyse lief auf dem noch **nicht gemergten** Branch `feat/document-canvas-fidelity`
(Umbau „Vorlagen, Bausteine und Dokument-Studio an einem Ort“, Commit `4a8161d7`). Dieser Umbau
ändert Rechte gegenüber `main` bewusst: Vorlagenelemente (anlegen/ändern/verschieben/entfernen,
`POST /template-elements/{id}/detach`) und Elementdefinitionen bzw. die Bibliothek „Meine Bausteine“
(anlegen/ändern) sind dort **writer** statt admin (`api/routes/templates.py`). Writer dürfen auch
eigene Gestaltungen ihrer Sitzungsvorlage anlegen und veröffentlichen
(`document_studio.py` session-templates/designs, publish). Laut Commit bleiben „Einstellungen,
Teilnehmende, Bussen Admin-Sache“. Dieser Vorschlag behandelt den Branch-Stand als **Ist-Zustand**.
Die RBAC-Umsetzung beginnt erst **nach dem Merge** dieses Branches, weil sonst Konflikte in
`templates.py`, `document_studio.py`, `documents/permissions.py` und `frontend/app/templates/*`
entstehen.

---

## 0. Kurzfassung

1. hocX hat heute ein **festes Rollenmodell**: ein Konto gehört zu genau einem Mandanten und hat
   genau eine von vier globalen Rollen (`admin`, `writer`, `kassier`, `reader`). Die Rolle steht
   in `app_user.role_id` und zeigt auf die globale Tabelle `role`. Die Rollencodes sind an
   **über 40 Stellen** in Backend und Frontend fest verdrahtet.
2. Die Prüfungen laufen serverseitig und werden **bei jedem Request frisch aus der DB geladen**
   (`core/security.py::build_current_user`). Mandantentrennung (RLS + `get_by_public_id(tenant_id=…)`)
   ist sauber. Die Schwächen liegen woanders: verstreute Rollen-Literale, uneinheitliche
   Lösch- und Bearbeitungsrechte und einige echte Lese-Lecks (Abschnitt A.5). **Diese Lecks sollten
   unabhängig von RBAC zuerst behoben werden.**
3. Empfehlung: **schlankes, datenbankgestütztes RBAC** mit
   - **15 systemseitig definierten Berechtigungen**,
   - **mandanteneigenen Rollen** (vier vorkonfigurierte Standardrollen pro Mandant, die die heutigen
     Rollen exakt abbilden),
   - **mehreren Rollen pro Benutzer**; die effektiven Rechte sind die Vereinigungsmenge,
   - **vier kleinen Tabellen** (`permission`, `tenant_role`, `tenant_role_permission`, `user_role`),
   - **einer** Prüffunktion `require_permission(user, P.X)` plus einer Handvoll fester
     Ressourcenregeln, die es heute schon gibt. Eine Policy-Engine ist nicht vorgesehen.
4. Die Einführung erfolgt in zwei Schritten. Zuerst kommt eine **verhaltensgleiche
   Äquivalenzmigration**: die alten `require_*`-Helfer werden intern auf Permissions abgebildet,
   ohne Rechteänderung, und durch eine Äquivalenztabelle getestet. Erst danach wird jede fachliche
   Bereinigung einzeln freigegeben, und erst ganz am Ende werden eigene Rollen in der Oberfläche
   freigeschaltet.

---

## A. Ist-Zustand

### A.1 Rollenmodell

| Element | Fundstelle | Befund |
|---|---|---|
| Tabelle `role` (global, ohne `tenant_id`) | `sql/baseline_schema.sql:1227`, Modell `models/entities.py:258` | `id smallint`, `code text UNIQUE`, `description`. Keine RLS, `hocx_app` hat volle DML-Rechte (`baseline_schema.sql:5510`). |
| Seed | `sql/baseline_lookup_data.sql:276-279` | 1 admin, 2 writer, 3 reader, 4 kassier |
| Zweiter Seed beim Start | `main.py:44-61` `ensure_roles()` | **[Befund] Abweichende IDs** (2 admin, 3 writer, 4 reader, 5 kassier). Greift nur, wenn ein Code fehlt; auf Baseline-DBs wirkungslos, aber eine Fehlerquelle. `scripts/seed_test_tenant.py:88-91` verwendet wieder 1–4. |
| Zuordnung | `app_user.role_id NOT NULL → role(id) ON DELETE RESTRICT` (`0078_single_tenant_users.py:76-121`, `entities.py:286`) | Genau **eine** Rolle pro Konto. Die früheren Tabellen `user_role` und `user_tenant_role` wurden in 0078 gelöscht. |
| Laufzeitobjekt | `core/security.py:28` `CurrentUser.current_role: str` | Pro Request aus der DB (`build_current_user`, :160) |
| Plattform-Admin | `platform_admin.role` ∈ {`owner`,`support`} (`entities.py:350-372`), `core/admin_security.py:131,141` | Vollständig getrennt (eigene Tabelle, eigene Session, eigene Domain). **Bleibt unverändert.** |
| Mandanten-Features | `feature`, `tenant_feature`, `plan_feature` (`0084`, `0085`); `require_feature` (`core/security.py:247`) | Gebuchte Module (`finance`, `abgabebox`, `custom_domain`, `verify_domain`). Sie gelten **zusätzlich zur** Rolle und sind kein Teil des RBAC. |
| Eingeschränkte Leser | `user_template_access`, `user_protocol_access` (`entities.py:1050-1075`, RLS seit `0132`) | Siehe A.3. Eine Ressourcenregel, keine Rolle. |
| Doku | `docs-site/docs/benutzer/rollen.md` | „Benötigt eine Person beide Rechte [writer+kassier], muss sie derzeit `admin` sein.“ Das ist der **konkrete fachliche Bedarf für mehrere Rollen pro Benutzer**. |

Die heutige fachliche Bedeutung der Rollen, aus dem Code abgeleitet:

| Rolle | Darf (zusätzlich zur Rolle darüber) |
|---|---|
| `reader` | Termine sowie **abgeschlossene** Protokolle lesen (eingeschränkte Leser: nur zugewiesene), Traktanden, eigene Aufgaben und eigene Bussen sehen, PDF-Export, Vorlagenliste lesen, Kassenbuch lesen (wenn `finance` gebucht), Abgaben lesen (wenn `abgabebox` gebucht), Statistik (personenbezogen nur die eigene Zeile), Aufgaben-Kalenderfeed |
| `kassier` | reader **plus**: alle Protokolle inkl. Entwürfe, alle Bussen, personenbezogene Statistik, Finanzen und Bussen buchen, Dateien in Protokollen bzw. Partneralben lesen (`services/access_service.py:116,132`) |
| `writer` | reader **plus**: Termine, Protokolle, Traktanden, Aufgaben, Listen, Teilnehmende, Dateien/Fotos/Alben, Freigabelinks, Word-Import, Vorlagenelemente, Elementdefinitionen anlegen, Dokumentvorlagen bearbeiten, Abgaben verwalten, alle Bussen und Statistik lesen (aber **keine** Finanzbuchungen), Termin-Kalenderfeed. Darf u. a. Protokolle und Termine **löschen**. |
| `admin` | alles, zusätzlich: Benutzer und Logins, Rollen zuweisen, MFA anderer zurücksetzen, Mandanten- und Datenschutz-Einstellungen, Aufbewahrung, Prüfdomain, Vorlagen und Zyklen anlegen/löschen, Aufgabenpakete, Dokumentvorlagen veröffentlichen und zuweisen, Corporate Design, Aktivitätsprotokoll, Speicherübersicht, Gesamtexport (zusätzlich `mfa_verified`), Personendaten-Export für andere, Korrektur historischer Listenstände. **MFA ist Pflicht** (`core/security.py:198`). |

### A.2 Bestehende Prüfmechanik

- **Zentrale Helfer** in `core/security.py:235-299`: `require_reader`, `require_writer`,
  `require_admin`, `require_feature`, `require_finance_read/write`, `require_abgabebox_read/write`,
  `require_all_fines_read`. Sie werden **imperativ im Funktionsrumpf** aufgerufen, nicht als
  `Depends`. Router-Dependencies gibt es nicht.
- **Prüfungen in Services:** `services/user_service.py` (`require_admin` in jeder Methode),
  `services/mfa_service.py:195`, `services/tenant_service.py:130,262,288` (`_manageable_tenant_ids`),
  `services/access_service.py` (`can_read_template`/`can_read_protocol`/`ensure_can_read_*`).
- **Eigene Capability-Map** des Dokument-Studios: `documents/permissions.py:21-55`
  (export/view = reader, edit = writer, publish/brand = admin, dazu `personal_data`, `unmark_drafts`,
  `finance_data`), ergänzt durch `documents/context.py:192-199`, `documents/catalog.py:27,308-332`
  (`Access = Literal["reader","writer","finance"]`) und `documents/bindings.py:27,157,480`.
- **Weitere Rollen-Literale außerhalb von `security.py`** [Befund]:
  `api/routes/protocols.py:161`, `fines.py:52`, `agenda_items.py:115`, `managed_documents.py:44`,
  `files.py:843,979`, `collaboration_ws.py:171`, `document_studio.py:266`, `admin.py:979-985`,
  `services/access_service.py:19,31,36,48,51,116`, `services/statistics_common.py:398`
  (`PER_PERSON_ROLES`), `services/calendar_feed_service.py:36-43` (`can_subscribe`),
  `services/user_service.py:50-53,181-190`, `services/admin_tenant_user_service.py:40-49`,
  `services/participant_service.py:21`, `services/mfa_service.py:103`,
  `repositories/user_repository.py:26`, `services/tenant_import_service.py:585-590,638`,
  `services/tenant_transfer_common.py:14,51`, `services/data_export/tenant.py:245`,
  `services/data_export/personal.py:43`, `documents/service.py:377`, `schemas/user.py:103,129,157,188`,
  `schemas/admin.py:282,288`, `schemas/participant.py:36`. Die Schemas prüfen `role_code` nur als
  freien `str`; die Prüfung passiert im Service gegen die DB.
- **Frontend** (nur zur Benutzerführung): Es gibt **keinen zentralen Helfer**. Rollenvergleiche
  stehen direkt in rund 30 Seiten und Komponenten, z. B. `frontend/app/*/page.tsx`
  (`session.current_role !== "admin"`), `components/ui/app-shell-nav.ts:31-35`,
  `components/dashboard/dashboard-permissions.ts`, `app/finances/page.tsx:16-31`,
  `app/fines/page.tsx:21-34`, `app/protocols/[id]/page.tsx:26-27`,
  `components/finances/finances-view.tsx`, `components/mobile/*`, `components/documents/*`.
  Die Rollenauswahl ist eine Radiogruppe mit vier festen Codes in
  `components/users/user-management.tsx:26-29,343-355`.
- **Indirekte Ausführung:** Render-Jobs (`services/document_render_jobs.py:156`) und
  Kalenderfeeds (`services/calendar_feed_service.py:163-180`) bauen den Benutzer **bei der
  Ausführung neu** aus der DB auf. Rechteänderungen greifen dort also sofort. Die
  Kollaborations-WebSocket prüft alle 30 s neu (`collaboration_ws.py`, SEC-007).
- **Session und Rollenwechsel:** `session_revoke_at` wird bei Passwortwechsel, Deaktivierung,
  Login-Entzug und MFA-Reset gesetzt, **nicht** bei einem Rollenwechsel. Das ist korrekt, weil die
  Rolle bei jedem Request neu geladen wird.

### A.3 Ressourcenregeln, die schon existieren

| Regel | Fundstelle |
|---|---|
| Mandant: RLS (`core/tenant_scope.py::bind_tenant_scope`, Policies `0132`/`0134`) und `get_by_public_id(..., tenant_id=…)` | SECURITY-RULES §1/§2 |
| **Eingeschränkte Leser:** Ein `reader` mit mindestens einer Zeile in `user_template_access`/`user_protocol_access` sieht nur die Vorlagen und Protokolle, denen er als Teilnehmer zugeordnet ist. Die Zeilen werden **ausschließlich abgeleitet** (`access_service.sync_user_access_from_participants`, :145) aus der Teilnehmer-Zuordnung zu Vorlagen (`PUT /participants/{id}/templates`, `PUT /templates/{id}/participants`, writer). Ein Reader ohne Zeilen ist „uneingeschränkt“ und sieht im Protokoll-Listing nur `abgeschlossen`. | `services/access_service.py:17-57`, `repositories/access_repository.py:40,84,97` |
| Eigene Daten: eigene Bussen (`fines.py:52`), eigene Aufgaben, eigene Kalenderfeeds, eigenes Profil, eigene MFA | diverse |
| Personenbezogene Statistik: nur `writer/kassier/admin` sehen alle Personen, außer der Mandant schaltet sie öffentlich (`tenant.statistics_per_person_public`) | `services/statistics_common.py:398-411` |
| Gesperrte/eingefrorene Protokolle sind nicht änderbar | `protocol_elements.py` (Lock-Prüfung) |
| Geteilte Fotoalben: Eigentümer-Mandant und akzeptierter Partner | `services/photo_album_share_service.py`, `files.py:1152` |
| Systemvorlagen (Dokument-Studio): nur Plattform-Admin | `document_studio.py:316` `_editable_template` |
| Letzter Administrator: Herabstufen, Deaktivieren, Login-Entzug und Löschen des letzten aktiven Admins werden blockiert | `services/user_service.py:167-193`, auch für Plattform-Admin (`admin_tenant_user_service.py:48`) |
| Eigenes Konto löschen ist verboten | `user_service.py:265` |
| Abgabebox: eigenes Sicherheitsmodell, ohne Benutzer. DB-Rolle `hocx_abgabebox`, RLS über das geheime Link-Token (`abgabebox-backend/app/link_scope.py`, `0133_abgabebox_rls`) | **bleibt unverändert, kein User-RBAC** |

### A.4 Datenbankstrukturen, die wiederverwendet werden können

- `app_user` (= Teilnehmende **und** Benutzer seit 0108): bleibt die User-Tabelle.
- `role`: global, wird nach der Migration überflüssig (siehe D).
- `feature`/`tenant_feature`: bleibt **orthogonal**. Effektives Recht = Permission **und** Feature.
- `user_template_access`/`user_protocol_access`: bleiben unverändert als Ressourcenregel.
- RLS-Muster (`0132_tenant_rls.py` `BASE`, `0134_child_table_rls.py`) und
  `tests/test_tenant_rls.py` (schlägt bei Tabellen mit `tenant_id` ohne RLS fehl).

### A.5 Sicherheitslücken und Inkonsistenzen

Schwere nach eigener Einschätzung. Die mit ✔ markierten Punkte habe ich zusätzlich direkt im Code
gegengeprüft. **Die Punkte S-1 bis S-6 sind vom RBAC unabhängig und sollten vorab behoben werden
(Phase 0).**

| # | Schwere | Befund | Fundstelle |
|---|---|---|---|
| S-1 ✔ | **hoch** | **Der Statistik-Cache ignoriert den Aufrufer.** Der Redis-Key enthält nur Mandant, Zyklus, Offset und Finanz-Flag. Mit `?cached=true` bekommt ein `reader` das von einem Admin berechnete Ergebnis mit allen Personen. Das umgeht PRIV-001. Umgekehrt bekommt ein Admin evtl. ein gefiltertes Ergebnis. Eingeschränkte Leser werden in der Statistik außerdem nicht gefiltert. | `api/routes/statistics.py:133-135,148` |
| S-2 ✔ | **hoch** | **Entwürfe sind per ID lesbar.** Das Listing zwingt uneingeschränkte Reader auf `abgeschlossen` (`protocols.py:161`), aber `can_read_protocol` prüft nur den Mandanten, nicht den Status. Damit liefern `GET /protocols/{id}`, `/elements`, Managed Documents und die WebSocket Entwürfe an jeden Reader, der die ID kennt. | `services/access_service.py:47-57` |
| S-3 | mittel | **Eingeschränkte Leser nicht geprüft:** pending-todos, period, cycle-events und scroll-position prüfen nur den Mandanten. `GET /protocols/next-session` und `GET /todos/blocks` sind ebenfalls nicht auf die Zuordnung eingeschränkt. | `protocols.py:234,386,407,419,546`; `todos.py:65` → `protocol_todo_service.py:122` |
| S-4 ✔ | mittel | **Teilnehmerliste für alle Reader:** `/documents/sources/participants` liefert alle aktiven Teilnehmenden, obwohl `GET /participants` writer-only ist. | `api/routes/documents.py:433-435` |
| S-5 | mittel | **Listen für Reader über Snapshots:** `GET /table-snapshots/...` ist reader-only und enthält `list_definition`/`list_entry`. Die Listen-API ist writer-only. | `table_snapshots.py:117` |
| S-6 | mittel | **Rennbedingung beim letzten Admin:** `count_active_admins` zählt ohne Sperre. Zwei Admins, die sich gleichzeitig gegenseitig herabstufen, hinterlassen einen Mandanten ohne Admin. | `repositories/user_repository.py:21-30`, `user_service.py:187` |
| S-7 | **entschieden: gewollt (E-7)** | **Partner-Alben nicht nur lesend:** Ein Partner-writer kann eigene Fotos in ein fremdes Album legen (sofort freigegeben) und `best_override` auf allen Elementen setzen. SECURITY-RULES §1.2 sagt: „was ein Partner lesen darf …, darf er deshalb noch nicht ändern“. Das Mitwirken ist **bewusst gewollt** (E-7). Es bleibt so, wird aber als Ausnahme zu §1.2 in SECURITY-RULES dokumentiert. | `files.py:1152,1446,1461` |
| S-8 | niedrig/fachlich | Reader sehen **alle** Kassenbuch-Konten und Buchungen (`require_finance_read`) und laden **alle** Abgabe-Dateien herunter (`require_abgabebox_read`, inkl. ZIP). Laut Kommentar ist das gewollt („Every tenant role may inspect …“). Für Abgaben ist **entschieden, dass es so bleibt** (E-4), für das Kassenbuch ist es offen [E-3]. | `core/security.py:255,272` |
| S-9 | niedrig | GETs mit Schreibwirkung: `GET /document-studio/catalog` und `GET /document-brands` (`ensure_default_brand` + commit), Thumbnail-Erzeugung (`files.py:1008`, `public_share.py:184`, `submission_assignments.py:389`), Download des Gesamtexports schreibt einen Audit-Eintrag. Das ist meist idempotent oder Cache, gehört aber auf die Liste für SECURITY-RULES §3.1. | — |
| S-10 | niedrig | Rollen-IDs in `main.py:ensure_roles` weichen vom Baseline-Seed ab (siehe A.1). | `main.py:44-61` |
| I-1 | Inkonsistenz (teilweise bewusst) | **Lösch- und Strukturrechte uneinheitlich:** writer darf Protokolle, Termine, Traktanden, Vorlagen**elemente**, Protokollblöcke, Word-Import-Dokumente und Dokument-Komponenten löschen. Nur admin darf Vorlagen, Elementdefinitionen (die writer aber **anlegen** darf), Zyklen, Snapshot-Zeilen sowie Dokumentvorlagen, Brands und Assets löschen. Vorlagen legt nur admin an, ihre Elemente bearbeitet writer. **Korrektur:** Der Teil zu Vorlagenelementen und Bausteinen ist eine **bewusste Entscheidung des Umbaus `4a8161d7`** (writer gestaltet Inhalt und Erscheinungsbild bestehender Vorlagen, admin legt Vorlagen an, löscht sie und verwaltet ihre Einstellungen) und wird mit `templates.edit` abgebildet (E-10). Tatsächlich inkonsistent bleibt: Elementdefinitionen darf writer anlegen, aber nur admin löschen. Außerdem ist die Teilnehmer-Zuordnung einer Vorlage im Backend writer (`participants.py:260-267`), laut Commit und UI aber „Admin-Sache“. | `templates.py:74-369`, `document_studio.py` |
| I-2 | Inkonsistenz | `kassier` gilt in `access_service` als privilegiert (alle Protokolle inkl. Entwürfe, alle Dateien), in `require_writer` nicht. Fachlich plausibel (Bussen aus Sitzungen), aber nirgends dokumentiert. | `access_service.py:31,48,116` |
| I-3 | Inkonsistenz | Der Termin-Kalenderfeed ist nur für writer/admin freigegeben, obwohl alle Rollen Termine lesen dürfen. | `calendar_feed_service.py:36-43` |
| I-4 | Inkonsistenz | Ein Admin kann sich selbst herabstufen oder deaktivieren, solange ein anderer Admin existiert. Gegen den eigenen Rechteverlust gibt es keinen gesonderten Schutz. | `user_service.py:167-193` |
| T-1 | Testlücke | Es gibt **keinen Routen-Inventartest**, der verlangt, dass jede Route eine Rechteprüfung hat. Weil die Prüfungen inline statt als `Depends` laufen, sieht Dependency-Introspektion sie nicht. Nur `test_document_api.py:181` prüft die Authentifizierung der Dokument-Routen. E2E hat keine `kassier`-Session (`frontend/e2e/auth.ts`). | `backend/tests/`, `frontend/e2e/` |

**Bestehend vs. geplant:** Ein Konzept für eigene Rollen, granulare Rechte oder Gruppen gibt es
weder im Code noch in der Doku (`security-audit/`, `docs-site/`, `RUNBOOK.md`). Alles in diesem
Dokument über das feste Rollenmodell hinaus ist **neu**.

---

## B. Berechtigungskatalog

Leitlinie: Eine Permission bekommt nur, was **unabhängig vergeben werden muss** und sich
**einem Vereinsadmin in einem Satz erklären lässt**. Lesen, Schreiben, Verwalten, Löschen und
Exportieren sind nur dort getrennt, wo heute schon getrennt wird oder ein Sicherheitsgrund besteht.
Löschen ist grundsätzlich Teil von „bearbeiten“ bzw. „verwalten“. Für irreversible Fälle gibt es
eine **Ressourcenregel**, keine eigene Permission (siehe E.3).

Die **Bereiche** sind nur visuelle Kategorien in der Oberfläche, keine Objekte.

| # | Key | Bezeichnung (de) | Beschreibung | Abgedeckte Funktionen | Feature | Sicherheit | Warum eigenständig |
|---|---|---|---|---|---|---|---|
| **Sitzungen & Protokolle** |||||||
| 1 | `meetings.read` | Sitzungen ansehen | Termine, abgeschlossene Protokolle, Traktanden, eigene Aufgaben ansehen, PDFs exportieren | `GET /events`, `/protocols` (abgeschlossen bzw. zugewiesen), `/agenda-items`, `/templates` (lesen), `/cycle-configs`, Dokument-Export und -Vorschau, Managed Documents lesen, Aufgaben-Kalenderfeed, Statistik (eigene Zeile), Bild- und Dateizugriff innerhalb lesbarer Protokolle | – | niedrig | Grundrecht jedes Mitglieds. Ohne dieses Recht sieht man nur sein Profil. |
| 2 | `meetings.read_drafts` | Entwürfe ansehen | Auch laufende und nicht abgeschlossene Protokolle und alle Aufgaben sehen | Protokolle aller Status, alle Protokoll-Dateien, keine Einschränkung durch Teilnehmer-Zuordnung | – | mittel | Heute schon getrennt (kassier sieht Entwürfe, reader nicht). Realer Fall: Kassier, Revisor oder Vorstand liest mit, ohne zu schreiben. |
| 3 | `meetings.edit` | Sitzungen bearbeiten | Termine, Protokolle, Traktanden, Aufgaben und Listen anlegen, bearbeiten, abschließen, löschen (auch abgeschlossene Protokolle, E-5); Word-Import | alle heutigen `require_writer`-Routen in events, agenda_items, protocols, protocol_elements, todos, lists, word_import, table_snapshots (rekonstruieren), Kollaborations-WS (Schreiben), Termin-Kalenderfeed, Entwürfe ohne Wasserzeichen; Dokument-Studio `require_edit` für Dokumentvorlagen, die keiner Sitzungsvorlage gehören | – | mittel | Kernrolle „Protokollführung“. Enthält fachlich `read_drafts` (siehe D.4 *Implikationen*). |
| 4 | `templates.edit` | Vorlagen gestalten | Inhalt und Erscheinungsbild **bestehender** Sitzungsvorlagen bearbeiten: Traktanden und Bausteine, Bibliothek „Meine Bausteine“, PDF- und Einladungsgestaltung der Vorlage samt Veröffentlichung | Vorlagenelemente (`POST/PATCH/DELETE /template-elements`, `/detach`, `/behavior`), Elementdefinitionen anlegen/ändern, `/document-studio/session-templates/*`, Publish eigener Sitzungsvorlagen-Gestaltungen, Dokument-Komponenten | – | mittel (Änderungen an geteilten Bausteinen wirken „überall“) | Bildet die Entscheidung des Umbaus `4a8161d7` ab. Trennbar von `meetings.edit`: Realer Fall: Die Protokollführung soll Sitzungen schreiben, aber nicht die Vorlage ändern, die alle künftigen Sitzungen prägt. Standardrolle Schreiber hat beides, also keine Rechteänderung. |
| 5 | `templates.manage` | Vorlagen verwalten | Sitzungsvorlagen anlegen, duplizieren, löschen und konfigurieren; Zyklen, Aufgabenpakete, Tag-Konfiguration und historische Listenstände verwalten | `POST/PATCH/DELETE /templates`, Bussentarif, `/cycle-configs` schreiben, `/task-packages`, Elementdefinitionen löschen, `tag_config` schreiben, Snapshot-Zeilen korrigieren | – | mittel | Heute admin-only. Ändert die Struktur aller künftigen Sitzungen. Realer Fall: ein Vorstand pflegt Vorlagen, hat aber keine Benutzerverwaltung. |
| **Teilnehmende** |||||||
| 6 | `participants.manage` | Teilnehmende verwalten | Teilnehmende inkl. Kontaktdaten ansehen, anlegen, bearbeiten, importieren und Vorlagen zuordnen | `/participants` (ohne Login-Felder), CSV-Import, Zuordnung zu Vorlagen (steuert damit die Sicht eingeschränkter Leser!), Personendaten in Dokumenten (`personal_data`), Quelle `participants` | – | **hoch** (Personendaten, steuert Protokollzugriff) | Datenschutz: Kontaktdaten sind sensibler als Protokolle. Realer Fall: die Protokollführung soll keine Adressen pflegen. |
| **Finanzen** (Feature `finance`) |||||||
| 7 | `finances.read` | Kassenbuch ansehen | Konten, Buchungen und Saldi ansehen | `GET /finance/*`, Finanzdaten in Dokumenten | finance | mittel | Heute dürfen alle Rollen lesen, buchen aber nur kassier/admin. Transparenz für Mitglieder ist eine eigene Entscheidung [E-3]. |
| 8 | `finances.manage` | Finanzen verwalten | Buchungen, Konten und Bussen erfassen, ändern, löschen | `require_finance_write`-Routen (finance.py, fines.py) | finance | **hoch** | Geldwerte Buchungen. Klassische Kassier-Trennung. |
| **Auswertungen** |||||||
| 9 | `reports.personal` | Personenbezogene Daten aller ansehen | Bussen und Anwesenheit **aller** Personen sehen | `require_all_fines_read`, Bussen im Protokoll, `PER_PERSON_ROLES` in der Statistik | (Bussen: finance) | mittel (PRIV-001) | Ersetzt **zwei** heutige Sonderlisten, die schon identisch sind (`writer/kassier/admin`). Ohne das Recht gilt: nur eigene Bussen und eigene Statistik. |
| **Dateien & Fotos** |||||||
| 10 | `files.manage` | Dateien & Fotos verwalten | Dateien, Fotogalerie und Alben verwalten, öffentliche Freigabelinks und Albumfreigaben an Partner | files.py, gallery_upload_route.py, share_links.py | – | **hoch** (öffentliche Links) | Heute writer. Upload und Veröffentlichung nach außen gehören zusammen [E-6: öffentliche Links eventuell separat]. |
| **Abgabebox** (Feature `abgabebox`) |||||||
| 11 | `submissions.read` | Abgaben ansehen | Eingereichte Abgaben und Dateien ansehen | `require_abgabebox_read` | abgabebox | mittel | Nur nötig, solange alle Rollen Abgaben lesen sollen. **Kandidat zum Streichen** [E-4]. |
| 12 | `submissions.manage` | Abgaben verwalten | Abgabe-Aufträge und Upload-Links anlegen, prüfen, löschen | `require_abgabebox_write` | abgabebox | **hoch** (öffentliche Upload-Links) | Erzeugt öffentliche Zugänge nach außen. |
| **Administration** |||||||
| 13 | `settings.manage` | Einstellungen verwalten | Vereinsprofil, Datenschutz, Aufbewahrung, Prüfdomain, Corporate Design; Dokumentvorlagen veröffentlichen und zuweisen; Aktivitätsprotokoll und Speicher einsehen | tenants.py (PATCH), privacy_settings, retention, document_verification, document-settings, Dokument-Studio `require_publish`/`require_brand`, activity, storage | – | **hoch** | Wirkt auf den ganzen Verein und auf die Datenaufbewahrung. Trennbar von der Benutzerverwaltung. |
| 14 | `access.manage` | Benutzer & Rollen verwalten | Logins, Rollen und Rollenzuweisungen verwalten, MFA anderer zurücksetzen | users.py, Login- und Rollenfelder in participants.py, Rollen-API (neu), `mfa_service._managed_user` | – | **kritisch** | Wer Rollen vergibt, kontrolliert alle anderen Rechte. Deshalb gelten Schutzregeln (E.2). |
| 15 | `data.export` | Datenexporte | Gesamtexport des Vereins und Personendaten-Auskunft für andere Personen | tenant_data_export.py (plus `mfa_verified`), `POST /users/{id}/personal-data` | – | **kritisch** | Massenabfluss personenbezogener Daten, nicht umkehrbar. Realer Fall: mehrere Vorstände administrieren, aber nur eine Person darf exportieren. |

**Immer erlaubt, ohne Permission** (Regel „eigene Daten“): eigenes Profil, Passwort, MFA,
Sprache, eigene Bussen, eigene Aufgaben, eigene Kalenderfeeds, eigener Datenexport
(rate-limitiert). Ein Benutzer ohne jede Rolle hat genau diese Rechte.

**Bewusst _nicht_ als Permission** (geprüft und verworfen):

| Verworfene Idee | Grund |
|---|---|
| `minutes.*` getrennt von `events.*` | Termine und Protokolle werden in hocX von denselben Leuten gepflegt und sind über Vorlagen und Zyklen eng verknüpft. Eine Trennung bringt Verwaltungsaufwand ohne Kontrollgewinn. |
| `*.delete` je Bereich | Kein realer Fall, in dem jemand bearbeiten, aber nicht löschen darf. Auch abgeschlossene Protokolle darf weiter löschen, wer `meetings.edit` hat (E-5). |
| `*.export` je Bereich | Ein PDF-Export zeigt nur, was man ohnehin lesen darf (`documents/context.py`). Nur der **Massen**export ist eigenständig (`data.export`). |
| `lists.*` | Listen werden ausschließlich im Protokollkontext gepflegt (Snapshots). |
| `documents.design` / `documents.publish` | Gestalten = `templates.edit`/`meetings.edit` (heute writer), Veröffentlichen und Brand = `settings.manage` (heute admin). Ein eigener „Layouter“ ist kein realistischer Vereinsfall [Annahme]. |
| `users.manage` + `roles.manage` getrennt | Wer Rollen zuweist, kann sich über eine passende Rolle jedes Recht holen, auch mit der Teilmengenregel innerhalb seiner eigenen Rechte. Die Trennung wäre Scheinsicherheit. |
| `audit.read` | Das Aktivitätsprotokoll ist Teil der Vereinsadministration und gehört zu `settings.manage`. |
| `statistics.read` | Basis-Statistik ist für alle mit `meetings.read` lesbar. Das Sensible daran deckt `reports.personal`. |
| Plattform-Rechte (`owner`/`support`) | Bleiben **außerhalb** des Mandanten-RBAC (`core/admin_security.py`). |
| Abgabebox-Öffentlich | Das Token-Modell bleibt (`link_scope.py`). |

Nach den Entscheidungen E-4 und E-10 sind es **15 Permissions**. Würde `templates.edit` wieder in
`meetings.edit` aufgehen, wären es 14 (siehe Abschnitt 9).

---

## C. Rollenmatrix

Jeder Mandant bekommt vier **Standardrollen**. Sie werden beim Anlegen des Mandanten und
einmalig per Migration erzeugt und haben einen festen `system_key`. In Phase 1 bilden sie die
heutigen Rollen **exakt** ab.

| Permission | Mitglied (`reader`) | Kassier (`kassier`) | Schreiber (`writer`) | Administrator (`admin`) |
|---|:-:|:-:|:-:|:-:|
| `meetings.read` | ✔ | ✔ | ✔ | ✔ |
| `meetings.read_drafts` | – | ✔ | ✔ | ✔ |
| `meetings.edit` | – | – | ✔ | ✔ |
| `templates.edit` | – | – | ✔ | ✔ |
| `templates.manage` | – | – | – | ✔ |
| `participants.manage` | – | – | ✔ | ✔ |
| `finances.read` | ✔ ¹ | ✔ | ✔ | ✔ |
| `finances.manage` | – | ✔ | – | ✔ |
| `reports.personal` | – | ✔ | ✔ | ✔ |
| `files.manage` | – | – | ✔ | ✔ |
| `submissions.read` | ✔ ² | ✔ | ✔ | ✔ |
| `submissions.manage` | – | – | ✔ | ✔ |
| `settings.manage` | – | – | – | ✔ |
| `access.manage` | – | – | – | ✔ (gesperrt) |
| `data.export` | – | – | – | ✔ |

¹ So steht es heute im Code. Ob es fachlich so bleiben soll, ist offen [E-3].
² Bleibt bewusst so (E-4).

**Bewertung der Migration der heutigen Rollen:**

- Die Zuordnung ist 1:1: `app_user.role_id` → genau eine `user_role`-Zeile auf die Standardrolle
  mit gleichem `system_key`. **Kein Konto gewinnt oder verliert ein Recht.**
- „Administrator“ ist eine **Systemrolle**: nicht löschbar, Permissions nicht änderbar (immer
  alle). So gibt es in jedem Mandanten verlässlich eine voll handlungsfähige Rolle, und der
  Plattform-Admin (`admin_tenant_user_service.set_role`) kann sie im Notfall zuweisen.
- „Mitglied“, „Kassier“ und „Schreiber“ sind **Vorlagen**. Der Mandant darf sie umbenennen und ihre
  Permissions ändern, aber nicht löschen, solange ihnen Benutzer zugewiesen sind [E-1: oder ganz
  unveränderlich].
- Der heutige Sonderfall „writer + kassier = admin“ verschwindet: Eine Person bekommt einfach
  beide Rollen.
- Neue Teilnehmende ohne Login bekommen **keine** Rolle. Neue Logins bekommen standardmäßig
  „Mitglied“, so wie heute `participant_service.py:21` und `schemas/user.py:103`.

---

## D. Datenbankdesign

### D.1 Tabellen

Es kommen **vier** neue Tabellen hinzu, zwei alte fallen am Ende weg (`role`, `app_user.role_id`).

```sql
-- Systemdefinierte Permissions (Lookup, global, wie `feature`).
-- Einzige Quelle der Wahrheit für die Keys ist der Code-Katalog (E.1); diese Tabelle
-- existiert nur für die referenzielle Integrität und wird per Migration gepflegt.
CREATE TABLE permission (
    key text PRIMARY KEY CHECK (key ~ '^[a-z_]+\.[a-z_]+$')
);

-- Mandanteneigene Rollen
CREATE TABLE tenant_role (
    id          bigint PRIMARY KEY GENERATED BY DEFAULT AS IDENTITY,
    public_id   uuid NOT NULL UNIQUE DEFAULT uuidv7(),
    tenant_id   bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    name        text NOT NULL CHECK (btrim(name) <> ''),
    description text,
    system_key  text CHECK (system_key IN ('admin','writer','kassier','reader')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id)                                   -- Ziel der Composite-FKs
);
CREATE UNIQUE INDEX uq_tenant_role_name   ON tenant_role (tenant_id, lower(name));
CREATE UNIQUE INDEX uq_tenant_role_system ON tenant_role (tenant_id, system_key) WHERE system_key IS NOT NULL;

-- Rolle → Permission (Untertabelle; RLS über die Elterntabelle, Muster 0134)
CREATE TABLE tenant_role_permission (
    role_id        bigint NOT NULL REFERENCES tenant_role(id) ON DELETE CASCADE,
    permission_key text   NOT NULL REFERENCES permission(key) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_key)
);

-- Benutzer → Rolle. Mit eigener tenant_id, damit Composite-FKs Zuweisungen über
-- Mandantengrenzen hinweg schon in der DB unmöglich machen.
CREATE TABLE user_role (
    tenant_id  bigint NOT NULL,
    user_id    bigint NOT NULL,
    role_id    bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, role_id),
    FOREIGN KEY (tenant_id, user_id) REFERENCES app_user (tenant_id, id)    ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, role_id) REFERENCES tenant_role (tenant_id, id) ON DELETE RESTRICT
);
CREATE INDEX idx_user_role_role ON user_role (role_id);
-- Voraussetzung: CREATE UNIQUE INDEX uq_app_user_tenant_id ON app_user (tenant_id, id);
```

Begründungen:

- **Warum `permission` als Tabelle statt nur Code?** Ohne FK könnten Tippfehler oder
  Altlasten-Keys stillschweigend in `tenant_role_permission` landen. Das Muster ist dasselbe wie bei
  `feature`. Die Kosten: eine Zeile in der Migration, die eine neue Permission einführt. Ein Test
  prüft, dass Katalog und Tabelle übereinstimmen (H).
- **Warum eine neue Tabelle `tenant_role` statt `role` zu erweitern?** `role` ist global, hat
  `smallint`-IDs, `hocx_app` hat dort volle DML-Rechte, und eine Spalte `tenant_id` dürfte nicht
  `NULL` sein (SECURITY-RULES §2.1). Eine neue Tabelle mit RLS ist sauberer, und `role` lässt sich
  am Ende ersatzlos löschen.
- **`ON DELETE RESTRICT` auf `user_role.role_id`:** Eine Rolle mit zugewiesenen Benutzern lässt
  sich nicht versehentlich löschen. Die Oberfläche verlangt zuerst eine Umverteilung.
- **Bewusst ohne** `public_id` auf `user_role`/`tenant_role_permission` (Verknüpfungstabellen ohne
  eigene API-Identität), ohne Rollen-Hierarchie, ohne Gruppen, ohne direkte User-Permissions.

### D.2 RLS

- `tenant_role`, `user_role`: Policy `tenant_isolation` mit `BASE` (`0132_tenant_rls.py`).
- `tenant_role_permission`: Policy über `tenant_role` (Muster `0134_child_table_rls.py`,
  Eintrag in `CHILD_TABLES`).
- `permission`: global ohne RLS, wie `feature`. **`hocx_app` bekommt nur `SELECT`**
  (abweichend von den Default-Privileges, SECURITY-RULES §2.4), weil die Keys nur per Migration
  entstehen.
- `tests/test_tenant_rls.py` erfasst die neuen Tabellen automatisch.

### D.3 Effizienz

Die Rechte werden **pro Request** mitgeladen, in derselben Funktion, die heute schon Rolle und
Features lädt (`core/security.py:160`). Dazu kommt **eine** zusätzliche indexgestützte Abfrage:

```sql
SELECT DISTINCT rp.permission_key
FROM user_role ur JOIN tenant_role_permission rp ON rp.role_id = ur.role_id
WHERE ur.user_id = :user_id
```

Einen Cache gibt es nicht. Damit wirken Rechteänderungen sofort, auch in laufenden Sessions,
Render-Jobs, Kalenderfeeds und der WebSocket (30-s-Recheck). Einen Session-Widerruf beim
Rollenwechsel braucht es weiterhin nicht. Bei Lastproblemen ließen sich `user_role` und die
Permissions als ein `JOIN` mit der bestehenden Rollenabfrage zusammenlegen.

### D.4 Implikationen (bewusst minimal)

Ein fester, im Code definierter Satz: `meetings.edit ⇒ meetings.read_drafts ⇒ meetings.read`,
`templates.manage ⇒ templates.edit ⇒ meetings.read`,
`finances.manage ⇒ finances.read`, `submissions.manage ⇒ submissions.read`. Die Erweiterung
geschieht **beim Laden** (eine Zeile im Code, keine Tabelle). So kann keine unsinnige Rolle
entstehen („bearbeiten, aber nicht lesen“), und die Oberfläche zeigt die mitgemeinte
Permission als automatisch gesetzt an. Das ist **keine Rollenvererbung**: Rollen kennen einander
nicht.

### D.5 Migrationsstrategie (DB)

1. **Revision A (additiv):** die vier Tabellen und RLS anlegen, `permission` seeden, pro Mandant
   die vier Standardrollen mit den Permissions aus Abschnitt C seeden,
   `user_role` aus `app_user.role_id` befüllen (alle Konten, auch solche ohne Login, damit kein
   Recht beim späteren Aktivieren eines Logins verloren geht). Die Revision ist idempotent und
   prüft am Ende: Anzahl `user_role` = Anzahl `app_user` und jeder Mandant hat einen Admin. Sonst
   bricht sie ab.
2. **Übergangszeit:** `app_user.role_id` bleibt bestehen und wird beim Schreiben mitgepflegt.
   Er gilt als „primäre“ Standardrolle, was das Rollback und alte Exportformate ermöglicht.
   Gelesen wird nur noch über `user_role`.
3. **Revision B (nach Freischaltung eigener Rollen und einer Stabilitätsphase):**
   `app_user.role_id`, `idx_app_user_tenant_role` und `role` entfernen,
   `main.py:ensure_roles` löschen. Bereits produktiv gelaufene Migrationen werden nicht verändert
   (SECURITY-RULES §2.5).

---

## E. Backend-Architektur

### E.1 Katalog als einzige Quelle

`app/core/permissions.py` (neu):

```python
class P(StrEnum):
    MEETINGS_READ = "meetings.read"
    MEETINGS_READ_DRAFTS = "meetings.read_drafts"
    ...

@dataclass(frozen=True)
class PermissionDef:
    area: str                 # nur Anzeige-Kategorie (meetings, participants, finances, …)
    feature: str | None = None  # gebuchtes Modul, ohne das die Permission wirkungslos ist
    requires_mfa: bool = False  # access.manage, settings.manage, data.export
    implies: tuple[P, ...] = ()

CATALOG: dict[P, PermissionDef] = {...}
```

Das Frontend bekommt die Keys über eine generierte Datei
(`frontend/lib/permissions.generated.ts`, per Sync-Skript wie `sync-i18n-config.py` bzw.
`element_types_generated.py`). Ein CI-Check stellt sicher, dass die Datei aktuell ist. Labels und
Beschreibungen sind i18n-Keys, keine DB-Spalten.

### E.2 Funktionsberechtigung: eine Prüffunktion

```python
# core/security.py
@dataclass
class CurrentUser:
    ...
    permissions: frozenset[str] = frozenset()   # bereits um Implikationen erweitert
    role_names: tuple[str, ...] = ()            # nur Anzeige

    def can(self, permission: P) -> bool:
        definition = CATALOG[permission]
        if definition.feature and definition.feature not in self.current_tenant_features:
            return False
        return permission in self.permissions

def require_permission(user: CurrentUser, permission: P) -> CurrentUser:
    if not user.can(permission):
        raise HTTPException(status_code=403, detail="Permission required")  # bewusst ohne Key
    return user
```

- **Default deny:** Ohne Rolle sind `permissions` leer. Ein unbekannter Key ist ein `KeyError`
  und fällt damit im Test auf, nicht erst in Produktion.
- **Konvention bleibt:** Der Aufruf steht wie heute imperativ im Routenrumpf
  (SECURITY-RULES §1.3, *vor* dem Laden). Es gibt keinen neuen Dependency-Stil.
- **Feature-Gate eingebaut:** `require_feature` bleibt für Fälle ohne Permission (z. B.
  `custom_domain`). Für Permissions mit `feature` ist es eingebaut, sodass die bisherigen Doppelaufrufe
  (`require_feature(...)` plus Rollenprüfung) entfallen.
- **MFA:** `_requires_mfa` (`core/security.py:198`) wird zu „hat eine Permission mit
  `requires_mfa`“. Mit den Standardrollen ist das exakt die heutige Regel (nur admin).
- **Übergangsschicht (Phase 1):** `require_reader/writer/admin/finance_*/abgabebox_*/all_fines_read`
  bleiben als dünne Wrapper bestehen und bilden so ab:

  | Alt | Neu (Phase 1) |
  |---|---|
  | `require_reader` | `meetings.read` |
  | `require_writer` | `meetings.edit` (in templates.py für Vorlagenelemente und Elementdefinitionen sowie in document_studio session-templates schon in Phase 1 `templates.edit`; mit den Standardrollen ist das gleichwertig) |
  | `require_admin` | `access.manage` |
  | `require_finance_read` / `_write` | `finances.read` / `finances.manage` |
  | `require_abgabebox_read` / `_write` | `submissions.read` / `submissions.manage` |
  | `require_all_fines_read`, `PER_PERSON_ROLES` | `reports.personal` |
  | `access_service`: `role in {admin,writer,kassier}` | `meetings.read_drafts` |
  | `role == "reader"` (eingeschränkt) | `not meetings.read_drafts` |
  | `documents/permissions.py` capabilities | export/view → `meetings.read`, edit → `meetings.edit` bzw. `templates.edit` (Sitzungsvorlagen-Gestaltung), publish/brand → `settings.manage`, Publish eigener Sitzungsvorlagen-Gestaltung → `templates.edit`, personal_data → `participants.manage`, unmark_drafts → `meetings.edit` |
  | `calendar_feed_service.can_subscribe` | events → `meetings.edit` (I-3, später `meetings.read`), todos → `meetings.read` |

  Mit nur vier Standardrollen ist das **beweisbar verhaltensgleich** (Test in H). In Phase 2
  werden die Aufrufstellen bereichsweise auf die fachlich richtige Permission umgestellt
  (z. B. participants.py auf `participants.manage`, `require_admin` je nach Route auf
  `templates.manage`, `settings.manage`, `access.manage` oder `data.export`). **Erst danach** sind
  eigene Rollen sinnvoll; sonst würde etwa eine Rolle mit nur `participants.manage` an
  `require_writer` scheitern.

### E.3 Ressourcenberechtigung: feste Regeln statt Policy-Engine

Die Funktionsberechtigung beantwortet „darf er das grundsätzlich?“. Die Ressourcenregeln
beantworten „an diesem Datensatz?“. Sie bleiben gezielte Funktionen in `access_service.py`, wie
heute:

| Regel | Umsetzung |
|---|---|
| R1 Mandant | RLS und `get_by_public_id(..., tenant_id=…)`. **Jede** Permission gilt nur im eigenen Mandanten. |
| R2 Protokollstatus | Nicht abgeschlossene Protokolle nur mit `meetings.read_drafts` (behebt S-2 zentral in `can_read_protocol`). |
| R3 Teilnehmer-Zuordnung | Benutzer **ohne** `meetings.read_drafts`, die `user_*_access`-Zeilen haben, sehen nur Zugeordnetes (heute `_is_restricted_reader`, nur die Bedingung ändert sich). Gilt auch für Statistik, `todos/blocks` und `next-session` (behebt S-3). |
| R4 Eigene Daten | eigene Bussen, Aufgaben, Feeds, Profil: ohne Permission, nur `user_id == actor` |
| R5 Gesperrte Protokolle | unverändert |
| R6 Partneralben | Eigentümer verwaltet; ein akzeptierter Partner mit `files.manage` darf bewusst beitragen und „Beste“ markieren (E-7), aber nicht einladen und nicht freigeben |
| R7 Systemvorlagen | unverändert nur Plattform |

Das wird kein allgemeines Policy-System: Es gibt nur diese sieben Regeln, und neue Regeln
entstehen nur mit einem konkreten fachlichen Fall.

### E.4 Schutzregeln der Rechteverwaltung

Alle Punkte gelten in `RoleService` (neu) und `UserService`, **auch für den Plattform-Admin-Pfad**
(`admin_tenant_user_service`, `admin_update_user`), so wie heute `guard_last_tenant_admin`
geteilt wird.

1. **Keine Rechteausweitung:** Ein Akteur darf nur Rollen zuweisen, entziehen, anlegen oder
   ändern, deren Permissions eine **Teilmenge seiner eigenen** effektiven Permissions sind. Er darf
   Benutzer nur dann bearbeiten (Passwort, Login, E-Mail, Rollen), wenn deren Permissions eine
   Teilmenge seiner eigenen sind (Schutz vor Konto-Übernahme Höherberechtigter). Ausnahme: der
   Plattform-Admin.
2. **Letzter handlungsfähiger Admin:** „Handlungsfähig“ heißt aktiv, Login erlaubt und
   `access.manage` effektiv vorhanden. Jede Operation, die diese Menge verkleinern kann
   (Rolle entziehen, Rolle ändern, Rolle löschen, deaktivieren, Login entziehen, löschen), prüft
   danach `count ≥ 1`. Weil „Administrator“ unveränderlich ist, reduziert sich das praktisch auf
   „mindestens ein aktiver Benutzer mit der Systemrolle Administrator“. Das ist einfach zu zählen
   und zu erklären.
3. **Nebenläufigkeit:** Alle diese Operationen sperren zuerst die Mandantenzeile
   (`SELECT … FROM tenant WHERE id = :t FOR UPDATE`) und prüfen erst danach. So werden
   Admin-Änderungen pro Mandant serialisiert, was S-6 behebt. Die Kosten sind vernachlässigbar,
   weil das selten passiert.
4. **Selbstentzug:** Ein Akteur kann sich `access.manage` nicht selbst entziehen (Oberfläche und
   Backend, 409). Ein anderer Admin muss das tun. Das behebt I-4 [E-2].
5. **Systemrolle:** „Administrator“ ist nicht löschbar, nicht umbenennbar und hat immer alle
   Permissions. Standardrollen sind nicht löschbar, solange Benutzer sie haben.
6. **MFA:** Wer durch eine Zuweisung eine Permission mit `requires_mfa` erhält, ohne einen
   MFA-Faktor zu haben, wird beim nächsten Request abgewiesen (heutiges Verhalten bei der
   Beförderung zum Admin). Die Oberfläche warnt vor der Zuweisung.
7. **Audit:** Rollen- und Zuweisungsänderungen gehen ins bestehende `audit_log` (alter und neuer
   Permission-Satz).

### E.5 Hintergrundjobs und indirekte Aktionen

- Jobs ohne Benutzer (Wartungsloops, Worker) brauchen keine Permission. Sie laufen bewusst
  mandantenübergreifend (SECURITY-RULES §1.4) und werden nicht verändert.
- Jobs **im Namen** eines Benutzers (Render-Jobs, Kalenderfeeds, WebSocket) bauen den Benutzer
  schon heute neu auf. Sie müssen nur `permissions` mitladen, dann gelten Rechteänderungen sofort.
- `documents/service.py:377` (`user is None` ⇒ darf schreiben) bleibt als Systempfad, wird aber
  dokumentiert.

### E.6 API (neu, nur `access.manage`)

```
GET    /api/roles                     Rollen inkl. Permissions und Anzahl Benutzer
POST   /api/roles                     anlegen  {name, description, permissions[]}
PATCH  /api/roles/{id}                ändern
DELETE /api/roles/{id}                löschen (409 bei Zuweisungen oder Systemrolle)
GET    /api/roles/catalog             Katalog (Keys, Bereich, Feature, MFA, Implikationen)
PUT    /api/users/{id}/roles          {role_ids[]} – setzt die Rollen vollständig
```

Session (`/api/auth/session`): `permissions: string[]`, `roles: {id,name}[]`. `current_role`
bleibt in der Übergangszeit für alte Frontend-Stellen erhalten.

---

## F. Frontend-Architektur

1. **Ein Helfer:** `frontend/lib/permissions.ts` mit `can(session, "meetings.edit")` und den
   generierten Keys als Union-Typ. Alle rund 30 `current_role`-Vergleiche werden ersetzt
   (`dashboard-permissions.ts` und `app-shell-nav.ts` zuerst, dann die Seiten). Es ist nur
   Benutzerführung; das Backend prüft unabhängig.
2. **Rollenverwaltung** als Tab „Rollen“ in der Benutzerverwaltung (`app/users/page.tsx`,
   `RouteTabs`):
   - `DataTable` mit Rollen (Name, Beschreibung, Anzahl Benutzer, Badge „Standard“/„System“),
     Zeilenaktionen über `ActionMenu`.
   - `Modal` „Rolle bearbeiten“: Name, Beschreibung, darunter die Permissions **nach Bereich
     gruppiert** (`.field-stack` mit Überschrift pro Bereich, Checkbox, ein Satz Erklärung).
     Permissions ungebuchter Features erscheinen ausgegraut mit Hinweis „Modul nicht gebucht“.
     Implizierte Permissions sind automatisch gesetzt und gesperrt. Permissions, die der Akteur
     selbst nicht hat, sind gesperrt (E.4.1). Bei `requires_mfa` gibt es ein Schloss-Symbol mit
     Hinweis.
   - Löschen über `useConfirm({ tone: "danger" })`.
3. **Benutzer bearbeiten:** Die Radiogruppe (`user-management.tsx:343-355`) wird zu
   `SearchableMultiSelect` „Rollen“.
4. **Effektive Rechte:** Im Benutzer-Modal ein Abschnitt „Effektive Berechtigungen“: Liste nach
   Bereich und je Permission, **durch welche Rolle** sie kommt (reine Ableitung aus
   Katalog, Rollen und Features, keine eigene API).
5. **i18n** (Pflicht laut CLAUDE.md): Namespace `roles` mit `roles.areas.<area>`,
   `roles.permissions.<key>.label/description`, `roles.system.<system_key>.name/description` in
   allen Locales. Die Namen der Standardrollen werden **beim Anzeigen** übersetzt, solange der
   Mandant sie nicht umbenannt hat (`name` leer bzw. gleich dem Default ⇒ i18n-Text). Die
   bestehenden `roleDescriptions.*`/`roles.*` werden ersetzt.
6. **Plattform-Admin:** `admin-tenant-settings-modal.tsx` und die Benutzerzeilen im Admin-Panel
   zeigen die Rollen an. „Zum Administrator machen“ bleibt als Notfallaktion (Systemrolle
   zuweisen). Weitere Rollenverwaltung im Admin-Panel ist nicht nötig.
7. Design: nur bestehende Bausteine (`DataTable`, `Modal`, `ActionMenu`, `Badge`,
   `SearchableMultiSelect`, `useConfirm`), neue Optik als Klassen mit dem Präfix `roles-…`.

---

## G. Migrationsplan (priorisiert)

| Phase | Inhalt | Rechteänderung? | Aufwand (grob) |
|---|---|---|---|
| **0 – Sofortfixes** (vom RBAC unabhängig) | S-1 Statistik-Cache-Key um Aufrufer-Scope ergänzen. S-2 Statusprüfung in `can_read_protocol`. S-3 Zuordnungs-Prüfung in den genannten Routen. S-6 Mandantensperre beim Letzter-Admin-Check. S-4/S-5 sperren (E-12). S-10 `ensure_roles`-IDs angleichen. Je ein Regressionstest. | **ja, Schließen von Lecks**, jeweils einzeln freizugeben | 1–2 PT |
| **1 – Äquivalenzmigration** | Revision A (D.5). Katalog `core/permissions.py`. `CurrentUser.permissions`. Alte Helfer als Wrapper (E.2-Tabelle). Session liefert `permissions`. Kein UI-Umbau. Export und Import: Rollen per `system_key` (`tenant_transfer_common.py`, `tenant_import_service.py`; alte Formate mit `role_code` bleiben importierbar). Neue Mandanten bekommen die Standardrollen (`admin_tenant_service`). | **nein** (bewiesen durch Äquivalenztest) | 3–4 PT |
| **2 – Aufrufstellen fachlich schneiden** | Bereichsweise PRs: Routen und Services von `require_writer`/`require_admin` auf die passende Permission umstellen. Rollen-Literale (A.2-Liste) entfernen. `documents/permissions.py`, `catalog.py` und `bindings.py` auf Permissions umstellen. Routen-Inventartest. Rest von **I-1** (E-10 a/b) und **I-3** nach Entscheidung. | nur bei Inkonsistenzen, einzeln freizugeben | 4–6 PT |
| **3 – Frontend auf `can()`** | `lib/permissions.ts`, alle `current_role`-Stellen ersetzen | nein | 2–3 PT |
| **4 – Rollenverwaltung freischalten** | Rollen-API, Schutzregeln E.4, UI (F.2–F.4), i18n, Audit, Doku `docs-site/docs/benutzer/rollen.md` | nein (neue Möglichkeit) | 4–5 PT |
| **5 – Aufräumen** | Revision B, Wrapper und `current_role` entfernen | nein | 1 PT |

**Summe: ca. 15–21 Personentage**, davon etwa 40 % Tests. [Annahme: Schätzung ohne
Abstimmungsaufwand.]

Schutz gegen unbeabsichtigte Änderungen:

- Phase 1 ist **rein additiv**. Ein Rollback ist ein Code-Revert; `role_id` existiert noch und wird
  mitgepflegt.
- In Phase 1 ist die Rollenverwaltungs-API **nicht vorhanden**. Damit kann niemand eigene Rollen
  bauen, bevor Phase 2 die Aufrufstellen fachlich korrekt geschnitten hat.
- Jede Abweichung vom Ist-Verhalten (Phase 0 und 2) ist ein eigener, benannter Punkt mit eigener
  Freigabe.
- Vor Revision A erzeugt ein Diagnose-Skript pro Mandant „Benutzer je Rolle“. Dieselbe Abfrage
  nach der Migration über `user_role` muss identisch sein.
- Neue Permissions in künftigen Features: Die Migration, die sie einführt, ordnet sie explizit den
  **Standardrollen** zu (per `system_key`, auch wenn der Mandant die Rolle bearbeitet hat; es wird
  nur hinzugefügt). Eigene Rollen bekommen sie **nicht** (default deny). Die Oberfläche markiert
  neue Permissions eine Zeit lang als „neu“.

---

## H. Teststrategie

| Ebene | Test | Ort |
|---|---|---|
| Katalog | Enum = `permission`-Tabelle = generierte TS-Datei. Jede Permission hat i18n-Keys in allen Locales. Implikationen sind azyklisch. | `tests/test_permission_catalog.py`, `check-i18n-completeness.py` |
| **Äquivalenz (Phase 1)** | Für jede der vier Rollen und jede Feature-Kombination liefern alter Helfer (eingefrorene Kopie der heutigen Logik im Test) und neue Permission-Prüfung dasselbe Ergebnis. Gilt auch für `access_service`, `can_subscribe`, `PER_PERSON_ROLES` und `documents/permissions.capabilities`. | `tests/test_rbac_equivalence.py` |
| Migration | Revision A auf einer DB mit Mandanten mit allen vier Rollen: Zählungen identisch, jeder Mandant hat einen Admin. Idempotenz. Downgrade. | `tests/test_migration_rbac.py` |
| Routen-Inventar | AST-Scan aller Routen: jede Route ruft `require_permission`/einen Wrapper auf **oder** steht mit Begründung in einer Allowlist (öffentlich, „eigene Daten“). Behebt T-1. | `tests/test_route_permission_inventory.py` |
| Mandantentrennung | Rolle oder Benutzer aus Mandant B per ID zuweisen oder lesen ⇒ 404. Composite-FK verhindert den mandantenfremden `INSERT` in `user_role`. RLS auf allen neuen Tabellen. | `test_tenant_rls.py`, neue Fälle |
| Rechteausweitung | Ein Nicht-Admin mit `access.manage`-Teilmenge versucht, eine Rolle mit mehr Rechten zuzuweisen, anzulegen oder zu ändern ⇒ 403. Ein Benutzer ändert seine eigene Rolle ⇒ 403. Das Passwort eines Höherberechtigten setzen ⇒ 403. | `tests/test_role_service.py` |
| Letzter Admin | Entziehen, Löschen, Deaktivieren, Löschen der Rolle ⇒ 409. **Nebenläufig:** zwei Threads stufen sich gegenseitig herab ⇒ genau einer scheitert. | `test_user_service.py` erweitern |
| Wirkung auf Sessions | Rolle entziehen ⇒ der nächste Request derselben Session ist 403, ebenso der Kalenderfeed und der Render-Job; die WebSocket verliert das Schreibrecht beim Recheck. | `test_auth_access.py`, `test_calendar_feeds.py` |
| Mehrfachrollen | Mitglied + Kassier ergibt die Vereinigungsmenge. Das Entziehen einer Rolle entfernt nur deren Anteil. | `test_role_service.py` |
| Ressourcenregeln | R2 Entwurf per ID für ein Mitglied ⇒ 404. R3 eingeschränkt + Statistik/todos/next-session. R4 eigene Bussen. | bestehende Audit-Tests erweitern |
| Bestand | Die bestehenden Suites (`test_role_permissions.py`, `test_permission_routes.py`, `test_feature_gating.py`, `test_privacy_statistics.py`, …) bleiben **unverändert grün**. Sie sind die zweite Absicherung der Äquivalenz. | — |
| E2E | `roles-and-tenants.spec.ts` bekommt eine **Kassier-Session**. Neuer Spec: Rolle anlegen, zuweisen, die Navigation passt sich an, Entzug wirkt ohne neues Login. | `frontend/e2e/` |
| Frontend | `can()`-Unit-Tests, Rollen-Modal (Sperren, Implikationen, ungebuchtes Feature) | vitest |

---

## I. Aufwand und Alternativen

| Kriterium | 1. Festes Rollenmodell weiterentwickeln | **2. Schlankes DB-RBAC (Empfehlung)** | 3. Komplexes System (ABAC/Policy-Engine, Gruppen, Vererbung, User-Overrides) |
|---|---|---|---|
| Beschreibung | Fünfte Rolle `writer_kassier`, Literale zentralisieren, Lecks fixen | 15 Permissions, mandanteneigene Rollen, Mehrfachrollen, feste Ressourcenregeln | z. B. OPA/Cerbos/Casbin, Policies als Daten, Gruppen, Scopes je Objekt |
| Implementierung | 4–6 PT | 15–21 PT | 40–80 PT + Betrieb einer Policy-Komponente |
| Wartung | **steigt mit jeder Kombination** (Rollenexplosion: writer+kassier, kassier+Dateien, …), Literale bleiben verstreut | gering: neue Funktion = 1 Enum-Eintrag + 1 Migrationszeile + i18n, oder Wiederverwendung einer bestehenden Permission | hoch: Policies debuggen, eine zweite Wahrheit neben dem Code, Schulung |
| Admin-Verständlichkeit | sehr hoch, aber starr | hoch (4 Standardrollen genügen den meisten Vereinen, Anpassung optional) | niedrig für Vereine |
| Sicherheit | gut, wenn die Lecks behoben werden; keine Delegation „nur Teilnehmende pflegen“ möglich | gut: Default deny, Teilmengenregel, DB-Composite-FKs, Äquivalenz bewiesen | theoretisch am feinsten, praktisch fehleranfälliger durch Komplexität |
| Erweiterbarkeit | schlecht (jeder neue Fall = neue Rolle + Codeänderung überall) | gut, ausreichend für alle aktuell bekannten Fälle | sehr hoch, aber für hocX nicht benötigt |
| Risiko | gering | mittel, durch Phase 1 (Äquivalenz) beherrscht | hoch |

**Empfehlung: Variante 2.** Begründung: Der einzige dokumentierte Bedarf, der heute nicht
abgedeckt ist (writer + kassier), zwingt bei Variante 1 schon zur ersten Kombinationsrolle. Variante
2 kostet etwa dreimal so viel, beseitigt aber die verstreuten Literale (der größte laufende
Wartungs- und Fehlerposten, siehe A.2/A.5) und deckt die realistischen Delegationsfälle eines
Vereins ab. Variante 3 löst Probleme, die hocX nicht hat.

**Falls das Budget knapp ist:** Phase 0 und Phase 1 bis 3 liefern bereits den größten Teil des
Nutzens (zentrale Prüfung, keine Literale, Mehrfachrollen über die Standardrollen). Phase 4
(eigene Rollen in der Oberfläche) lässt sich verschieben. Mehrfachrollen lassen sich dann zunächst
nur mit den vier Standardrollen zuweisen.

---

## 9. Kritische Selbstprüfung (und Vereinfachungen, die schon eingearbeitet sind)

| Frage | Ergebnis |
|---|---|
| Was lässt sich zusammenlegen? | Schon zusammengelegt: Termine + Protokolle + Traktanden + Aufgaben + Listen → `meetings.edit`; Bausteine + Bibliothek + Vorlagen- und Dokumentgestaltung → `templates.edit`. Alle Bussen + personenbezogene Statistik → `reports.personal`. Benutzer + Rollen → `access.manage`. Aktivitätsprotokoll, Brand und Dokument-Publishing → `settings.manage`. `submissions.read` bleibt nach E-4. Ein weiterer Kandidat wäre `finances.read` in `meetings.read` (E-3). |
| Was ist eventuell unnötig? | `templates.edit`: Es ließe sich in `meetings.edit` zusammenlegen (14 Permissions). Ich behalte es, weil der Umbau „Vorlagen“ zu einem eigenen Bereich macht und Änderungen an geteilten Bausteinen alle künftigen Sitzungen betreffen. `data.export`: Wenn jeder Admin exportieren darf und man die Trennung nicht braucht, geht es in `access.manage` auf (E-8). `meetings.read_drafts` ist nur wegen kassier nötig. Fällt dessen Entwurfszugriff weg, entfällt es (E-9). Ich empfehle, beide zu behalten, weil sie heutiges Verhalten abbilden. |
| Welche Tabellen lassen sich vermeiden? | `permission` wäre verzichtbar (CHECK oder App-Validierung). Ich behalte sie für die FK-Integrität, weil sie fast nichts kostet. Keine Gruppen-, Override-, Policy- oder Rollenhierarchie-Tabellen. `user_template_access`/`user_protocol_access` werden nicht angefasst. |
| Was wird weiterverwendet? | `app_user`, Feature-Gating, RLS-Muster, `access_service`, `guard_last_tenant_admin` (erweitert), Audit-Log, Per-Request-Laden in `build_current_user`, Neuaufbau in Jobs, bestehende UI-Bausteine, Testfactories (`make_current_user` bekommt `permissions=`). |
| Wo droht unnötige Abstraktion? | Implikationen (D.4): Die feste Liste hat 3 Kanten. Wenn das stört, wäre die Alternative „Oberfläche erzwingt Mitauswahl“. Das Sync-Skript für den TS-Katalog ist eine weitere generierte Datei, entspricht aber dem bestehenden Muster. Alternativ wäre ein handgepflegter TS-Typ plus Test gegen `/api/roles/catalog` möglich. |
| Welche Sonderfälle rechtfertigen Regeln? | Nur R2 (Entwürfe), R3 (Teilnehmer-Zuordnung), R4 (eigene Daten) und R6 (Partneralben). Alles andere ist die Funktionsberechtigung. |
| Migrationsrisiken | (1) Phase 2 schneidet falsch und ein Benutzer verliert ein Recht. Dagegen helfen die Äquivalenztests pro Bereich und die unverändert grünen Bestandstests. (2) Ein eigener Rollenbau vor Phase 2 führt zu Fehlrechten, deshalb ist die API bis dahin nicht vorhanden. (3) Ein MFA-Lockout, wenn einer Rolle nachträglich `settings.manage` gegeben wird: Die Oberfläche warnt und zeigt die betroffenen Benutzer ohne MFA. (4) Export- und Importformate: Alte Formate mit `role_code` bleiben importierbar. |
| Verständlich für kleine Vereine? | Ja: Ohne Zutun bleibt alles wie heute (vier Rollen). Die einzige sichtbare Neuerung ist, dass man mehrere Rollen ankreuzen kann. Eigene Rollen sind optional. |

---

## 10. Offene fachliche Entscheidungen

Keine davon wird stillschweigend getroffen. Jede Entscheidung, die heutige Rechte ändert, kommt als
eigener Schritt. **Getroffen (2026-10-26):** E-4, E-5, E-7, E-10, E-12. **Noch offen:** E-1, E-2, E-3, E-6,
E-8, E-9, E-11 sowie die Teilfragen E-10 (a)/(b). Für alle offenen Punkte gilt die jeweilige Empfehlung erst nach Freigabe.

| # | Frage | Empfehlung |
|---|---|---|
| E-1 | Sollen Mandanten die Standardrollen Mitglied, Kassier und Schreiber umbenennen und anpassen dürfen? | Ja, aber nicht löschen. Administrator ist fest. |
| E-2 | Soll Selbstentzug von `access.manage` verboten werden (heute: Selbst-Herabstufung erlaubt, wenn ein anderer Admin existiert)? | Ja (verbieten). |
| E-3 | Sollen normale Mitglieder weiterhin das ganze Kassenbuch sehen (`finances.read` in „Mitglied“)? | Heutiges Verhalten beibehalten. Mandanten können es nach Phase 4 selbst entfernen. |
| E-4 | Sollen normale Mitglieder weiterhin **alle** Abgaben und Dateien sehen und herunterladen? | **Entschieden 2026-10-26: ja, bleibt so.** `submissions.read` bleibt in der Rolle „Mitglied“. |
| E-5 | Wer darf **abgeschlossene** Protokolle löschen (heute: writer)? | **Entschieden: bleibt so.** Wer `meetings.edit` hat, darf weiterhin auch abgeschlossene Protokolle löschen. Keine Ressourcenregel dafür. |
| E-6 | Öffentliche Freigabelinks als eigenes Recht (`files.share`)? | Nein, bei `files.manage` lassen. Erst trennen, wenn ein Kunde es verlangt. |
| E-7 | Partneralben: dürfen Partner Fotos beitragen und „Beste“ markieren (S-7)? | **Entschieden: ja, gewollt.** Bleibt so (R6), wird als Ausnahme zu SECURITY-RULES §1.2 dokumentiert. |
| E-8 | `data.export` eigenständig oder Teil von `access.manage`? | Eigenständig (kritisch, MFA). |
| E-9 | Soll `kassier` weiterhin Entwürfe und alle Protokoll-Dateien sehen (I-2)? | Ja, beibehalten (über `meetings.read_drafts`). |
| E-10 | Wie werden die Rechte des Vorlagen-Umbaus (`4a8161d7`, noch nicht gemergt) abgebildet? Der Umbau lässt writer Bausteine und Gestaltung bestehender Vorlagen bearbeiten; Anlegen, Löschen und Einstellungen bleiben admin. | **Entschieden: so übernehmen.** Abgebildet durch `templates.edit` (writer) und `templates.manage` (admin). Ohne Rechteänderung. Offen bleibt nur: (a) Elementdefinitionen löschen. Vorschlag: zu `templates.edit`, denn wer Bausteine der Bibliothek anlegen darf, soll sie auch entfernen dürfen; das wäre eine kleine **Rechteerweiterung** für writer. (b) Teilnehmer-Zuordnung einer Vorlage: Backend writer, UI und Commit „Admin-Sache“. Vorschlag: bleibt `participants.manage` (Schreiber hat es), die UI wird angeglichen. |
| E-11 | Termin-Kalenderfeed für alle mit `meetings.read` (I-3)? | Ja. |
| E-12 | S-4/S-5: Teilnehmerliste und Listen-Snapshots für Mitglieder sperren? | **Entschieden: ja, sperren (Phase 0).** Teilnehmerquelle `/documents/sources/participants` nur mit `participants.manage` oder `meetings.edit`, Listen-Snapshots nur mit `meetings.edit`. |

---

## 11. Empfehlung

1. **Phase 0 zuerst und getrennt freigeben.** Vor allem S-1 (Statistik-Cache) und S-2 (Entwürfe per
   ID) sind heute schon echte Datenschutzlücken.
2. **Variante 2 (schlankes DB-RBAC)** mit 15 Permissions, vier Standardrollen, Mehrfachrollen
   und vier kleinen Tabellen umsetzen, in der Reihenfolge der Phasen 1 → 5.
3. Die offenen Entscheidungen (E-1, E-2, E-3, E-6, E-8, E-9, E-11, E-10 a/b) vor Phase 2 klären. Phase 1
   hängt von keiner davon ab.
4. Beginn der Umsetzung erst **nach dem Merge** von `feat/document-canvas-fidelity`.

---

## 12. Umsetzungsstand (2026-10-26)

Umgesetzt wurden alle Phasen 0-5 in einem Branch, nach dem Merge des Vorlagen-Umbaus (PR #16).
Für die bei Freigabe noch offenen Entscheidungen gilt jeweils die Empfehlung aus Abschnitt 10:
E-1 (Standardrollen umbenennbar und anpassbar, nicht löschbar), E-2 (kein Selbstentzug), E-3
(Mitglieder sehen das Kassenbuch weiter), E-6 (keine eigene Berechtigung für Freigabelinks), E-8
(`data.export` eigenständig), E-9 (Kassier liest Entwürfe), E-10 a (Elementdefinitionen löschen
mit `templates.edit`), E-10 b (Teilnehmer-Zuordnung bleibt `participants.manage`), E-11
(Termin-Abo mit `meetings.read`).

| Phase | Umsetzung |
|---|---|
| 0 | S-1 Cache-Key mit Sicht des Aufrufers (`statistics.py`); S-2 Status in `can_read_protocol`; S-3 `protocol_visibility` für Traktanden, `todos/blocks`, `next-session` und `_get_readable_protocol_or_404` für die lesenden Protokoll-Unterrouten; S-4/S-5 Teilnehmerquelle und Listen-Snapshots gesperrt (E-12); S-6 Mandantensperre + Savepoint (`role_service.admin_guard`); S-10 `ensure_roles` entfernt |
| 1 | `permissions/catalog.json` + `scripts/sync-permission-catalog.py` (CI `--check`), `core/permissions.py`, `CurrentUser.permissions/can()`, `require_permission`, Migration `0156_rbac` (Tabellen, RLS, Trigger `trg_tenant_seed_roles`, Backfill mit Prüfung) |
| 2 | Alle Aufrufstellen fachlich geschnitten, alte Helfer und Rollen-Literale entfernt, `documents/permissions.py` auf Berechtigungen, Routen-Inventartest `tests/test_route_permission_inventory.py` |
| 3 | `frontend/lib/permissions.ts` (`can`, `canAny`, Rollennamen), alle `current_role`-Vergleiche ersetzt, Session liefert `permissions` und `roles` |
| 4 | Rollen-API (`api/routes/roles.py`), `services/role_service.py` mit Schutzregeln E.4, Seite `/users/roles`, Mehrfachrollen und effektive Berechtigungen in der Benutzerverwaltung (Desktop und Mobil), Plattform-Admin setzt Standardrollen, i18n `roles.*` in allen Locales, Audit `role.*`/`user.roles_changed`, Export-Format 9 (Rollen) mit Import alter Formate |
| 5 | Migration `0157_drop_legacy_role` (entfernt `app_user.role_id` und `role`; Downgrade stellt die höchste Standardrolle wieder her) |

Abweichungen vom Vorschlag, bewusst und ohne Rechteänderung für bestehende Konten:

- **Bezeichnungen der Standardrollen** bleiben die bisherigen (Admin, Schreiber, Kassier, Leser,
  `nav.roles.*`) statt «Mitglied/Administrator», damit sich für Nutzer nichts umbenennt.
- **Neue Teilnehmende ohne Login** bekommen wie bisher die Standardrolle Leser (statt keiner Rolle).
  Das ist gleichwertig zu vorher, und ein späterer Login braucht keinen Zusatzschritt.
- **Standardrolle Admin** hat keine Zeilen in `tenant_role_permission`, sie bekommt beim Laden immer alle
  Berechtigungen. Damit wirken künftige Berechtigungen automatisch, ohne Migration je Mandant.
- **Personendaten in Dokumenten** (Katalog-Zugriff `writer`) = `participants.manage` **oder**
  `meetings.edit`, so wie Anwesenheitslisten bisher für alle Schreibenden.
- **Aufgaben** (`ensure_can_read_todo`) folgen der Aufgabenliste: Wer nicht eingeschränkt ist,
  sieht Aufgaben auch aus nicht abgeschlossenen Protokollen (wie bisher in `GET /todos`).
  Eingeschränkte Leser sehen zusätzlich ihre eigenen Aufgaben.
- **Eigene Kalender-Abos** ansehen und löschen ohne Berechtigung (eigene Daten). Das Anlegen
  verlangt `meetings.read`.
- **Letzter Admin**: Geprüft wird «die Änderung senkt die Zahl der handlungsfähigen Admins von
  ≥ 1 auf 0». Ein Mandant, der schon vorher keinen Admin hatte, blockiert also keine anderen
  Änderungen. Löschungen prüfen vorab (`ensure_not_last_admin_removed`).
- **Plattform-Admin-Panel** setzt nur Standardrollen (`system_role` bzw. `AdminTenantUserGrant`).
  Ohne Änderung der Auswahl schickt das Formular keine Rolle, damit eigene Rollen beim Speichern
  erhalten bleiben.
- **Navigation «Import»** bleibt wie bisher in der Administration sichtbar (`templates.manage`).

Tests: `tests/test_rbac.py` (Äquivalenz der Standardrollen mit eingefrorener Alt-Logik,
Schutzregeln, Nebenläufigkeit, RLS, Composite-FK, Mehrfachrollen, Session-Wirkung, Phase-0-Lecks,
Rollen-API), `tests/test_route_permission_inventory.py`, angepasste Bestandstests,
`frontend/lib/permissions.test.ts`, `frontend/e2e/rbac-roles.spec.ts`.

