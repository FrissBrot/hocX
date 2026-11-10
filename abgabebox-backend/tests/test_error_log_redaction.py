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
