"""Passwortregel (app/core/password_policy.py).

Dieselben Beispiele stehen in frontend/lib/password-strength.test.ts - die Live-Anzeige auf
/auth/set-password und die Prüfung im Backend müssen für jedes Passwort gleich urteilen.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.password_policy import ensure_password_acceptable, evaluate_password, personal_tokens

PERSONAL = ("Ben", "Beispiel", "Ben Beispiel", "ben@beispiel.ch", "Musterverein Seeland")

# (Passwort, Stufe 0-4, leicht zu erraten, akzeptiert) - identisch im Frontend-Test
VECTORS = [
    ("", 0, False, False),
    ("kurz", 0, False, False),
    ("elfzeichen1", 0, False, False),
    ("zwoelfzeichen", 1, False, False),
    ("zwoelfzeichenA", 2, False, True),
    ("Zwoelfzeichen1", 2, False, True),
    ("sechzehnzeichenx", 2, False, True),
    ("Sechzehnzeichen1", 3, False, True),
    ("Sechzehnzeichen1!", 4, False, True),
    ("zwanzigzeichenlangxy", 3, False, True),
    ("Tanne-Kiesel-Wolke", 3, False, True),
    ("BenBeispiel-2026!", 1, True, False),
    ("Seeland-Wald-77x", 1, True, False),
    ("Passwort-Sicher-9", 1, True, False),
    ("mmm-Kiesel-Wolke7", 1, True, False),
    ("Fluss Ufer Möwe 42", 4, False, True),
]


@pytest.mark.parametrize(("password", "score", "guessable", "acceptable"), VECTORS)
def test_vectors(password, score, guessable, acceptable):
    result = evaluate_password(password, personal=PERSONAL)
    assert (result.score, result.guessable, result.acceptable) == (score, guessable, acceptable)


def test_personal_tokens_split_name_email_and_organisation():
    assert personal_tokens(PERSONAL) == ["beispiel", "ben", "musterverein", "seeland"]
    assert personal_tokens(["Jo", None, ""]) == []


def test_email_local_part_counts_as_personal():
    assert evaluate_password("Kiesel.Mueller-2026", personal=["k.mueller@example.ch"]).guessable is True


def test_ensure_password_acceptable_raises_password_weak():
    with pytest.raises(HTTPException) as weak:
        ensure_password_acceptable("BenBeispiel-2026!", personal=PERSONAL)
    assert weak.value.status_code == 400 and weak.value.detail["code"] == "password_weak"
    ensure_password_acceptable("Tanne-Kiesel-Wolke", personal=PERSONAL)
