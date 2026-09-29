# Fork H — Auth-Kernaudit (Abschnitt 7)

Scope: `auth.py`, `core/security.py`, `core/rate_limit.py`, `mfa_service.py`,
`domain_bridge_service.py`, `user_service.py` (Passwort-/Session-Revocation-Pfade). Keine
Codeänderungen, keine Commits.

## Ergebnis: keine neuen CONFIRMED/NEEDS_VERIFICATION-Findings

Alle sechs Prüffragen aus dem Directive wurden beantwortet, keine hält als Sicherheitslücke stand.

### 1. CSRF — geprüft, kein Fund
`SameSite=Lax`-Cookie + reine JSON-Content-Type-APIs (kein Endpoint akzeptiert
`application/x-www-form-urlencoded`/`multipart` für state-changing Auth-Aktionen ausser Uploads,
die separat auditiert wurden) ist die Standardkombination gegen CSRF. Einzige GET-Route mit
Seiteneffekt: `/bridge` (redeemt ein One-Time-Token, setzt Cookie). Bewertung: theoretisches
"Login-CSRF"-Muster (Angreifer schickt Opfer einen Link mit dem Bridge-Token des Angreifers
selbst → Opfer landet in Angreifers Session auf der Custom-Domain), aber selbstlimitierend:
Token ist `secrets.token_urlsafe(32)` (256 Bit), **single-use** (`GETDEL`, atomar), 60s TTL,
`nx=True` beim Erzeugen. Angreifer muss den Link innerhalb von 60s nach eigenem Login verschicken;
Impact beschränkt sich darauf, dass das Opfer (falls es das nicht bemerkt) in der Session des
Angreifers landet — kein Zugriff auf Opfer-Daten. Kein neuer Fund, nur als INFO vermerkt.
`/tenant-by-domain` und `/session` (GET) sind reine Lesezugriffe ohne Seiteneffekt.

### 2. Rate-Limiting/Brute-Force — geprüft, robust
`core/rate_limit.py` ist **Redis-backed** (nicht In-Memory/pro-Worker) — konsistent über alle
Uvicorn-Worker-Prozesse hinweg, kein Umgehen durch Lastverteilung. Zwei unabhängige Schichten:
Traefik-Labels (per-Source-IP, z. B. Login 10/min) UND App-seitiges `check_account_lockout`/
`record_failed_attempt` (Redis, **account-scoped**, nicht IP-scoped) — Kommentar im Code selbst
begründet das explizit: "second, account-scoped line of defense... which a distributed or
shared-IP attacker can bypass". Login-Lockout: 20 Versuche/15 Minuten pro Account
(`_ACCOUNT_LOGIN_ATTEMPT_LIMIT`/`_ACCOUNT_LOGIN_WINDOW_SECONDS`, `auth_service.py:33-34`).
TOTP-Verify-Lockout: 10 Versuche/15 Minuten pro Account (`mfa_service.py:51-52`), zusätzlich ein
Flow-scoped Limit (10/Ticket-TTL). Password-Change-Selfservice hat ebenfalls einen eigenen
Account-Lockout (`user_service.py:350-353`). Keine Lücke gefunden: App-seitiges Limit deckt exakt
die Fälle ab, die Traefik (nur IP-basiert) nicht abdecken könnte (verteilter Angreifer). Kein
Endpoint identifiziert, der NUR durch Traefik geschützt wäre und bei direktem Backend-Zugriff
ungeschützt bliebe — `enforce_rate_limit`/`check_account_lockout` sind direkt im Service-Code
aufgerufen, nicht nur als Middleware, greifen also unabhängig vom Netzwerkpfad.

### 3. Passwort-Reset/Invite-Tokens — Feature existiert absichtlich nicht
`UserPasswordChange`-Docstring (`schemas/user.py:114-117`): explizit dokumentierte
Design-Entscheidung — "deliberately no 'forgot password' email flow (no mail infrastructure
exists in this project)". Passwort wird ausschliesslich (a) selbst geändert (mit Alt-Passwort-
Bestätigung, `change_own_password`) oder (b) von einem Tenant-Admin gesetzt (`_update_user_core`,
ohne Alt-Passwort-Kenntnis nötig, aber `require_admin`+Tenant-Match-gescoped, siehe Fork B). Kein
Reset-Token-Mechanismus vorhanden, also auch keine der klassischen Reset-Token-Schwachstellen
(Entropie/Timing/Log-Leak) — nicht anwendbar, kein Fund.

