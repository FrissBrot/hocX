// GENERATED FILE - do not edit by hand. Source of truth: permissions/features.json (repo root).
// Regenerate with: python3 scripts/sync-feature-catalog.py

export type FeatureCode = "finance" | "abgabebox" | "custom_domain" | "verify_domain" | "task_packages" | "custom_roles" | "photo_sharing" | "document_designer";
export type FeatureModule = "meetings" | "people" | "documents" | "finance" | "media" | "submissions" | "administration";

export type FeatureInfo = {
  code: FeatureCode;
  module: FeatureModule;
  downgrade: "read_only" | "blocked";
  readPermissions: string[];
  requires: FeatureCode[];
};

export const FEATURES: readonly FeatureInfo[] = [
  { code: "finance", module: "finance", downgrade: "read_only", readPermissions: ["finances.read"], requires: [] },
  { code: "abgabebox", module: "submissions", downgrade: "read_only", readPermissions: ["submissions.read"], requires: [] },
  { code: "custom_domain", module: "administration", downgrade: "blocked", readPermissions: [], requires: [] },
  { code: "verify_domain", module: "documents", downgrade: "blocked", readPermissions: [], requires: [] },
  { code: "task_packages", module: "meetings", downgrade: "read_only", readPermissions: [], requires: [] },
  { code: "custom_roles", module: "people", downgrade: "read_only", readPermissions: [], requires: [] },
  { code: "photo_sharing", module: "media", downgrade: "read_only", readPermissions: [], requires: [] },
  { code: "document_designer", module: "documents", downgrade: "read_only", readPermissions: [], requires: [] },
];
