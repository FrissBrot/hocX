"""Kuratierte Fehler der öffentlichen Abgabebox mit stabilem Code.

Die Abgabebox-Oberfläche ist mehrsprachig, die Meldungen hier sind deutsch. Damit sie in der
gewählten Sprache erscheinen, trägt jede kuratierte Antwort zusätzlich einen festen ``code`` und
die Werte für Platzhalter (``params``); das Frontend übersetzt über
``abgabebox.upload.errors.server.<code>``. ``detail`` bleibt als deutscher Klartext erhalten
(Logs, ältere Clients). Neuer Code = Übersetzung in allen Locales des abgabebox-frontend.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException


class PublicError(HTTPException):
    def __init__(
        self,
        status_code: int,
        code: str,
        detail: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code
        self.params = params or {}

    def body(self) -> dict[str, Any]:
        return {"detail": self.detail, "code": self.code, "params": self.params}
