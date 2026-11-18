# Abweichungen Plan ↔ Code (Plan «Berechtigungen, Datei-Kontexte und Kontext-Freigaben»)

Der Plan entstand ohne Einblick in den Code. Hier steht je Phase, wo die Umsetzung bewusst davon
abweicht und warum. «OFFEN» markiert fachliche Punkte, die noch eine Entscheidung brauchen.

## Phase 0 – Inventar und Sicherheitsnetz

- Inventar wird **generiert** (`docs/permissions-inventory.md` aus `scripts/sync-route-permissions.py`)
  statt von Hand gepflegt; CI/Pre-Commit prüfen mit `--check`, dass es aktuell ist.
- Matrix-Test: statische Matrix (`permissions/permission-matrix.json`, Standardrolle × Route) plus
  Laufzeitprüfung aller **GET**-Routen (`tests/test_permission_matrix.py`). Schreibende Routen
  prüft der Laufzeittest nicht (Body-Validierung vor der Rechteprüfung); sie deckt die statische
  Matrix ab, deren Diff jede Änderung zeigt.

## Phase 1 – Katalog und can()

- Bereits vorhanden und nicht neu gebaut: Katalog im Code (`permissions/catalog.json`, mit
  `implies`, MFA, Feature-Bindung; generiert nach Backend/Frontend), zentrale Prüfung
  `require_permission`/`require_any_permission`/`user.can` (= `can()` des Plans), Texte als
  Übersetzungen `roles.permissions.*` (Vollständigkeit prüft `sync-permission-catalog.py --check`).
- «Unbekannter Schlüssel ⇒ Fehler»: Die Prüfung nimmt nur das generierte Enum `P` an – ein
  unbekannter Schlüssel ist in jeder Umgebung ein sofortiger Fehler (nicht nur in Dev/Test).
- «Kein direkter Rollen-Check»: erzwungen durch die Sicherheitsregel `role-code-comparison`
  (Hook, Pre-Commit, CI); Suche am 18.11.2026 ohne Fund.
- Schlüssel bleiben englisch (`files.manage`, `meetings.edit` …), Entscheid vom 18.11.2026.

## Phase 2 – Dateien bekommen einen Kontext

- Kontexte `protokoll | abgabe | album | ablage` wie im Plan; `context_id` = Protokoll bzw.
  Abgabe-Auftrag (bei Album/Ablage leer – Galerie-Fotos gehören zur Galerie, nicht zu einem
  bestimmten Album).
- **Eine Datei kann in mehreren Kontexten verwendet werden** (z. B. ein Galerie-Foto in einem
  Protokoll, ein eingereichtes Foto in der Galerie). Gespeichert wird der primäre Kontext
  (Herkunft, Priorität abgabe > protokoll > album > ablage); der **Zugriff gilt, wenn einer der
  verknüpften Kontexte ihn erlaubt** (additiv). Sonst verlören Protokoll-Leser den Zugriff auf
  eingebundene Galerie-Fotos.
- «Upload-Pfade setzen den Kontext explizit»: stattdessen setzt die Datenbank ihn beim Verknüpfen
  (Trigger auf `submission_upload_file`, `gallery_image`, `protocol_image`, `document_export`,
  `word_import_document`; Funktion `hocx_file_context`). Grund: Dateien legen auch die Abgabebox und
  der Foto-Worker an; ein Weg, der eine Stelle vergisst, ist so ausgeschlossen. Neue Dateien
  starten als «ablage».
- Dry-Run: `app.services.file_context_service.report(db, tenant_id=…)` berechnet die Zuordnung
  ohne zu schreiben (Zählung je Kontext, Liste der Ablage-Fälle, Abweichungen); reversibel über
  `alembic downgrade` (Zuordnung ist jederzeit aus den Verknüpfungen neu berechenbar).
- Pendenz-Anhänge, Dokumentregister und Exporte ohne Protokoll sind «ablage» – wie heute gelten
  für sie dieselben Regeln wie für die freie Ablage.
- Keine Verhaltensänderung: `access_service.ensure_can_read_stored_file` prüft unverändert; die
  Rechte je Kontext kommen in Phase 3 (Mapping ohne Rechteverlust) und 5 (Freigaben).

## Phase 3 – Neue Rechte und Rollen-Migration

- Zwölf neue Rechte (`meetings.approve`, `todos.complete_own`, `participants.read|contacts|export`,
  `fines.manage`, `files.read`, `photos.read|manage`, `sharing.public`, `submissions.review`,
  `activity.read`); Migration 0190 ordnet sie ohne Rechteverlust zu
  (`app.services.permission_mapping`, Probelauf `report(db, tenant_id=…)`).
- Mapping-Korrekturen gegenüber dem Plan: `participants.export` (Datenauskunft für andere) kommt
  aus `data.export`, nicht aus `participants.manage` – sonst bekämen Schreiber neu Personenexporte.
  `meetings.edit` bekommt kein `participants.read` (war vorher auch nicht nötig).
