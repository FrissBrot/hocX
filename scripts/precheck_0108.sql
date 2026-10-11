-- Vorab-Check fuer Migration 0108_unified_participants (Update auf 1.1.10).
-- Read-only, auf der DB VOR dem Upgrade ausfuehren (RUNBOOK Abschnitt 4).
-- 1) Login-Konten ohne E-Mail/Passwort -> ck_app_user_login_credentials schlaegt fehl
SELECT 'login_ohne_credentials' AS check, id, email FROM app_user
WHERE COALESCE((external_identity_json->>'login_enabled')::boolean, TRUE)
  AND (email IS NULL OR trim(email) = '' OR password_hash IS NULL);
-- 2) Login-E-Mails, die nach lower(trim()) kollidieren -> uq_app_user_login_email schlaegt fehl
SELECT 'email_kollision' AS check, lower(trim(email)) AS email, count(*) FROM app_user
WHERE COALESCE((external_identity_json->>'login_enabled')::boolean, TRUE)
GROUP BY 2 HAVING count(*) > 1;
-- 3) Mehrere Teilnehmer am selben Konto -> PK template_participant / doppelte Referenzen
SELECT 'teilnehmer_doppelt_verknuepft' AS check, app_user_id, count(*) FROM participant
WHERE app_user_id IS NOT NULL GROUP BY 2 HAVING count(*) > 1;
