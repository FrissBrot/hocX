import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AssignmentPublic(BaseModel):
    public_slug: str
    title: str
    description: str | None = None


class AssignmentDetailPublic(BaseModel):
    public_slug: str
    title: str
    description: str | None = None
    allowed_file_types: list[str]
    max_files_per_element: int | None
    max_file_size_mb: int


class ElementPublic(BaseModel):
    element_ref: str
    label: str
    window_start: str | None = None
    window_end: str | None = None
    uploaded_count: int = 0


class UploadResult(BaseModel):
    ok: bool
    files_received: int
    image_duplicate_warnings: list[str] = []


class CaptchaVerifyResult(BaseModel):
    session_token: str
    expires_in_seconds: int


class VerifyRequest(BaseModel):
    """Body von POST /api/public/verify: nur der im Browser berechnete Hash, optional die
    Dokument-ID aus dem QR-Code. Die Datei selbst verlässt den Browser nie."""

    model_config = ConfigDict(extra="forbid")

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_id: uuid.UUID | None = None


class VerifyResult(BaseModel):
    """found=false trägt bewusst keine weiteren Felder - auch keinen Hinweis darauf, ob eine
    mitgeschickte Dokument-ID existiert (keine Aufzählung möglich)."""

    found: bool
    document_id: uuid.UUID | None = None
    document_id_matches: bool | None = None
    document_type: str | None = None
    title: str | None = None
    status_code: str | None = None
    version_label: str | None = None
    created_at: datetime | None = None
    is_superseded: bool | None = None
    latest_version_label: str | None = None
    tenant_name: str | None = None
    tenant_public_id: uuid.UUID | None = None
    tenant_has_logo: bool | None = None
    organization_verified: bool | None = None