- `todos.complete_own` erhalten **alle** Rollen inkl. Leser; ohne das Recht ist ein Konto rein
  lesend (Entscheid 18.11.2026). Erlaubt nur Status/Erledigt-Datum, nur eigene Pendenzen.
- `sharing.public` verlangt **kein** MFA (Entscheid 18.11.2026); `participants.export` verlangt MFA.
- Vier-Augen-Prinzip pro Organisation wählbar (`tenant.four_eyes_protocols`, Migration 0191,
  Standard aus). Der Abschliessen-Knopf bleibt sichtbar; das Backend lehnt mit
  `four_eyes_required` ab und die Oberfläche zeigt die Meldung.
- «Gruppen» des Plans sind Rollen; keine Freigaben auf Ordnerebene.

## Ergänzung (nicht im Plan) – MFA je Rolle, Frist

- `tenant_role.require_mfa` (Migration 0192): Schalter im Rollen-Editor.
- Bestehende Konten (`app_user.first_login_at` gesetzt) haben 3 Tage Frist, wenn MFA für sie neu
  Pflicht wird; die Einrichtung erscheint bei jedem Login und lässt sich überspringen, in der App
  erinnert ein Hinweis. Keine Frist bei Pflicht wegen Administrationsrechten und für neue Konten.

## Security-Review Phase 3 (18.11.2026) – Entscheide

- **Word-Import** legt Protokolle abgeschlossen an und verlangt dafür `meetings.approve`. Das
  Vier-Augen-Prinzip gilt dort bewusst nicht: importiert werden ausserhalb von hocX genehmigte,
  historische Protokolle. Protokolle ohne Verfasser (Altbestand, gelöschtes Konto) kann jede Person
  mit `meetings.approve` abschliessen.
- **Öffentliche Links:** Bilder brauchen `photos.read`, Dokumente `files.read` – beim Erstellen je
  Datei, beim Auflisten und Widerrufen je Link (sonst öffnete die Token-URL Inhalte, die man im
  Verein nicht lesen darf). Album-Links brauchen `photos.read`.
- **Einzelabruf von Dateien** symmetrisch: `files.read` nur Dokumente, `photos.read` nur Bilder
  (Entwürfe-Leser wie bisher alles).
- **Personensuche** sucht ohne `participants.contacts` nicht in E-Mail-Adressen; ohne
  Verwaltungsrecht sind `login_enabled`/`notify_without_login` ausgeblendet.
- **MFA:** Ein Zurücksetzen des Faktors durch die Administration startet keine neue Frist.
  Das Rollen-Flag `require_mfa` steht im Audit (vorher/nachher) und überlebt Export/Import.
- **`activity.read`** verlangt MFA (wie vorher `settings.manage`).

## Phase 6 – Öffentliche Links

- **Keine physische Tabelle `public_links`.** Die Vereinheitlichung leistet das bestehende Register
  `backend/app/public_links` (jede Link-Art meldet sich dort, der Test `test_public_link_registry`
  erzwingt das) mit der Übersicht Organisation › Zugangslinks. Grund: Ein Umzug der Tokens aus
  `share_link`, `submission_link`, `calendar_feed`, `account_token`, `submission_access_token` in
  eine Tabelle hätte die Abgabebox (liest `submission_link` direkt, eigene Rolle) und alle
  öffentlichen Routen berührt, ohne für Vereine etwas zu ändern. Tokens bleiben unverändert.
- Freigabelinks für Dateien und Alben lassen sich **direkt in der Übersicht widerrufen** (gleiche
  Prüfung wie auf der Seite «Geteilte Links»: `sharing.public` plus Leserecht auf den Inhalt).
  Abgabe-Links, Kalender-Abos und Einladungen verwaltet weiter ihre eigene Seite (sie hängen an
  Aufträgen bzw. Personen).
- `sharing.public` ohne MFA (Entscheid 18.11.2026).

## Phase 8 – Nachvollziehbarkeit

- Kein eigenes `permission_audit_log`: alles läuft in den bestehenden Verlauf (`audit_log`,
  Organisation › Verlauf, mit Spaltenfiltern).
- Rollen: `role.created/updated/deleted` mit Rechten und Reichweiten vorher/nachher, inkl.
  `require_mfa`.
- Zuweisungen: `user.roles_changed` mit Rollen vorher/nachher, zentral in
  `role_service.set_user_roles` in derselben Transaktion (alle Wege: Zugriff, Konto anlegen/ändern,
  Mehrfachauswahl). Dafür kann `AuditService.log` ohne eigenen Commit schreiben.
- Öffentliche Links: `public_link.created/regenerated/revoked` (Freigabelinks und Abgabe-Links).
- Kontext-Freigaben (Phase 5) und Prüfer-Zuweisungen (Phase 4) protokollieren ihre eigenen Phasen.
## Phase 4 – Reichweite «zugewiesene» und Prüfer

