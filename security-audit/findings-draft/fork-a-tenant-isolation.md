# Fork A — Tenant-Isolation Deep-Dive: Ergebnisse

Scope: Invariante I3 (`SECURITY_MODEL.md`) — Caller von `public_id_service.get_by_public_id`/
`resolve_internal_id`/`resolve_internal_ids` für Modelle ohne eigene `tenant_id`-Spalte, plus
ungescopte Repository-`.get(id)`-Methoden.

## Wichtige Korrektur zum Phase-1-Befund

Der `public_id_service.py`-Docstring listet `StoredFile` und `ProtocolTodo` als Beispiele für
"nur transitiv tenant-gescopt" (kein eigenes `tenant_id`). Das ist **veraltet/falsch**: beide
Modelle haben in `backend/app/models/entities.py` inzwischen eine eigene `tenant_id`-Spalte
(`StoredFile` Zeile 970, `ProtocolTodo` Zeile 1079, dort nullable). Der No-Op-Fall betrifft
tatsächlich nur `ProtocolElement`, `ProtocolElementBlock`, `ProtocolImage`,
`ProtocolText`/`ProtocolDisplaySnapshot` (nicht im Scope dieser Prüfung) und `TemplateElement`/
`ListEntry` (siehe deren jeweils eigene, korrekt dokumentierte Join-basierte Helfer in
`word_import.py`/`lists.py`). Kein Sicherheitsproblem daraus, nur eine Doku-Ungenauigkeit —
Empfehlung: Docstring korrigieren, damit zukünftige Entwickler nicht von falschen Prämissen
ausgehen (siehe TEN-02).

## Methodik

Alle Aufrufer von `get_by_public_id`/`resolve_internal_id`/`resolve_internal_ids` im gesamten
`backend/app` wurden per grep aufgelistet (siehe Rohliste in dieser Fork-Session). Für jeden
Aufruf mit einem Modell ohne (wirksame) Tenant-Filterung wurde der jeweilige Route-/Service-Code
gelesen und geprüft, ob unmittelbar danach ein Tenant-/Ownership-Beweis erfolgt.

**Geprüft, kein Fund** (korrekt abgesichert durch nachgelagerten Check):

- `todos.py` (alle 6 Stellen: `ProtocolElementBlock`/`ProtocolTodo`) → jeweils
  `access_service.ensure_can_read_protocol_block`/`ensure_can_read_todo` direkt danach.
- `protocol_elements.py` (`ProtocolElement`, Zeilen 147, 274) →
  `access_service.ensure_can_read_protocol_element` direkt danach.
- `files.py` (`ProtocolElementBlock`/`ProtocolImage`/`StoredFile`, 7 Stellen) →
  `access_service.ensure_can_read_protocol_block`/`ensure_can_read_stored_file` direkt danach.
  `access_service.ensure_can_read_stored_file` selbst behandelt zusätzlich den Cross-Tenant-
  Share-Fall (geteilte Fotoalben) korrekt (Rollen-Check + `photo_album_share_service`).
- `submission_assignments.py` (`SubmissionUpload`/`StoredFile`, 5 Stellen) → jeweils
  `assignment.tenant_id != user.current_tenant_id`-Check direkt danach.
- `templates.py`/`_ensure_template_element_in_tenant` (`TemplateElement`) →
  `template.tenant_id != user.current_tenant_id`-Check.
- `lists.py`/`_get_entry_or_404` (`ListEntry`) → `definition.tenant_id != user.current_tenant_id`-
  Check über den geladenen `ListDefinition`.
- `word_import.py` — dokumentiert das I3-Muster explizit im Code-Kommentar (Zeilen 116-125) und
  löst `TemplateElement`/`ListEntry` über eigene join-basierte Helfer auf, nicht über den
  No-Op-Pfad.
- `fines.py`/`_resolve_fine_id` (`AttendanceFine`) → bewusst unscoped, weil
  `FinesRepository.delete_fine`/`collect_fine` selbst `protocol.tenant_id != tenant_id` prüfen
  (verifiziert in `fines_repository.py:204-225`, inkl. Row-Lock gegen Race mit `collect_fine`).
- `users.py` (`UserMfaFactor`, 3 Stellen) → `mfa_service.delete_self_factor`/
  `delete_managed_user_factor` filtern `_get_factor(..., user_id=...)` auf den bereits per
  `_managed_user`/`actor.user_id` verifizierten User; `_managed_user` selbst prüft
  `user.tenant_id != actor.current_tenant_id` UND `require_admin(actor)`.
