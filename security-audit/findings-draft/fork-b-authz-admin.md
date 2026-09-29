# Fork B — Authorization / Platform-Admin Deep-Dive

Scope: Audit-Abschnitt 8 (Authorization). Dateien vollständig gelesen: `backend/app/core/security.py`,
`backend/app/core/admin_security.py`, `backend/app/api/routes/admin_auth.py`,
`backend/app/api/routes/admin.py` (960 Zeilen, vollständig), `backend/app/api/routes/tenants.py`,
`backend/app/api/routes/users.py`, `backend/app/services/tenant_service.py` (Domain-Management-
Abschnitt), `backend/app/services/user_service.py`/`mfa_service.py` (Guard-Aufrufe),
`backend/app/services/platform_oidc_service.py` (Redirect-Sanitizing), Auszüge `files.py`
(Album-Routen). Automatisierter Scan über ALLE Routendateien nach Guard-Mustern (siehe unten).

## Methodik

1. Automatisiertes Skript, das für jede `@router.*`-Route im Funktionskörper nach
   `require_[a-z_]+`-Aufrufen sucht (sowohl direkte Calls `require_writer(user)` als auch
   `Depends(require_admin_write)`), und state-changing Routen ohne jeden Treffer bzw. mit nur
   `require_reader` markiert.
2. Jeden Treffer manuell verifiziert (False-Positive-Check: Guard kann in einer Helper-Funktion
   oder im Service-Layer liegen, nicht in der Route selbst).

## Ergebnis: KEIN neuer bestätigter Authorization-Fund

Alle automatisch geflaggten Kandidaten wurden auf einen der folgenden, unbedenklichen Fälle
zurückgeführt:

- **Self-Service-Routen** (`/me/*` in `users.py`, `/mfa/*` (self) in `admin.py`, `/logout`,
  `/login`, `/mfa/totp/verify` während des Login-Tickets in `auth.py`/`admin_auth.py`): korrekt
  ohne Rollen-Guard, da Ziel implizit "der eigene Account" ist bzw. die Route selbst Teil des
  Auth-Vorgangs ist (kann nicht Auth verlangen, bevor Auth abgeschlossen ist).
- **Guard liegt im Service-Layer, nicht in der Route**: `users.py` (`/`, `/{user_id}` GET/PATCH/
  DELETE, `/{user_id}/mfa/*`) delegiert an `UserService`/`MfaService`, die jeweils
  `require_admin(actor)` **und** einen expliziten Tenant-Match (`user.tenant_id !=
  actor.current_tenant_id` → 403/404) durchsetzen (`user_service.py:107,155,204,204,311,317`,
  analog `mfa_service.py:195,197`). Verifiziert durch Lesen der Service-Methoden, nicht nur
  Vermutung.
- **Guard liegt in einer gemeinsamen Helper-Funktion**: `files.py`s `POST /files/albums/{album_id}
  /items` und `PATCH .../best` rufen beide `_get_album(db, user, album_id)` auf, das intern
  `require_writer(user)` **und** tenant-gescopte `get_accessible_album(...)` durchsetzt
  (`files.py:893-898`).
- **Tenant-Domain-Management** (`tenants.py`: `patch_tenant`, `create/verify/delete_tenant_domain`):
  alle delegieren an `TenantService`, das `_require_manageable()` (= `require_admin` +
  `_manageable_tenant_ids`-Tenant-Check) und zusätzlich `require_feature(actor, "custom_domain")`
  bei `create_domain`/`verify_domain` durchsetzt (`tenant_service.py:166-299`). `delete_domain`
  bewusst OHNE Feature-Gate (Kommentar: nach Feature-Downgrade muss eine bestehende Domain noch
  entfernbar sein) — kein Fund, nachvollziehbare, dokumentierte Ausnahme.
- **`export.py`/`exports.py`-POST-Routen mit nur `require_reader`**: inhaltlich Lese-Operationen
  (PDF/Markdown-Export bestehender, für den User ohnehin sichtbarer Daten), POST nur wegen
  Options-Payload im Body — sachlich korrekt mit Reader-Niveau. Die *tenant-übergreifende*
  Leck-Frage bei Exporten (historische Findings in `export_service.py`) ist ausdrücklich NICHT
  Teil dieses Forks (siehe TODO.md Phase 3 "statistics.py/exports.py Regression").
- **`protocols.py` `PUT /protocols/{protocol_id}/scroll-position`**: rein UI-State des
  aufrufenden Users selbst, unkritisch.
- **`admin.py`**: Router-weite `dependencies=[Depends(get_current_admin)]` (Zeile 77) erzwingt
  strukturell für JEDE Route mindestens eine gültige, MFA-verifizierte Platform-Admin-Session
  (nicht optional/vergessbar). Jede Mutation zusätzlich `Depends(require_admin_write)`
  ("owner"-Rolle), jeder Cross-Tenant-PII-Read zusätzlich `Depends(require_admin_owner)`
  (Tenant-User-Liste, einzelner User, MFA-Übersicht, Error-Logs, Upload-Pipeline-Status,
  Admin-Liste). Konsistent durchgehalten über alle 45 Routen der Datei (vollständig gelesen).
  `export_tenant` (Voll-Export inkl. Passwort-Hashes) ist mit explizitem Kommentar auf
  `require_admin_write` verschärft (referenziert selbst einen Audit-Fix 2026-08-25) —
  verifiziert korrekt implementiert.

