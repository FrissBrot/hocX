"""Passwortregel für neue Passwörter (alle Setzpfade: Einladung, Passwort vergessen, Profil,
Verwaltung, Plattform-Admin-Konten).

Dieselbe Regel steht im Frontend in ``frontend/lib/password-strength.ts`` (Live-Anzeige auf
``/auth/set-password``); beide Seiten prüfen sie mit denselben Beispielen
(``tests/test_password_policy.py`` bzw. ``lib/password-strength.test.ts``). Wer sie ändert, ändert
beide Dateien und beide Tests.

Regel: mindestens 12 Zeichen (Pflicht) und mindestens Stufe «Mittel» (2 von 4).
- Stufe 1 ab 12 Zeichen, +1 ab 16 Zeichen, +1 bei drei Zeichenarten (klein, gross, Zahl,
  Sonderzeichen), +1 bei allen vier Arten oder ab 20 Zeichen. Zwei Zeichenarten ab 12 Zeichen
  reichen für «Mittel».
- «Leicht zu erraten» (Name, E-Mail, Organisation, häufige Wörter, dreimal dasselbe Zeichen)
  deckelt die Stufe auf «Schwach».
- Zusätzlich (nur im Backend): Passwort aus einem bekannten Leak → 400 ``password_leaked``
  (``app/core/password_leak.py``, SEC-AUTH-015). Erst nach der Stärkeprüfung, damit ein schwaches
  Passwort gar nicht erst abgefragt wird.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from fastapi import HTTPException, status

from app.core.password_leak import check_password

MIN_LENGTH = 12
MIN_SCORE = 2

# Häufige Wörter und Muster (klein geschrieben, als Teilstring geprüft). Gleiche Liste wie im Frontend.
COMMON_WORDS: tuple[str, ...] = (
    "passwort", "password", "kennwort", "hocx", "qwertz", "qwerty", "asdf", "yxcv",
    "123456", "654321", "abc123", "abcdef", "letmein", "welcome", "willkommen", "hallo",
    "admin", "login", "geheim", "secret", "sommer", "winter", "fruehling", "herbst",
    "iloveyou", "schatz", "fussball", "football", "schweiz", "verein",
    # Häufigste Grundwörter aus öffentlich bekannten Passwortlisten (offline, ohne externen Dienst:
    # SEC-AUTH-015) und Tastaturfolgen
    "qwertzuiop", "qwertyuiop", "asdfghjkl", "zxcvbnm", "1q2w3e", "q1w2e3", "112233", "121212",
    "dragon", "monkey", "master", "sunshine", "princess", "shadow", "superman", "batman", "trustno1",
    "starwars", "baseball", "hockey", "liebe", "schalke", "bayern", "hallo123", "changeme", "zugang",
    "startpass", "default", "computer", "internet", "michael", "andrea", "daniel", "thomas",
)
# Ersetzungen, die Passwortlisten kennen (p@ssw0rd = password): geprüft wird auch die so
# zurückgeführte Form.
LEET = str.maketrans({"4": "a", "@": "a", "3": "e", "1": "i", "!": "i", "0": "o", "5": "s", "$": "s", "7": "t"})
# Auf- oder absteigende Folgen ab 5 Zeichen (12345, abcde, 98765)
SEQUENCE_LENGTH = 5

_LOWER = re.compile(r"[a-z]")
_UPPER = re.compile(r"[A-Z]")
_DIGIT = re.compile(r"[0-9]")
_SYMBOL = re.compile(r"[^A-Za-z0-9]")
_REPEAT = re.compile(r"(.)\1\1", re.S)
_SPLIT = re.compile(r"[^a-z0-9äöüàâçéèêëîïôûùÿñ]+")


@dataclass(frozen=True)
class PasswordStrength:
    length: int
    classes: int
    guessable: bool
    score: int  # 0 (leer/zu kurz) … 4

    @property
    def acceptable(self) -> bool:
        return self.length >= MIN_LENGTH and self.score >= MIN_SCORE


def personal_tokens(values: Iterable[str | None]) -> list[str]:
    """Teile von Name, E-Mail und Organisation ab 3 Zeichen, klein geschrieben."""
    tokens: set[str] = set()
    for value in values:
        if not value:
            continue
        lowered = value.strip().lower()
        if "@" in lowered:
            local, _, domain = lowered.partition("@")
            lowered = f"{local} {domain.split('.')[0]}"
        for part in _SPLIT.split(lowered):
            if len(part) >= 3:
                tokens.add(part)
    return sorted(tokens)


def has_sequence(value: str, length: int = SEQUENCE_LENGTH) -> bool:
    """Folge gleichmässig auf- oder absteigender Zeichen (Buchstaben/Ziffern) ab ``length``."""
    run = 1
    direction = 0
    for previous, current in zip(value, value[1:]):
        step = ord(current) - ord(previous)
        if step in (1, -1) and current.isalnum() and previous.isalnum() and (direction in (0, step)):
            run += 1
            direction = step
            if run >= length:
                return True
        else:
            run = 2 if step in (1, -1) and current.isalnum() and previous.isalnum() else 1
            direction = step if run == 2 else 0
    return False


def evaluate_password(password: str, *, personal: Iterable[str | None] = ()) -> PasswordStrength:
    length = len(password)
    classes = sum(1 for pattern in (_LOWER, _UPPER, _DIGIT, _SYMBOL) if pattern.search(password))
    lowered = password.lower()
    unleet = lowered.translate(LEET)
    words = (*COMMON_WORDS, *personal_tokens(personal))
    guessable = length > 0 and (
        any(word in lowered or word in unleet for word in words) or bool(_REPEAT.search(password)) or has_sequence(lowered)
    )
    score = 0
    if length >= MIN_LENGTH:
        score = 1
        if length >= 16:
            score += 1
        if classes >= 3:
            score += 1
        if classes == 4 or length >= 20:
            score += 1
        if score == 1 and classes >= 2:
            score = 2
        score = min(score, 4)
        if guessable:
            score = min(score, 1)
    return PasswordStrength(length=length, classes=classes, guessable=guessable, score=score)


def ensure_password_acceptable(password: str, *, personal: Iterable[str | None] = ()) -> None:
    """400 ``password_weak``, wenn das Passwort die Regel nicht erfüllt, 400 ``password_leaked``,
    wenn es in einem bekannten Leak vorkommt."""
    strength = evaluate_password(password, personal=personal)
    if not strength.acceptable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "password_weak",
                "message": "Das Passwort ist zu schwach: mindestens 12 Zeichen, ohne Name, E-Mail oder häufige Wörter.",
            },
        )
    if check_password(password).leaked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "password_leaked",
                "message": "Dieses Passwort ist aus einem Datenleck bekannt. Bitte wähle ein anderes.",
            },
        )
