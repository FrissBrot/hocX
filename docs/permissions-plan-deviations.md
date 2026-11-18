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
  an dieselben Daten. **Entschieden 18.11.2026:** Leser/Kassier behalten `submissions.read` für alle
  (nur lesend).
- **Nicht nach Abgabe-Reichweite gefiltert (Phase 5):** Dateien-Übersicht, Galerie und
  `/api/stored-files/*` prüfen eingereichte Dateien weiterhin über `files.read`/`photos.read` (ohne
  Reichweite); ein reiner Prüfer ohne diese Rechte sieht dort nichts. Mails «Abgabe zurückgezogen»
  gehen weiter nur an `submissions.manage` (gilt für alle), Dashboard-Fristen ebenfalls nur mit
  `submissions.manage`.
- **Export/Import:** Rollen tragen im Gesamtexport `permission_scopes`; der Import übernimmt sie
  (sonst würde «nur zugewiesene» still zu «alle»). Ältere Exporte ohne Feld: «alle» wie vorher.
  **OFFEN:** Prüfer-Zuweisungen (`resource_assignment`) sind nicht im Export – nach einem Import
  sieht ein «nur zugewiesene»-Prüfer nichts, bis man sie neu zuweist (sichere Richtung).

## Phase 7 – Rollen-Dialog, Vorlagen, «Ansehen als …»

- **Rollen-Dialog:** Gruppen, implizierte Rechte (angehakt, gesperrt, «Ergibt sich aus …»),
  Reichweiten-Auswahl und Hilfetexte (`roles.permissions.<bereich>.<aktion>.description`) gab es
  im Kern schon (Phase 3/4); Phase 7 vereinheitlicht nur: implizierte Rechte sind optisch
  abgesetzt (gestrichelt, Klasse `roles-permission-option-implied`), Hinweistext «Ergibt sich aus»
  statt «Automatisch enthalten in», «Effektive Berechtigungen» auf der Personenseite zeigen
  «Nur zugewiesene». Kein Hilfetext im Katalog selbst – der Katalog enthält bewusst keine Texte
  (Phase 1), die Übersetzungen sind die Quelle.
- **Rollen-Vorlagen als Frontend-Konstante** (`frontend/lib/role-templates.ts`), keine Lese-Route,
  keine Migration. Begründung: Vorlagen gewähren nichts (gespeichert wird über `POST /api/roles`,
  `role_service` prüft wie immer), Name/Beschreibung sind Übersetzungen (`roles.templates.*`),
  eine Backend-Kopie wäre eine zweite Quelle ohne Sicherheitsgewinn. `PermissionKey`-Typen und
  `role-templates.test.ts` sichern, dass nur Katalog-Rechte vorkommen.
- **Auswahl der Vorlagen-Rechte** (Vorschlag, fachlich prüfen): keine Vorlage enthält
  MFA-/Administrationsrechte (dafür die Standardrolle Admin). Präsident: Sitzungen bearbeiten +
  Protokolle freigeben, Vorlagen gestalten, Kontaktdaten, Kassenbuch, Personenbezogene Daten aller,
  Dateien/Fotos/Abgaben ansehen. Aktuar: Sitzungen bearbeiten **ohne** Freigeben (Vier-Augen mit
  dem Präsidenten), Vorlagen und Teilnehmende verwalten, Dateien/Fotos verwalten, öffentlich
  teilen. Kassier: wie die Standardrolle, aber **ohne** `submissions.read` (siehe OFFEN in Phase 4)
  und mit `participants.read`. Revisor: nur lesend inkl. Finanzen, ohne «eigene Pendenzen
  erledigen» (rein lesender Zugang). Abgabe-Prüfer: `submissions.review` (+ `submissions.read`)
  «Nur zugewiesene», Sitzungen ansehen. Mitglied: exakt `SYSTEM_ROLE_PERMISSIONS.reader`.
