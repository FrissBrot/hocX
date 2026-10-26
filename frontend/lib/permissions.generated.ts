// GENERATED FILE - do not edit by hand. Source of truth: permissions/catalog.json (repo root).
// Regenerate with: python3 scripts/sync-permission-catalog.py

export type PermissionKey = "meetings.read" | "meetings.read_drafts" | "meetings.edit" | "templates.edit" | "templates.manage" | "participants.manage" | "finances.read" | "finances.manage" | "reports.personal" | "files.manage" | "submissions.read" | "submissions.manage" | "settings.manage" | "access.manage" | "data.export";
export type PermissionArea = "meetings" | "templates" | "participants" | "finances" | "reports" | "files" | "submissions" | "administration";
export type PermissionFeature = "finance" | "abgabebox";
export type SystemRoleKey = "admin" | "writer" | "kassier" | "reader";

export type PermissionInfo = {
  key: PermissionKey;
  area: PermissionArea;
  feature: PermissionFeature | null;
  requiresMfa: boolean;
  implies: PermissionKey[];
};

export const PERMISSION_AREAS: readonly PermissionArea[] = ["meetings", "templates", "participants", "finances", "reports", "files", "submissions", "administration"];

export const PERMISSIONS: readonly PermissionInfo[] = [
  { key: "meetings.read", area: "meetings", feature: null, requiresMfa: false, implies: [] },
  { key: "meetings.read_drafts", area: "meetings", feature: null, requiresMfa: false, implies: ["meetings.read"] },
  { key: "meetings.edit", area: "meetings", feature: null, requiresMfa: false, implies: ["meetings.read_drafts"] },
  { key: "templates.edit", area: "templates", feature: null, requiresMfa: false, implies: ["meetings.read"] },
  { key: "templates.manage", area: "templates", feature: null, requiresMfa: false, implies: ["templates.edit"] },
  { key: "participants.manage", area: "participants", feature: null, requiresMfa: false, implies: [] },
  { key: "finances.read", area: "finances", feature: "finance", requiresMfa: false, implies: [] },
  { key: "finances.manage", area: "finances", feature: "finance", requiresMfa: false, implies: ["finances.read"] },
  { key: "reports.personal", area: "reports", feature: null, requiresMfa: false, implies: [] },
  { key: "files.manage", area: "files", feature: null, requiresMfa: false, implies: [] },
  { key: "submissions.read", area: "submissions", feature: "abgabebox", requiresMfa: false, implies: [] },
  { key: "submissions.manage", area: "submissions", feature: "abgabebox", requiresMfa: false, implies: ["submissions.read"] },
  { key: "settings.manage", area: "administration", feature: null, requiresMfa: true, implies: [] },
  { key: "access.manage", area: "administration", feature: null, requiresMfa: true, implies: [] },
  { key: "data.export", area: "administration", feature: null, requiresMfa: true, implies: [] },
];

export const PERMISSION_KEYS: readonly PermissionKey[] = PERMISSIONS.map((permission) => permission.key);

export const SYSTEM_ROLE_KEYS: readonly SystemRoleKey[] = ["admin", "writer", "kassier", "reader"];

export const SYSTEM_ROLE_PERMISSIONS: Readonly<Record<SystemRoleKey, readonly PermissionKey[]>> = {
  admin: PERMISSION_KEYS,
  writer: ["meetings.read", "meetings.read_drafts", "meetings.edit", "templates.edit", "participants.manage", "finances.read", "reports.personal", "files.manage", "submissions.read", "submissions.manage"],
  kassier: ["meetings.read", "meetings.read_drafts", "finances.read", "finances.manage", "reports.personal", "submissions.read"],
  reader: ["meetings.read", "finances.read", "submissions.read"],
};
