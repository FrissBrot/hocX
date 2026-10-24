"""Anfragen für passwortgeschützte Exporte (Datenauskunft, Vereinsexport)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ProtectedExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Im Body, nie in der URL (SECURITY-RULES 3.2); data_export.archive prüft zusätzlich ohne Leerraum.
    password: str = Field(min_length=12, max_length=200)
