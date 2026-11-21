// GENERATED FILE - do not edit by hand. Source of truth: permissions/catalog.json (repo root).
// Regenerate with: python3 scripts/sync-permission-catalog.py

export type PermissionKey = "meetings.read" | "meetings.read_drafts" | "meetings.edit" | "meetings.approve" | "todos.complete_own" | "templates.edit" | "templates.manage" | "participants.read" | "participants.contacts" | "participants.manage" | "participants.export" | "finances.read" | "finances.manage" | "fines.manage" | "reports.personal" | "files.read" | "files.manage" | "photos.read" | "photos.manage" | "sharing.public" | "submissions.read" | "submissions.review" | "submissions.manage" | "settings.manage" | "activity.read" | "security.read" | "access.manage" | "data.export";
export type PermissionArea = "meetings" | "templates" | "participants" | "finances" | "reports" | "files" | "submissions" | "administration";
export type PermissionFeature = "finance" | "abgabebox" | "custom_domain" | "verify_domain" | "task_packages" | "custom_roles" | "photo_sharing" | "document_designer" | "todo_fines";
export type SystemRoleKey = "admin" | "writer" | "kassier" | "reader";
export type PermissionScope = "all" | "assigned";

export type PermissionInfo = {
  key: PermissionKey;
  area: PermissionArea;
  feature: PermissionFeature | null;
  requiresMfa: boolean;
  implies: PermissionKey[];
  /** Mögliche Reichweiten ("all" zuerst = Standard); leer = Recht ohne Reichweite. */
  scopes: PermissionScope[];
};

export const PERMISSION_AREAS: readonly PermissionArea[] = ["meetings", "templates", "participants", "finances", "reports", "files", "submissions", "administration"];

export const PERMISSIONS: readonly PermissionInfo[] = [
  { key: "meetings.read", area: "meetings", feature: null, requiresMfa: false, implies: [], scopes: [] },
  { key: "meetings.read_drafts", area: "meetings", feature: null, requiresMfa: false, implies: ["meetings.read"], scopes: [] },
  { key: "meetings.edit", area: "meetings", feature: null, requiresMfa: false, implies: ["meetings.read_drafts"], scopes: [] },
  { key: "meetings.approve", area: "meetings", feature: null, requiresMfa: false, implies: ["meetings.read_drafts"], scopes: [] },
  { key: "todos.complete_own", area: "meetings", feature: null, requiresMfa: false, implies: [], scopes: [] },
  { key: "templates.edit", area: "templates", feature: null, requiresMfa: false, implies: ["meetings.read"], scopes: [] },
  { key: "templates.manage", area: "templates", feature: null, requiresMfa: false, implies: ["templates.edit"], scopes: [] },
  { key: "participants.read", area: "participants", feature: null, requiresMfa: false, implies: [], scopes: [] },
  { key: "participants.contacts", area: "participants", feature: null, requiresMfa: false, implies: ["participants.read"], scopes: [] },
  { key: "participants.manage", area: "participants", feature: null, requiresMfa: false, implies: ["participants.contacts"], scopes: [] },
  { key: "participants.export", area: "participants", feature: null, requiresMfa: true, implies: ["participants.read"], scopes: [] },
  { key: "finances.read", area: "finances", feature: "finance", requiresMfa: false, implies: [], scopes: [] },
  { key: "finances.manage", area: "finances", feature: "finance", requiresMfa: false, implies: ["finances.read"], scopes: [] },
  { key: "fines.manage", area: "finances", feature: "finance", requiresMfa: false, implies: ["finances.read"], scopes: [] },
  { key: "reports.personal", area: "reports", feature: null, requiresMfa: false, implies: [], scopes: [] },
  { key: "files.read", area: "files", feature: null, requiresMfa: false, implies: [], scopes: [] },
  { key: "files.manage", area: "files", feature: null, requiresMfa: false, implies: ["files.read"], scopes: [] },
  { key: "photos.read", area: "files", feature: null, requiresMfa: false, implies: [], scopes: [] },
  { key: "photos.manage", area: "files", feature: null, requiresMfa: false, implies: ["photos.read"], scopes: [] },
  { key: "sharing.public", area: "files", feature: null, requiresMfa: false, implies: [], scopes: [] },
  { key: "submissions.read", area: "submissions", feature: "abgabebox", requiresMfa: false, implies: [], scopes: ["all", "assigned"] },
  { key: "submissions.review", area: "submissions", feature: "abgabebox", requiresMfa: false, implies: ["submissions.read"], scopes: ["all", "assigned"] },
  { key: "submissions.manage", area: "submissions", feature: "abgabebox", requiresMfa: false, implies: ["submissions.read"], scopes: [] },
  { key: "settings.manage", area: "administration", feature: null, requiresMfa: true, implies: [], scopes: [] },
  { key: "activity.read", area: "administration", feature: null, requiresMfa: true, implies: [], scopes: [] },
  { key: "security.read", area: "administration", feature: null, requiresMfa: true, implies: [], scopes: [] },
  { key: "access.manage", area: "administration", feature: null, requiresMfa: true, implies: [], scopes: [] },
  { key: "data.export", area: "administration", feature: null, requiresMfa: true, implies: [], scopes: [] },
];

export const PERMISSION_KEYS: readonly PermissionKey[] = PERMISSIONS.map((permission) => permission.key);

export const SYSTEM_ROLE_KEYS: readonly SystemRoleKey[] = ["admin", "writer", "kassier", "reader"];

export const SYSTEM_ROLE_PERMISSIONS: Readonly<Record<SystemRoleKey, readonly PermissionKey[]>> = {
  admin: PERMISSION_KEYS,
  writer: ["meetings.read", "meetings.read_drafts", "meetings.edit", "meetings.approve", "todos.complete_own", "templates.edit", "participants.read", "participants.contacts", "participants.manage", "finances.read", "reports.personal", "files.read", "files.manage", "photos.read", "photos.manage", "sharing.public", "submissions.read", "submissions.review", "submissions.manage"],
  kassier: ["meetings.read", "meetings.read_drafts", "todos.complete_own", "finances.read", "finances.manage", "fines.manage", "reports.personal", "submissions.read"],
  reader: ["meetings.read", "todos.complete_own", "finances.read", "submissions.read"],
};
