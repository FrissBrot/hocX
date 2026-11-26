// Lesbare Bezeichnung für Einträge im Audit-Log (Verlauf, /admin/audit). Statt jede Aktion einzeln
// zu übersetzen: Bereich (Präfix vor dem ersten Punkt) und Vorgang (aus der Endung abgeleitet).
// Unbekannte Bereiche/Vorgänge erscheinen lesbar statt als Code.

export type AuditVerb =
  | "loginFailed"
  | "mfaFailed"
  | "login"
  | "viewed"
  | "exported"
  | "imported"
  | "deleted"
  | "created"
  | "updated"
  | "restored"
  | "collected"
  | "revoked"
  | "published"
  | "other";

export const AUDIT_CATEGORIES = [
  "activity", "admin", "agenda_item", "backup", "calendar_feed", "context_visibility", "document", "document_asset", "document_brand", "document_settings",
  "document_template", "document_verification", "event", "file", "file_import", "finance_account", "finance_settings",
  "finance_transaction", "fine", "fine_tariff", "identity_verification", "mfa", "participant", "password", "personal_data",
  "photo", "privacy_settings", "protocol", "public_link", "retention", "role", "sessions", "submission", "submission_assignment",
  "submission_file", "submission_upload", "table_snapshot", "task_package", "template", "template_element", "tenant", "todo",
  "todo_fine", "user",
] as const;

export function auditVerb(action: string): AuditVerb {
  // Letztes Segment: "backup.restore.create" -> "create"
  const suffix = action.slice(action.lastIndexOf(".") + 1);
  if (suffix.includes("login_failed")) return "loginFailed";
  if (suffix.includes("mfa_failed")) return "mfaFailed";
  if (suffix === "login") return "login";
  if (suffix.includes("viewed")) return "viewed";
  if (suffix.includes("export")) return "exported";
  if (suffix.includes("imported")) return "imported";
  if (/(deleted|delete$|purge|cleanup|trash|^remove$|removed)/.test(suffix)) return "deleted";
  if (/(created|create$|upserted|added|requested|^upload$|duplicate|enroll|invited)/.test(suffix)) return "created";
  if (/(restored|^restore$)/.test(suffix)) return "restored";
  if (suffix.includes("collected")) return "collected";
  if (/(revoke|withdrawn|cancel|rejected|reopened)/.test(suffix)) return "revoked";
  if (/(publish|approved)/.test(suffix)) return "published";
  if (/(updated|^update|change|synced|reordered|assigned|edit|reverted|regenerated|rotated|render|renamed|postponed)/.test(suffix)) return "updated";
  return "other";
}

export function humanizeCode(code: string): string {
  const text = code.replace(/[._]+/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

type TFunc = (key: string) => string;

/** "Protokoll · gelöscht"; t ist der Namespace common.auditActions. */
export function describeAuditAction(action: string, t: TFunc): string {
  const category = action.split(".", 1)[0];
  const categoryLabel = (AUDIT_CATEGORIES as readonly string[]).includes(category) ? t(`categories.${category}`) : humanizeCode(category);
  const verb = auditVerb(action);
  const verbLabel = verb === "other" ? humanizeCode(action.slice(action.indexOf(".") + 1)) : t(`verbs.${verb}`);
  return `${categoryLabel} · ${verbLabel}`;
}

// ── Bereiche des Plattform-Audit-Logs (1.5.1, Design «hocX Audit-Log») ─────────────────────────
// Einzige Zuordnung Bereich → Kategorien: Filter-Chips, Zähler (Backend zählt je Kategorie) und
// Farbpunkte lesen sie. Übersetzung `admin.auditLog.areas.<bereich>`.

export const AUDIT_AREAS = ["auth", "content", "finance", "admin", "privacy"] as const;
export type AuditArea = (typeof AUDIT_AREAS)[number];

const AREA_BY_CATEGORY: Record<string, AuditArea> = {
  user: "auth", mfa: "auth", password: "auth", sessions: "auth",
  calendar_feed: "content", context_visibility: "content", document: "content", document_asset: "content", document_brand: "content",
  document_settings: "content", document_template: "content", document_verification: "content", event: "content", participant: "content",
  protocol: "content", submission_assignment: "content", submission_file: "content", submission_upload: "content", table_snapshot: "content",
  task_package: "content", template: "content", todo: "content",
  agenda_item: "content", file: "content", file_import: "content", photo: "content", submission: "content", template_element: "content",
  finance_account: "finance", finance_settings: "finance", finance_transaction: "finance", fine: "finance", fine_tariff: "finance", todo_fine: "finance",
  admin: "admin", backup: "admin", identity_verification: "admin", role: "admin", tenant: "admin",
  personal_data: "privacy", privacy_settings: "privacy", public_link: "privacy", retention: "privacy", activity: "privacy",
};

export function auditCategory(action: string): string {
  return action.split(".", 1)[0];
}

/** Bereich einer Aktion; unbekannte Kategorien gehören zu keinem Bereich (null). */
export function auditArea(action: string): AuditArea | null {
  return AREA_BY_CATEGORY[auditCategory(action)] ?? null;
}

/** Kategorien eines Bereichs (für den Filter `category=` der API). */
export function auditAreaCategories(area: AuditArea): string[] {
  return Object.entries(AREA_BY_CATEGORY).filter(([, value]) => value === area).map(([category]) => category);
}

/** Zähler je Bereich aus den Zählern je Kategorie (GET /api/admin/audit-log/timeline). */
export function countByArea(byCategory: Record<string, number>): Record<AuditArea, number> {
  const result = Object.fromEntries(AUDIT_AREAS.map((area) => [area, 0])) as Record<AuditArea, number>;
  for (const [category, count] of Object.entries(byCategory)) {
    const area = AREA_BY_CATEGORY[category];
    if (area) result[area] += count;
  }
  return result;
}

/** «Bereich · Verb» für das Plattform-Audit-Log. Unbekannte Kategorien oder Vorgänge erscheinen als
 * Code (nicht geraten «lesbar»), damit nichts falsch übersetzt wird. */
export function auditActionLabel(action: string, t: TFunc): { label: string; known: boolean } {
  const category = auditCategory(action);
  const verb = auditVerb(action);
  if (!(AUDIT_CATEGORIES as readonly string[]).includes(category) || verb === "other") return { label: action, known: false };
  return { label: `${t(`categories.${category}`)} · ${t(`verbs.${verb}`)}`, known: true };
}

/** Initialen für den Avatar «Von» (zwei Buchstaben, aus Name oder E-Mail). */
export function auditInitials(name: string | null | undefined): string {
  const source = (name ?? "").trim();
  if (!source) return "·";
  const parts = source.includes("@") ? [source] : source.split(/[\s-]+/).filter(Boolean);
  return parts.map((part) => part[0]).join("").slice(0, 2).toUpperCase();
}