- **Nur eigene Rechte:** Eine Vorlage übernimmt nur Rechte, die die handelnde Person selbst hat
  (inkl. Implikationen; eigene «nur zugewiesene» bleiben zugewiesen). Die übrigen sind im Formular
  wie bisher ausgegraut («Gesperrt: diese Berechtigung hast du selbst nicht»), die Auswahl zeigt
  die Zahl, das Formular die Namen.
- **«Ansehen als …» ohne Sitzungswechsel:** `GET /api/users/{id}/access-preview`
  (`access.manage`, damit MFA wie Administration) berechnet mit `build_current_user` dasselbe wie
  ein Request des Kontos (Rechte, Reichweiten, Module, MFA-Pflicht, sichtbare Abgaben) – kein
  Token, keine Sitzung, kein Schreibweg. Schutzregeln: nur eigener Mandant (fremd/unbekannt 404),
  nur Konten mit Teilmenge der eigenen Rechte inkl. Reichweite
  (`role_service.ensure_can_manage_account`, sonst 403 `permission_not_held`; innerhalb des
  Mandanten ist die Existenz eines Kontos kein Geheimnis). Verlauf `user.access_previewed`, auch
  abgelehnte Versuche (`outcome=failure`). Audit auf einer GET-Route wie bei
  `admin.user_viewed`.
- **Navigation der Vorschau im Frontend:** Das Backend liefert Rechte und Module; die Menüpunkte
  berechnet `buildNav` – dieselbe Funktion wie die echte Seitenleiste (Signatur auf
  `NavSession = Pick<SessionInfo, "permissions" | "current_tenant">` gelockert). Eine zweite
  Navigationslogik im Backend würde auseinanderlaufen.
- **Ort:** Knopf «Ansehen als …» auf der Personenseite (Abschnitt Login), nicht in der Tabelle
  Zugriff › Wer hat Zugriff (Zeilen führen dorthin). Die Vorschau zeigt den gespeicherten Stand.
- **Security-Review (18.11.2026):** Titel zugewiesener Abgabe-Aufträge zeigt die Vorschau nur,
  soweit der Akteur sie selbst lesen darf (hat er selbst nur «zugewiesene»: Schnittmenge; die
  Teilmengen-Regel vergleicht Rechte und Reichweiten, nicht einzelne Zuweisungen). Die Anzahl
  bleibt die des Kontos. Bewusst offen: der Knopf auf der Personenseite prüft nur Rechte, nicht
  Reichweiten – ein Akteur mit nur «zugewiesene» kann klicken und bekommt dann die 403-Meldung
  (nur Benutzerführung). Audit auf GET: per Top-Level-Navigation von fremder Seite liessen sich
  Verlaufseinträge erzeugen, aber keine Daten lesen – als Lese-Audit gewollt.
- Keine Migration in Phase 7.

## Entscheide 18.11.2026 (Abschluss Phasen 4–7)

- Standardrollen Leser und Kassier behalten «Abgaben ansehen» für **alle** Aufträge (nur lesend,
  Menüpunkt «Abgaben» sichtbar).
- Rollen-Vorlagen wie vorgeschlagen freigegeben.
- Word-Import bleibt vom Vier-Augen-Prinzip ausgenommen (historische, extern genehmigte Protokolle).
- Benutzerlimit: offene Einladungen zählen schon beim Einladen mit
  (`user_limit_service.pending_invite_count`); die eigene Einladung der Person nicht.
## Phase 5 – Kontext-Freigaben

- **Tabelle** `context_visibility` (Migration 0196) statt `context_visibility(id, context_type,
  context_id, audience, group_id, file_filter, show_in_gallery)`: Spalten `module`
  (`abgabe|protokoll|album`, wie `stored_file.context_type`), `context_id` (NULL = Modul-Standard,
  sonst Abgabe-Auftrag, mandantengleicher Fremdschlüssel mit ON DELETE CASCADE), `audience`,
  `file_filter`, `updated_by/at`. Werte englisch wie die Rechte-Schlüssel: `nur_rolle` →
  `role_only`, `alle_teilnehmenden` → `all_participants`, `einreichende_eigene` →
  `own_submissions`; `alle|bilder` → `all|images`. Kein `group_id` («Gruppen» = Rollen; Rollen
  geben Rechte bereits über Ebene 1), kein `show_in_gallery` (siehe unten).
