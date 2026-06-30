from pydantic import BaseModel


class OidcConfigPublic(BaseModel):
    """Returned to unauthenticated clients — no secrets."""
    tenant_id: int
    enabled: bool
    auto_redirect: bool
    issuer_url: str

    model_config = {"from_attributes": True}


class OidcConfigRead(BaseModel):
    tenant_id: int
    enabled: bool
    auto_redirect: bool
    issuer_url: str
    client_id: str
    scopes: str

    model_config = {"from_attributes": True}


class OidcConfigWrite(BaseModel):
    enabled: bool = False
    auto_redirect: bool = False
    issuer_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    scopes: str = "openid email profile"
