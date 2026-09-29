# TEST_RECOMMENDATIONS

Fehlende Security-Regressionstests, identifiziert während des Audits (nicht: bereits
vorhandene Tests bewerten — das folgt in einer späteren Phase, sofern Zeit bleibt).

## Aus Phase 2

1. **photo-analysis-worker Fehlererfassung** (zu BG-01): Test, der einen garantiert
   fehlschlagenden Job durchlaufen lässt und verifiziert, dass der Fehler im gewählten
   Ersatzmechanismus für `system_error_log` ankommt (abhängig von der Fix-Entscheidung).
2. **Word-Import ZIP mit falsch deklarierter Grösse**: Regressionstest, der ein ZIP mit
   absichtlich zu klein deklarierter, aber tatsächlich grosser Entry-Grösse hochlädt und
   verifiziert, dass der Prozess innerhalb der Ressourcen-/Zeitgrenzen bleibt (aktuell nur durch
   `run_in_threadpool`-Isolation gemildert, nicht hart begrenzt) — Kandidat, kein akutes Finding.
3. **`get_by_public_id`-Wrapper-Löschung/Absicherung** (zu TEN-01): falls Option (b) gewählt wird
   (Parameter-Pflicht statt Löschung), Unit-Test pro Methode: `tenant_id=<fremder Tenant>` →
   `None`.
4. **`ci.yml` `permissions:`-Policy** (zu DEPLOY-01): kein automatisierter Test sinnvoll,
   stattdessen Code-Review-Konvention (Kommentar im Workflow).

## Aus Phase 4 (Test-Abdeckungs-Analyse)

Abgleich von neun in diesem Audit als korrekt verifizierten Security-Invarianten gegen
vorhandene Tests (Suche nach Testfunktionsnamen, keine vollständige Test-Bewertung). Ergebnis:
**7 von 9 bereits solide abgedeckt**, 2 echte Lücken gefunden.

**Bereits abgedeckt (keine Aktion nötig):**
1. Cross-Tenant-Zugriff über `access_service` — `test_auth_access.py::
   test_writer_cannot_read_protocol_of_another_tenant`,
   `test_unrestricted_reader_cannot_read_protocol_of_another_tenant`,
   `test_files_overview.py::test_list_tenant_files_excludes_other_tenant_files`,
   `test_file_tags_metadata.py::test_update_submission_file_tags_route_rejects_other_tenant`.
2. Admin-Rollen-Trennung owner/support — `test_role_permissions.py::
   test_support_cannot_read_sensitive_platform_data`, `test_owner_can_read_sensitive_platform_data`.
3. Fines Row-Lock-Concurrency — `test_fines_collect_race.py::
   test_collect_fine_blocks_on_concurrent_holder_of_the_row_lock`,
   `test_collect_fine_race_only_one_of_two_concurrent_callers_succeeds` (echter
   Zwei-Prozess/Thread-Concurrency-Test, kein reiner Funktionsaufruf).
4. `public_share.py` Expiry/IDOR — `test_share_link_routes.py::
   test_public_share_endpoints_reject_an_expired_link`,
   `test_download_public_share_file_rejects_a_file_outside_the_link`,
   `test_get_public_share_404s_for_an_unknown_token`.
6. Session-Revocation — `test_auth_access.py::
   test_session_token_issued_before_revoke_at_is_rejected`,
   `test_session_is_rejected_after_user_is_deactivated`,
   `test_admin_logout_revokes_existing_session_tokens`.
7. `sanitize_redirect_to()` Open-Redirect — `test_platform_oidc_service.py::
   test_sanitize_redirect_to` (parametrisiert), `test_sanitize_redirect_to_strips_embedded_whitespace...`.
9. `_escape_latex` — `test_document_template_service.py::
   test_escape_latex_escapes_all_special_characters`.

**Echte Lücken (Testvorschlag):**

- **Account-Lockout-Schwelle (Login/TOTP)**: kein Test gefunden, der die tatsächliche
  Lockout-Schwelle erreicht und verifiziert, dass der (N+1)-te Versuch abgelehnt wird — trotz
  vorhandener Tests für angrenzende Bereiche (`test_user_service.py`, `test_mfa_service.py`,
  `test_admin_mfa_service.py` behandeln andere Aspekte). Vorschlag: Test, der
  `_ACCOUNT_LOGIN_ATTEMPT_LIMIT` (`auth_service.py`) bzw. das TOTP-Pendant
  (`mfa_service.py`) durch wiederholte Fehlversuche erreicht und einen danach folgenden,
  korrekten Login/TOTP-Versuch als abgelehnt (nicht nur "falsches Passwort", sondern
  "gesperrt") erwartet.
- **`collaboration_ws.py` WS-Handshake-Origin-Rejection**: `test_collaboration_ws.py` (53
  Zeilen) testet nur die Konstruktion der Origin-Allowlist
  (`_active_app_domain_origins_includes_active_app_domain` u. a.), aber KEINEN tatsächlichen
  WebSocket-Verbindungsversuch mit fehlendem/falschem `Origin`-Header gegen `_origin_allowed`/
  den echten Handshake-Handler. Vorschlag: Test, der eine WS-Verbindung mit `Origin: https://
  evil.example` bzw. ganz ohne `Origin`-Header aufbaut und eine Ablehnung (Connection-Close vor
  `accept()`) erwartet.