### 4. Session-Revocation — geprüft, konsistent
`session_revoke_at` wird korrekt gesetzt bei: eigenem Passwortwechsel, Admin-gesetztem Passwort,
Deaktivierung (`is_active=False`), Login-Disable (`_update_user_core`, `user_service.py:239-248`).
**Rollenänderung braucht KEINE Revocation**: `CurrentUser.current_role` wird bei JEDEM Request
frisch aus der DB geladen (`build_current_user`, kein Rollen-Claim im Token) — ein Downgrade wirkt
sofort ab dem nächsten Request, ohne dass die alte Rolle im Token "überlebt". **MFA-Faktor-Löschung
durch einen Admin braucht ebenfalls KEINE explizite Revocation**, obwohl `delete_managed_user_factor`/
`delete_platform_admin_user_factor` (`mfa_service.py:245-265`) `session_revoke_at` nicht setzen:
für die Rolle `admin` erzwingt `get_optional_current_user`
(`_requires_mfa(current_user) and (not has_mfa_factor or not current_user.mfa_verified)`,
`security.py:202-203`) bei jedem Request eine frische `has_mfa_factor`-Prüfung — wird der letzte
Faktor eines Admins gelöscht, wird JEDE bestehende Session dieses Admins beim nächsten Request
automatisch abgelehnt (kein Fenster, in dem eine alte Session mit gelöschtem Faktor weiterläuft).
Für Nicht-Admin-Rollen ist MFA nie erzwungen (`_requires_mfa` prüft nur `role == "admin"`), daher
gibt es dort auch nichts zu revoken. **Kein Fund** — ursprünglicher Verdacht (fehlende Revocation
bei Faktor-Löschung) durch genaues Lesen von `get_optional_current_user` widerlegt.

### 5. MFA-Lockout — geprüft, kein DoS-Fund
Beide Lockouts (Login-Passwort, TOTP-Verify) sind **zeitlich begrenzte Fenster** (15 Minuten),
kein permanentes Sperren. Ein Angreifer kann ein fremdes Konto zwar für die Fensterdauer
funktional gegen legitime Logins sperren (Standard-Trade-off jedes account-scoped Lockouts,
nicht spezifisch zu diesem Code), aber nicht dauerhaft aussperren. Kein Fund.

### 6. Cookie-Domain — geprüft, korrekt
`issue_session_cookie` (`security.py:101-116`) setzt **kein** `domain=`-Attribut → Host-only-Cookie
(Kommentar bestätigt das explizit: "sets it as a host-only cookie"). Der Browser sendet es
ausschliesslich an exakt den Host, der es gesetzt hat — kein Leak an Subdomains oder andere
Tenant-Custom-Domains. Genau deshalb existiert der separate `/bridge`-Mechanismus (Cookie muss
pro Domain einzeln neu ausgestellt werden). Kein Fund.

## Nebenbefund (kein neues Finding, Cross-Reference)

`_expected_origin()`/WebAuthn-RP-ID-Pinning (`auth.py:29-42`) bereits als Fix eines früheren Audits
(2026-08-25) korrekt implementiert (pinnt auf `settings.traefik_domain`, nicht auf den
client-gelieferten `Origin`-Header selbst) — verifiziert, keine Regression.

## Fazit

Auth-Kernbereich (Abschnitt 7) ist durchgängig robust: Redis-backed, account-scoped Lockouts
zusätzlich zu Traefik-IP-Limits, host-only Cookies, serverseitig frisch geladene Rolle ohne
Token-Claim, korrekte Session-Revocation bei allen sicherheitsrelevanten Aktionen, bewusst kein
Passwort-Reset-Feature (kein Angriffsvektor durch dessen Abwesenheit). Kein Finding in
FINDINGS.md-Format nötig — alle Prüfpunkte enden als "geprüft, kein Fund".
