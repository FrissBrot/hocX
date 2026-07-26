from pydantic import BaseModel


class PlatformOidcConfigPublic(BaseModel):
    """Returned to unauthenticated clients on the admin login page - no secrets."""
    enabled: bool
    issuer_url: str

    model_config = {"from_attributes": True}


class PlatformOidcConfigRead(BaseModel):
    """Returned to an already-authenticated platform admin - still no client_secret."""
    enabled: bool
    issuer_url: str
    client_id: str
    scopes: str

    model_config = {"from_attributes": True}


class PlatformOidcConfigWrite(BaseModel):
    enabled: bool = False
    issuer_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    scopes: str = "openid email profile"