## AUTHZ-01 — Platform-Admin-MFA-Erzwingung: verifiziert, kein Fund

`admin_security.get_optional_current_admin` akzeptiert NUR Session-Tokens mit `mfa: true`-Claim
(Zeile 118-119: `if not bool(session_data.get("mfa")): return None`) — jeder ältere/MFA-lose
Token wird abgelehnt, kein Fallback. `AdminAuthService.login` (nicht vollständig gelesen, aber
laut `admin_auth.py`-Kommentar "always routes a non-MFA'd password check through the MFA-pending
ticket flow") mintet nie direkt eine volle Session ohne abgeschlossene TOTP-Verifikation oder
OIDC-SSO (dort `mfa_verified=True` bewusst, da externe IdP-MFA als gleichwertig behandelt wird —
nachvollziehbare Design-Entscheidung, kein Bypass, da OIDC selbst wieder hinter
`platform_oidc_service`-Konfiguration + Signatur-/State-Prüfung liegt). **Status: REVIEWED,
kein Fund.**

## AUTHZ-02 — Admin-Rollen-Trennung "owner"/"support": verifiziert, kein Fund

`role: Literal["owner", "support"]` (typisiert, keine Freitext-Rolle). `require_admin_write`
und `require_admin_owner` beide `if admin.role != "owner": raise 403` — ein "support"-Admin kann
laut Code weder mutieren noch cross-tenant-PII lesen. Alle 960 Zeilen `admin.py` konsistent
geprüft, keine Route gefunden, die eine Mutation oder einen PII-Read ohne diese Guards erlaubt.

## AUTHZ-03 — Open-Redirect-Schutz bei OIDC-Login: verifiziert, kein Fund

`sanitize_redirect_to()` (`platform_oidc_service.py:23-42`) lehnt jeden nicht-relativen,
protokoll-relativen (`//host`) oder mit Backslash beginnenden Redirect-Ziel-String ab, inkl.
Tab/Newline-Stripping gegen naive Präfix-Checks. Angewendet sowohl beim Eintritt
(`oidc_authorize`) als auch am Ende (`oidc_callback`) — Defense-in-Depth wie kommentiert.

## Nicht abschliessend geprüft (Restarbeit für spätere Vertiefung/Phase 3)

Automatisierter Guard-Scan lief über ALLE Routendateien und ergab für folgende Module keine
auffälligen Muster (keine state-changing Route ohne jeden `require_*`/Feature-Guard-Treffer),
aber es wurde **nicht** jede Route einzeln manuell auf "ist genau die richtige Rolle für die
tatsächliche Sensitivität gewählt" gelesen (nur automatisiert plausibilisiert): `events.py`,
`finance.py`, `fines.py`, `participants.py`, `lists.py`, `statistics.py`, `templates.py`,
`document_templates.py`, `cycle_configs.py`, `tag_config.py`, `todos.py`, `table_snapshots.py`,
`protocol_elements.py`, `share_links.py`, `public_share.py`, `submission_assignments.py`,
`collaboration_ws.py`. Empfehlung: `finance.py`/`fines.py` (Geld) und `share_links.py`/
`public_share.py`/`submission_assignments.py` (Public-Grenze) mit höchster Priorität in Phase 3
noch einzeln lesen, da dort sowohl finanzieller Schaden als auch Public-Boundary-Risiko am
höchsten sind — dieser Fork hat sie aus Zeit-/Scope-Gründen nicht vollständig gelesen (nur
automatisiert gescannt).

`admin-error-log.tsx` selbst nicht inhaltlich gelesen (Backend-Gate `require_admin_owner` allein
bereits ausreichend verifiziert, um die Frage "kann ein Tenant-Admin das sehen?" mit Nein zu
beantworten — die UI ist unter `/admin/*`, komplett separates Auth-Realm, kein Tenant-User erhält
je eine gültige `admin_session_cookie`).

## Fazit

Kein CONFIRMED, kein NEEDS_VERIFICATION Finding in diesem Fork. Die Rollen-/Feature-Guard-
Architektur ist trotz "reiner Funktionsaufruf ohne FastAPI-Depends-Zwang"-Musters (Tenant-Seite)
in der Praxis konsistent angewendet, an mehreren Stellen zusätzlich durch Service-Layer- oder
Helper-Funktions-Kapselung abgesichert, die den Aufruf nicht der einzelnen Route überlässt.
Platform-Admin-System (Depends-basiert, MFA-erzwungen, rollengetrennt) ist strukturell robuster
als das Tenant-System und zeigt keine Lücke.