- **Overrides nur je Abgabe-Auftrag.** Alben haben keinen eigenen Kontext (`context_id` ist bei
  `album` leer, Phase 2), Protokolle keine Freigabe. Die Datenbank erzwingt das per CHECK.
- **Protokolle fest «nur Rolle»** (CHECK): Protokoll-Dateien folgen dem Protokoll (Entwurf,
  Teilnehmer-Zuordnung); eine Freigabe an alle würde den Entwurfsschutz umgehen. In der Oberfläche
  steht das Modul gesperrt mit Erklärung.
- **Seed – Entscheid gegen den Plan-Standard.** Plan: Abgaben → alle Teilnehmenden (nur Bilder),
  Alben → alle Teilnehmenden. Das wäre eine **Rechteausweitung**: die Standardrollen Leser und
  Kassier haben kein `photos.read` (Phase 3) und sähen damit neu alle Galerie- und Abgabe-Fotos über
  `/api/stored-files/*`; dasselbe gilt für eigene Rollen ohne Foto-Recht. Deshalb starten **alle
  Module für alle Mandanten mit `role_only`** (bestehende per Migration, neue per Trigger
  `trg_tenant_seed_context_visibility` wie die Standardrollen; fehlt eine Zeile, gilt im Code
  dasselbe). Die Dateitypen sind wie im Plan vorbelegt (Abgaben nur Bilder, Alben alle), so dass ein
  Verein nur noch die Zielgruppe wählen muss. Test: `test_default_seed_changes_nothing`.
- **«Alle Teilnehmenden»** = jedes Konto mit Login des Mandanten. Teilnehmende ohne Login haben keine
  Session und sehen nie etwas. Die Datei-Routen (`/api/stored-files/*`) verlangen wie bisher
  `meetings.read` als Grundrecht (alle Standardrollen haben es); ein Konto ganz ohne
  `meetings.read` sieht auch Freigaben nicht – bewusst keine schwächere Prüfung in der route-map.
- **«Nur eigene Einreichung»** = Elemente, für die das Konto verantwortlich ist: Quelle der
  Verantwortlichen der Abgabe oder zugewiesene Aufgabe des Elements – dieselbe Regel wie der
  persönliche Abgabe-Link (`submission_access_service._still_responsible`).
- **Zentrale Prüfung:** `context_visibility_service.context_grant_allows(db, user, stored_file)`
  (Override → Modul-Standard → `DEFAULTS`), additiv in `access_service.ensure_can_read_stored_file`:
  sie wird nur gefragt, wenn die Rollenprüfung mit 403/404 ablehnt. Damit gelten Inhalt, Vorschau,
  Download und Metadaten gleich. Schreibrouten (Tags, Aufnahmedatum, Alben), öffentliche Links und
  ZIP-Downloads von Aufträgen verlangen weiter Rollenrechte – Freigaben geben nie Schreibzugriff und
  keine öffentlichen Ableitungen. Zurückgezogene/gelöschte Einreichungen sind nie freigegeben.
- **`visible_files_query(db, user, module=…)`** liefert die per Freigabe sichtbaren Datei-IDs als eine
  Abfrage (nur saubere Dateien des eigenen Mandanten); «nur eigene» wird je Auftrag in Python
  aufgelöst (Verantwortliche kommen aus Terminfeldern und Listenspalten).
- **«Fotos aus Abgaben»** ist eine eigene Seite `/photos/submissions`
  (`GET /api/context-files/submission-photos`, `meetings.read`), nur Bilder; der Menüpunkt erscheint
  unter Ablage, wenn der Verein Abgabe-Dateien freigibt (Session `shared_submission_photos`) und das
  Konto kein `photos.read` hat. Dokumente aus Freigaben («alle Dateitypen») sind per Einzelabruf
  lesbar, aber nicht in dieser Ansicht gelistet.
