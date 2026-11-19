"""Datenschutz-Audit PRIV-002: Fehlertexte im gemeinsamen Fehlerprotokoll ohne Personendaten."""
from app.repository import redact


def test_redact_removes_postgres_values_parameters_and_emails():
    message = (
        "DETAIL:  Key (sha256)=(abc) already exists.\n"
        "[parameters: {'original_name': 'Arztzeugnis Muster.pdf'}]\n"
        "Kontakt: einreicher@example.com"
    )

    cleaned = redact(message)

    assert "abc" not in cleaned
    assert "Arztzeugnis" not in cleaned
    assert "einreicher@example.com" not in cleaned


class _CapturingSession:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)

    def commit(self):
        pass


def test_link_token_in_request_path_is_masked_in_error_log():
    """Der Abgabebox-Link trägt sein Zugangsgeheimnis im Pfad (/api/public/{link_token}/…). Bei
    einem 500 landete er sonst unmaskiert in system_error_log.request_path (SECURITY-RULES 5.1,
    wie backend/app/core/error_log.redact_path)."""
    from app.repository import insert_error_log

    token = "geheimer-abgabe-link-token"
    db = _CapturingSession()
    insert_error_log(
        db, tenant_id=None, request_method="POST",
        request_path=f"/api/public/{token}/assignments/fotos/elements/abc/upload",
        status_code=500, error_type="RuntimeError", error_message="kaputt", traceback=None,
    )

    params = db.statements[0].compile().params
    assert token not in params["request_path"]
    assert params["request_path"] == "/api/public/<token>/assignments/fotos/elements/abc/upload"


def test_redact_path_keeps_paths_without_secret():
    from app.repository import redact_path

    assert redact_path("/api/public/verify") == "/api/public/verify"
    assert redact_path("/api/public/verify/site") == "/api/public/verify/site"
    assert redact_path("/api/public/maintenance-status") == "/api/public/maintenance-status"
    assert redact_path(None) is None
