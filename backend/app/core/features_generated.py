# GENERATED FILE - do not edit by hand. Source of truth: permissions/features.json (repo root).
# Regenerate with: python3 scripts/sync-feature-catalog.py
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class F(StrEnum):
    FINANCE = "finance"
    ABGABEBOX = "abgabebox"
    CUSTOM_DOMAIN = "custom_domain"
    VERIFY_DOMAIN = "verify_domain"
    TASK_PACKAGES = "task_packages"
    CUSTOM_ROLES = "custom_roles"
    PHOTO_SHARING = "photo_sharing"
    DOCUMENT_DESIGNER = "document_designer"


@dataclass(frozen=True)
class FeatureDef:
    module: str
    downgrade: str
    read_permissions: frozenset[str]
    requires: tuple[str, ...]


FEATURES: dict[F, FeatureDef] = {
    F.FINANCE: FeatureDef(module="finance", downgrade="read_only", read_permissions=frozenset({"finances.read"}), requires=()),
    F.ABGABEBOX: FeatureDef(module="submissions", downgrade="read_only", read_permissions=frozenset({"submissions.read"}), requires=()),
    F.CUSTOM_DOMAIN: FeatureDef(module="administration", downgrade="blocked", read_permissions=frozenset(), requires=()),
    F.VERIFY_DOMAIN: FeatureDef(module="documents", downgrade="blocked", read_permissions=frozenset(), requires=()),
    F.TASK_PACKAGES: FeatureDef(module="meetings", downgrade="read_only", read_permissions=frozenset(), requires=()),
    F.CUSTOM_ROLES: FeatureDef(module="people", downgrade="read_only", read_permissions=frozenset(), requires=()),
    F.PHOTO_SHARING: FeatureDef(module="media", downgrade="read_only", read_permissions=frozenset(), requires=()),
    F.DOCUMENT_DESIGNER: FeatureDef(module="documents", downgrade="read_only", read_permissions=frozenset(), requires=()),
}