- **Wo die Reichweite definiert ist:** im Katalog (`permissions/catalog.json`, Feld
  `scopes: ["all", "assigned"]`), vorerst nur `submissions.read` und `submissions.review`. Das
  Sync-Skript generiert `PermissionDef.scopes`/`SCOPED_PERMISSIONS` (Backend) und
  `PermissionInfo.scopes` (Frontend) und lehnt ab, dass ein Recht mit Reichweite eines ohne
  impliziert. Begründung: eine Quelle wie für alles andere am Recht; keine zweite Konstante je Seite.
  Die Datenbank sichert zusätzlich per CHECK, dass nur diese Rechte eine Reichweite tragen (ein
  neues Reichweiten-Recht braucht damit eine Migration – gewollt).
- **Speicherung:** `tenant_role_permission.scope` NULL = alle (alle Bestandszeilen, keine
  Datenmigration nötig), sonst `'assigned'`. Gespeichert wird wie bei den Rechten die aufgelöste
  Menge inkl. Implikationen.
- **Auflösung** (`core/permissions.py::resolve_scopes`, gespiegelt in `frontend/lib/permissions.ts`):
  je Rolle gilt ein Recht für alle, wenn es selbst «alle» hat oder ein Recht der Rolle es
  impliziert, das für alle gilt (Rechte ohne Reichweite wie `submissions.manage` immer). Ohne eigene
  Angabe erbt ein impliziertes Recht (review(assigned) ⇒ read(assigned)), ein nicht impliziertes
  gilt für alle. Je Konto: «nur zugewiesene», wenn keine Rolle das Recht für alle gibt
  (`CurrentUser.assigned_only`, auch in der Session `assigned_only` zur Benutzerführung).
- **Plan-Datenmodell** `resource_assignments(resource_type, resource_id, user_id, funktion)` →
  Tabelle `resource_assignment` mit `tenant_id`, `function` (`'reviewer'`), `created_by`; der
  mandantengleiche Fremdschlüssel (tenant_id, resource_id) → `submission_assignment` funktioniert,
  solange `resource_type` nur `submission_assignment` kennt (neu: `uq_submission_assignment_tenant_id`).
  Ein weiterer Typ braucht dann Trigger statt Fremdschlüssel.
- **Prüfer verwalten:** über `reviewer_ids` in Create/Update/Read des Auftrags (kein eigener
  Endpunkt), nur mit `submissions.manage`; Kandidaten über `GET /api/submission-assignments/reviewer-candidates`
  (aktive Konten mit Login des Mandanten, nur `submissions.manage` – unabhängig von
  `participants.read`). Bereits zugewiesene Prüfer dürfen nach Entzug des Logins stehen bleiben
  (Speichern scheitert sonst), neu zuweisen lassen sich nur Konten mit Login. Audit
  `submission_assignment.reviewers_changed`.
- **Durchsetzung:** alle Lese-Routen der Abgaben (Liste, Fortschritt, Elemente, Upload-Protokoll,
  ZIP, Datei-Inhalt/Vorschau/Metadaten) und Dokumente aus Abgaben (`document_read_service`) filtern
  nach Reichweite; fremd = 404 wie fremder Mandant, bei Dateien vor der Scan-Status-Antwort.
  Schliessen/Öffnen mit `submissions.review` nur zugewiesen: nicht lesbar 404, lesbar (Lesen für
  alle) aber nicht zugewiesen 403.
- **Schwächere Prüfung (route-map):** `GET /api/submission-assignments` verlangt `submissions.read`
  statt `submissions.manage` (Lesezugang für Prüfer). Fortschritt, Elemente, Dateien und ZIP waren
  schon mit `submissions.read` lesbar; die Liste ist jetzt nach Reichweite gefiltert.
- **Sichtbare Änderung:** Die Standardrollen Leser und Kassier haben `submissions.read` (alle) seit
  Phase 0 – sie sehen jetzt den Menüpunkt «Abgaben» (nur lesen). Vorher kamen sie nur über die API
  an dieselben Daten. **OFFEN:** soll `submissions.read` bei Leser/Kassier bleiben oder auf «nur
  zugewiesene» bzw. weg? (Entscheid des Produktverantwortlichen; heute unverändert «alle».)
- **Nicht nach Abgabe-Reichweite gefiltert (Phase 5):** Dateien-Übersicht, Galerie und
  `/api/stored-files/*` prüfen eingereichte Dateien weiterhin über `files.read`/`photos.read` (ohne
  Reichweite); ein reiner Prüfer ohne diese Rechte sieht dort nichts. Mails «Abgabe zurückgezogen»
  gehen weiter nur an `submissions.manage` (gilt für alle), Dashboard-Fristen ebenfalls nur mit
  `submissions.manage`.
- **Export/Import:** Rollen tragen im Gesamtexport `permission_scopes`; der Import übernimmt sie
  (sonst würde «nur zugewiesene» still zu «alle»). Ältere Exporte ohne Feld: «alle» wie vorher.
  **OFFEN:** Prüfer-Zuweisungen (`resource_assignment`) sind nicht im Export – nach einem Import
  sieht ein «nur zugewiesene»-Prüfer nichts, bis man sie neu zuweist (sichere Richtung).