- **«In Fotogalerie anzeigen» weggelassen.** Die Galerie (`/photos`, `GET /api/files`) ist eine
  Mandanten-Gesamtsicht hinter `photos.read` mit Alben, Analyse, Duplikaten und Zeitstrahl;
  Freigabe-Fotos dort für Konten ohne `photos.read` einzublenden, hätte jede dieser Abfragen um
  einen zweiten Rechteweg erweitert. Abgabe-Fotos kommen ohnehin über die bestehende Album-Regel
  (Abgabe → Album) in die Galerie; wer sie ohne Foto-Recht sehen soll, nutzt «Fotos aus Abgaben».
- **UI:** Modul-Standards als Karte «Sichtbarkeit von Dateien» im bestehenden Reiter Organisation ›
  Datenschutz (`settings.manage`), Override im Auftragsformular (`submissions.manage`, Feld
  `file_visibility` in Anlegen/Ändern/Lesen; `mode = default|custom`). Die mobile Abgabe-Ansicht
  zeigt das Feld nicht, lässt einen gesetzten Override beim Speichern aber unverändert.
- **Audit:** `context_visibility.changed` mit `before`/`after` (Modul: `entity_type = tenant`;
  Auftrag: `entity_type = submission_assignment`, «default» = Standard). Unveränderte Werte schreiben
  keinen Eintrag. Kategorie im Verlauf: «Sichtbarkeit von Dateien».
- **Security-Review Phase 4 (Befund «mittel») mit umgesetzt:** Wer `submissions.read` nur «zugewiesene»
  hat, sieht Abgabe-Dateien anderer Aufträge auch über `files.read`/`photos.read` nicht mehr –
  Einzelabruf (`ensure_can_read_stored_file`, 404 wie in den Abgabe-Routen), Galerie/Ablage
  (`GET /api/files`), Zeitstrahl, Duplikate/Ähnliche, globale Suche und das Erstellen öffentlicher
  Links (`readable_assignment_ids`/`abgabe_scope_clause`). Additiv: eine Datei, die zusätzlich in
  einem Protokoll steckt, bleibt in Listen sichtbar (Einzelabruf prüft dann das Protokoll);
  Kontext-Freigaben wirken auch für diese Konten. Konten mit `submissions.read` «alle», mit
  `submissions.manage` oder ganz ohne `submissions.read` verlieren nichts. Album-Mitgliedschaft
  zählt nicht als zusätzlicher Kontext (Abgabe-Fotos kommen automatisch in Alben) – sichere Richtung.
  Mehrfachaktionen (Tags, Löschen, Fotos ins Album) lehnen Dateien nicht lesbarer Aufträge mit 404 ab.
  **OFFEN:** `GET /api/files/tags`, `GET /api/files/stats` und die Album-Übersicht (Cover/Namen der
  automatischen Abgabe-Alben) filtern nicht nach Reichweite (Tags enthalten die Herkunft «Abgabe:
  <Titel>», Statistik nur Zahlen).
- **Security-Review Phase 5 (18.11.2026), behoben:** (1) `gallery_image` enthält auch Ablage-Dokumente
  und Direkt-Uploads zu Abgaben – die Album-Freigabe gilt nur für Zeilen ohne Abgabe-Bezug, deren
  Hauptdatei ein Bild ist (plus Live-Clip); für Abgabe-Uploads gilt allein die Abgabe-Regel inkl.
  «zurückgezogen». (2) Schreib- und Weitergabewege prüfen mit `allow_context_grant=False` nur
  Rollenrechte: Tags, Aufnahmedatum, Bildbaustein im Document Studio. (3) Download `part=video|both`
  (Live-Clip, ZIP) nur mit Rollenrechten. (4) `visible_files_query` berechnet «eigene» je
  Dateityp-Gruppe getrennt.