- `protocol_todo_service.py` (`create_standalone_todo`/`create_todo`, Participant/Event/AppUser
  aus Payload) → bewusst unscoped, `*_allowed_for_tenant`/`*_allowed_for_block`-Checks direkt
  danach sind die dokumentierte Authorization-Grenze (Kommentar verweist auf "audit D6,
  2026-08-16").
- `events.py`/`event_service.py` — `EventRepository.get(db, event_id)` (ungescopt) wird
  ausschliesslich mit einer `id` aufgerufen, die zuvor über
  `public_id_service.get_by_public_id(db, Event, event_id, tenant_id=user.current_tenant_id)`
  bereits tenant-verifiziert wurde (`events.py:109,131` → `service.update_event`/`delete_event`
  → `event_service.py:145,174` → `self.repository.get`).
- `files.py` Album-Sharing (`Tenant`-Lookups ohne `tenant_id`, Zeilen 1035/1077) → beabsichtigtes
  Cross-Tenant-Feature (Album-Freigabe zwischen Mandanten); Album selbst vorher über
  `PhotoAlbum.tenant_id == user.current_tenant_id` verifiziert, Ziel-Mandant wird nur zum
  Auflösen einer Einladung/eines Widerrufs benutzt, keine Datenpreisgabe über die
  `Tenant`-Zeile hinaus.

## Findings

### TEN-01 [LOW] Unscoped Repository-Wrapper für `get_by_public_id` sind toter, aber gefährlicher Code

Status: CONFIRMED (als Hardening-Finding, kein aktiver Exploit-Pfad — Code ist unreachable)
CWE: CWE-1164 (Irrelevant Code) / defense-in-depth gegen zukünftige CWE-639 (IDOR)

Betroffene Dateien/Funktionen:
- `app/repositories/user_repository.py::UserRepository.get_by_public_id` (AppUser)
- `app/repositories/protocol_element_repository.py::get_by_public_id` (x2: ProtocolElement, ProtocolElementBlock)
- `app/repositories/file_repository.py::get_by_public_id` (ProtocolImage, um Zeile 566)

Security Invariant: I3 — jede client-gelieferte ID muss mit einem Tenant-/Ownership-Beweis
verknüpft werden, bevor die Resource zurückgegeben wird.

Beschreibung: Alle vier Methoden rufen `public_id_service.get_by_public_id` ohne `tenant_id=`
auf und sind (jeweils korrekt) mit einem Kommentar versehen, der Callern vorschreibt, selbst zu
scopen. Per grep über den gesamten `backend/app`-Baum ruft sie aktuell **niemand** auf — alle
tatsächlichen Routen nutzen stattdessen direkt `public_id_service.get_by_public_id(...)` mit
anschliessendem `access_service`-/Tenant-Check. Die Repository-Methoden sind toter Code.

Root Cause: Vermutlich Überbleibsel einer früheren Struktur (Repository-Pattern), das an diesen
vier Stellen nicht mehr benutzt wird, seit die Routen direkt gegen `public_id_service` +
`access_service` arbeiten.

Preconditions: Ein Entwickler müsste eine dieser vier Methoden künftig aus einer neuen Route
aufrufen, ohne den vorgeschriebenen Tenant-Check selbst nachzuziehen.

Attack Path (hypothetisch, aktuell nicht erreichbar):
1. Neue Route ruft z. B. `UserRepository().get_by_public_id(db, some_public_id)` auf.
2. Entwickler verlässt sich (fälschlich) darauf, dass die Methode wie die meisten anderen
   `get_by_public_id`-Wrapper im Repository-Layer bereits tenant-scoped ist (Inkonsistenz:
   andere Repositories wie `EventRepository.get_by_public_id`, `ParticipantRepository.
   get_by_public_id` NEHMEN `tenant_id` als Pflichtparameter).
3. Route gibt eine fremde `AppUser`/`ProtocolElement`/`ProtocolElementBlock`/`ProtocolImage`-Zeile
   zurück, wenn der Client die public_id eines anderen Tenants errät/kennt.

PoC: nicht anwendbar (kein aktiver Aufrufer).

Impact: Aktuell keiner. Bei künftiger Verwendung: Cross-Tenant-Informationsleck bzw. IDOR,
Schwere abhängig vom Modell (AppUser: E-Mail/Rolle; ProtocolElement/-Block/-Image: Protokoll-
inhalte fremder Mandanten).

Existing Mitigations: Docstring-Warnung in jeder Methode; kein aktueller Aufrufer.

Why Existing Mitigations Are Insufficient: Ein Kommentar verhindert keinen Fehlgebrauch
strukturell — genau das Muster, das laut CHANGELOG/Code-Kommentaren in diesem Repo bereits
mehrfach zu echten Cross-Tenant-Findings geführt hat (siehe `access_service.py`-Kommentare zu
`can_read_template`/`can_read_protocol`: "this used to return True unconditionally").

Recommended Fix: Diese vier ungenutzten Methoden entweder (a) löschen (kein Aufrufer, einfachste
Option), oder (b) falls als API-Fläche gewünscht, `tenant_id` zum Pflichtparameter machen und
intern zusätzlich den passenden `access_repository`-Join durchführen, damit die Methode für
JEDEN künftigen Aufrufer sicher ist, statt sich auf eine Konvention zu verlassen.

Regression Test: Falls (a) gewählt wird, kein Test nötig. Falls (b): Unit-Test, der belegt, dass
`get_by_public_id` mit der public_id eines Objekts aus Tenant B und `tenant_id=<Tenant A>` `None`
zurückgibt.

Evidence: siehe Dateipfade oben; Gegenprobe per `grep -rn "UserRepository().get_by_public_id\|
protocol_element_repository\.\|FileRepository().*ProtocolImage" backend/app` liefert ausser den
Definitionen selbst keine Treffer.

### TEN-02 [INFO] Veralteter Docstring in `public_id_service.py` nennt falsche Beispiele

Status: CONFIRMED (Doku-Ungenauigkeit, kein Sicherheitsfund)

Betroffene Datei: `app/services/public_id_service.py` (Modul-Docstring, Zeilen 14-21)

Beschreibung: Der Docstring nennt `StoredFile` und `ProtocolTodo` als Beispiele für Modelle ohne
eigene `tenant_id`-Spalte. Beide haben inzwischen eine eigene `tenant_id`-Spalte (siehe oben).
Nur `ProtocolElement`/`ProtocolElementBlock` (und weitere, hier nicht geprüfte wie
`ProtocolImage`/`ProtocolText`) sind tatsächlich noch rein transitiv gescopt.

Impact: Kein direkter Sicherheitsimpact, aber Verwirrungspotenzial für künftige Entwickler, die
sich auf die genannten Beispiele verlassen (könnte dazu führen, dass ein Entwickler fälschlich
glaubt, `tenant_id=` bei `StoredFile` sei wirkungslos, und einen unnötigen/fehlerhaften
zusätzlichen Check baut — oder umgekehrt bei einem tatsächlich noch transitiv gescopten Modell
den Docstring falsch verallgemeinert).

Recommended Fix: Docstring aktualisieren: `StoredFile`/`ProtocolTodo` aus der Beispielliste
entfernen (sie sind jetzt direkt gescoped), stattdessen `ProtocolImage`, `ProtocolText`,
`ProtocolDisplaySnapshot` als aktuelle Beispiele für "nur transitiv gescoped" nennen (jeweils
kurz verifizieren).

Regression Test: keiner nötig (reine Dokumentation).

## Fazit für Invariante I3

Die in Phase 1 als höchste Priorität eingestufte Sorge — ein systemisches IDOR-Muster über
`get_by_public_id`-No-Ops — **bestätigt sich bei der Tiefenprüfung NICHT** als aktiver Fund.
Jede der ca. 20 geprüften Call-Site-Gruppen über 10 Dateien hinweg verknüpft den No-Op-Fall
korrekt mit einem expliziten, nachgelagerten Tenant-/Ownership-Check. Das Muster ist eine bewusst
gewählte, mehrfach im Code kommentierte Architekturentscheidung (Repository/Service-Layer statt
ORM-Relationship-Magie), keine vergessene Absicherung. Einzige Funde: zwei Low/Info-Findings zu
totem Code bzw. veralteter Dokumentation (TEN-01, TEN-02) als Hardening-Empfehlungen.

**Nicht erschöpfend geprüft** (für Phase 3/Completeness-Check vormerken, falls Zeit bleibt):
`participant_service.py:137` (AppUser aus Payload), restliche `word_import.py`-Stellen
(`resolve_internal_ids` für Event/Participant/ListDefinition — laut grep bereits mit
`tenant_id=` versehen, stichprobenartig nicht einzeln gegengelesen), `admin.py`/`tenants.py`
(Platform-Admin-Scope, andere Actor-Klasse, siehe Fork B), `ProtocolImage`/`ProtocolText`/
`ProtocolDisplaySnapshot`-Callsites ausserhalb von `files.py`.

Status: REVIEWED_WITH_FINDINGS (2x LOW/INFO, keine CONFIRMED/HIGH-Cross-Tenant-Lücke gefunden)
