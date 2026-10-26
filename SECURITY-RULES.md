# hocX Sicherheitsregeln (verbindlich)

Gilt für **jede** Änderung, von Menschen und von AI-Agents (Claude Code, Codex, Gemini, Tabnine …).
hocX ist mandantenfähig: der schwerste Fehler ist, dass ein Verein Daten eines anderen sieht oder
ändert. Hintergrund und Ablauf: Wiki-Seite [Sicherheit](https://github.com/FrissBrot/hocX/wiki/Sicherheit).

Automatisch geprüft (nur neu eingeführte Verstösse): `python3 scripts/check-security-rules.py <Datei>`
- nach jeder Dateiänderung durch Claude Code (Hook), im Pre-Commit-Hook und in der CI
(`security-lint`). Eine Meldung wird behoben, nicht umgangen. Eine bewusste Ausnahme wird in
derselben Zeile **begründet** markiert; eine Markierung ohne echten Grund ist ein Fehler.

## 1. Mandantentrennung

1. **Jeder Zugriff ist auf den Mandanten des Aufrufers gescoped.** IDs aus Pfad, Query oder Body
   immer über `public_id_service.get_by_public_id(db, Model, public_id, tenant_id=user.current_tenant_id)`
   bzw. `resolve_internal_id(..., tenant_id=...)` auflösen. Ohne `tenant_id=` nur mit
   `# nosemgrep: public-id-lookup-without-tenant -- <Begründung>`, wenn danach nachweislich eine
   eigene Mandantenprüfung folgt.
2. **Schreiben ist strenger als Lesen.** Eine Schreibroute nutzt nie nur `ensure_can_read_*`: was ein
   Partner lesen darf (geteilte Alben), darf er deshalb noch nicht ändern (vgl. SEC-003). Bewusste
   Ausnahme: ein akzeptierter Partner mit `files.manage` darf in ein geteiltes Album Fotos beitragen
   und "Beste" markieren, aber nicht einladen oder freigeben (RBAC-Entscheidung E-7).
3. **Berechtigungen und Features** über `require_permission(user, P.<KEY>)` (`app/core/security.py`,
   Katalog `permissions/catalog.json`) bzw. `require_feature` prüfen, bevor etwas geladen oder
   geändert wird - nie über Rollen-Codes (`"admin"`, `"writer"` …). Eine neue Funktion nutzt eine
   bestehende Permission oder bekommt eine neue im Katalog (`scripts/sync-permission-catalog.py`,
   Migration ordnet sie den Standardrollen zu). Ressourcenregeln (Mandant, Protokollstatus,
   Teilnehmer-Zuordnung, eigene Daten) bleiben in `services/access_service.py`.
   `tests/test_route_permission_inventory.py` schlägt fehl, wenn eine Route keine Prüfung hat.
   Hintergrund: `docs/RBAC_ARCHITECTURE_PROPOSAL.md`.
4. **Rollen und Zuweisungen nur über `services/role_service.py`** (keine Rechteausweitung, letzter
   Administrator, kein Selbstentzug, Mandantensperre) - auch aus dem Plattform-Admin-Panel und
   aus Importen.
5. **Fremde Mandanten sind die Ausnahme.** Mandantenübergreifend dürfen nur Plattform-Admin,
   Hintergrundjobs und ausdrücklich dafür gebaute Wege (geteilte Fotoalben, öffentliche Links)
   arbeiten. `tenant_scope_suspended(db)` nur für Prüfungen, die nichts Fremdes zurückgeben (Ja/Nein,
   Anzahl), immer mit `# rls-ok: <Begründung>`.
6. **Antwort ohne Existenz-Orakel:** fremde und nicht existierende IDs ergeben dieselbe Antwort
   (meist 404).

## 2. Datenbank

1. **Neue Tabelle mit Mandantendaten → `tenant_id` (NOT NULL) und RLS-Policy im selben Change**
   (Vorlage: Wiki [Datenbank und Migrationen](https://github.com/FrissBrot/hocX/wiki/Datenbank-und-Migrationen#row-level-security)).
   Eine Untertabelle ohne eigene `tenant_id` bekommt eine Policy über ihre Elterntabelle
   (`0134_child_table_rls.py`). `tests/test_tenant_rls.py` schlägt fehl, wenn eine Tabelle fehlt.
2. Keine Tabelle, in der dieselbe Art Daten mal über `tenant_id`, mal nur über eine Beziehung zum
   Mandanten gehört (vgl. `protocol_todo` vor `0131`) - im Zweifel per Trigger füllen.
3. **SQL nur mit gebundenen Parametern** (`text("... :id")`, `{"id": value}`), nie als f-String
   mit Werten. f-Strings nur für feste Bezeichner aus dem Code, markiert mit `# sql-ok: <Begründung>`.
4. Laufzeitrollen (`hocx_app`, `hocx_abgabebox`, `hocx_photo_worker`) bekommen nur die nötigen
   Rechte, nie `SECURITY DEFINER`-Funktionen ohne `SET search_path`. Die Abgabebox liest nur über
   ihren Link-Kontext (`abgabebox-backend/app/link_scope.py`).
5. Migrationen, die bereits produktiv liefen, werden nicht geändert; Korrekturen als neue Revision.

## 3. Authentifizierung, Sessions, Requests

1. Zustandsändernde Endpunkte sind `POST/PUT/PATCH/DELETE`, nie `GET` (Origin-Prüfung und
   SameSite greifen nur dort).
2. **Geheimnisse nie in URLs** (Query-Parameter landen in Logs, Verlauf und Referer): Tokens und
   Passwörter in Body oder Header, Einmal-Links per URL-Fragment (vgl. Domain-Bridge).
3. Konten prüfen wie `get_optional_current_user`: aktiv, Login erlaubt, `session_revoke_at`, MFA.
   Wer Sessions eines Kontos beenden muss (Passwort, Deaktivierung, MFA-Reset), setzt
   `session_revoke_at`.
4. Öffentliche und Login-nahe Endpunkte haben ein Rate-Limit (`enforce_rate_limit`).
5. Redirects nur auf relative Pfade oder fest konfigurierte Domains (kein Open Redirect).

## 4. Dateien, Eingaben, Ausgaben

1. Uploads: Grössenlimit, Magic-Byte-Prüfung, ClamAV, Pfade nie aus Benutzereingaben bauen.
2. Frontend: kein `dangerouslySetInnerHTML` mit Benutzer- oder Mandantendaten. Nur für feste,
   eigene Inhalte, markiert mit `{/* security-ok: <Begründung> */}`. Neue Skripte brauchen die
   Nonce der CSP (`frontend/proxy.ts`, `abgabebox-frontend/proxy.ts`), kein `'unsafe-inline'`.
3. Fehler: `raise HTTPException(...) from exc` in jedem `except`-Block (siehe CLAUDE.md, Zentrale
   Fehlererfassung). Interne Details (Stacktraces, SQL, Pfade) gehören ins Fehlerprotokoll, nicht in
   die Antwort.
4. Exporte mit Personendaten verlassen den Server nur verschlüsselt (`export_crypto.py`).

## 5. Secrets und Abhängigkeiten

1. Keine Secrets, Tokens, echten Domains oder Kundendaten im Repo, in Tests oder Logs (Gitleaks im
   Pre-Commit und in der CI). Testpasswörter zur Laufzeit erzeugen.
2. Ein neues Secret wird vollständig verdrahtet: `app/core/config.py` (inkl. `_FILE`),
   `.env*.example`, `scripts/lib/env.sh` (Allowlist), `scripts/lib/env_migrate.sh` (einmalig erzeugen),
   `scripts/deploy.sh` (Prüfung und Secret-Datei), `docker-compose.release.yml` (Secret nur für die
   Dienste, die es brauchen).
3. Abhängigkeiten gepinnt, Actions und Images per SHA/Digest. `pip-audit`, `npm audit` und Trivy
   blockieren bekannte Schwachstellen; ein Fund ohne Fix wird begründet ausgenommen.

## 6. Vor dem Abschluss einer Änderung

- `python3 scripts/check-security-rules.py <geänderte Dateien>` meldet `Sicherheitsregeln: ok`.
- Tests für Fremd-Mandanten-Fälle der Änderung (fremde ID → abgelehnt, Partner nur lesend …);
  bei Datenbankänderungen zusätzlich `tests/test_tenant_rls.py` und der RLS-Testmodus
  (Wiki [Testprozess](https://github.com/FrissBrot/hocX/wiki/Testprozess#rls-testmodus)).
- Berührt die Änderung Auth, Mandantenzugriff, öffentliche Endpunkte, Uploads, Migrationen oder
  Secrets: vor dem Commit ein Security-Review des Diffs (in Claude Code: Agent `security-reviewer`
  bzw. `/security-review`). Funde werden behoben oder mit Begründung im Commit erwähnt.
