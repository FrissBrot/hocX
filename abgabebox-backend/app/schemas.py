from pydantic import BaseModel


class AssignmentPublic(BaseModel):
    public_slug: str
    title: str
    description: str | None = None


class AssignmentDetailPublic(BaseModel):
    public_slug: str
    title: str
    description: str | None = None
    allowed_file_types: list[str]
    max_files_per_element: int
    max_file_size_mb: int


class ElementPublic(BaseModel):
    element_ref: str
    label: str
    window_start: str | None = None
    window_end: str | None = None


class UploadResult(BaseModel):
    ok: bool
    files_received: int
