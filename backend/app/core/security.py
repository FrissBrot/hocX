from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException, status


@dataclass
class CurrentUser:
    user_id: int | None
    role: str


def get_current_user(
    x_demo_user_id: int | None = Header(default=1),
    x_demo_role: str | None = Header(default="admin"),
) -> CurrentUser:
    role = (x_demo_role or "admin").lower()
    if role not in {"admin", "editor", "readonly"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported demo role")
    return CurrentUser(user_id=x_demo_user_id, role=role)


def require_editor(user: CurrentUser) -> CurrentUser:
    if user.role not in {"admin", "editor"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Editor role required")
    return user
