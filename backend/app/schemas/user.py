from pydantic import BaseModel


class UserRead(BaseModel):
    id: int
    tenant_id: int
    name: str
    email: str
    is_active: bool

    model_config = {"from_attributes": True}
