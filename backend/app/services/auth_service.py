from app.core.security import CurrentUser


class AuthService:
    def login_stub(self) -> dict[str, str]:
        return {"mode": "stub", "message": "OIDC will be added later without replacing app_user-based authorization."}

    def session_stub(self, user: CurrentUser) -> dict[str, int | str | None]:
        return {
            "mode": "demo",
            "user_id": user.user_id,
            "role": user.role,
            "message": "Role checks are currently driven by demo headers and stay isolated behind the auth layer.",
        }
