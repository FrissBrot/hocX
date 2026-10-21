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
  "admin", "backup", "calendar_feed", "document", "document_asset", "document_brand", "document_settings",
  "document_template", "document_verification", "event", "finance_account", "finance_transaction", "fine",
  "fine_tariff", "identity_verification", "participant", "personal_data", "privacy_settings", "protocol",
  "retention", "submission_assignment", "submission_file", "submission_upload", "table_snapshot",
  "task_package", "template", "tenant", "todo", "user",
] as const;

export function auditVerb(action: string): AuditVerb {
  // Letztes Segment: "backup.restore.create" -> "create"
  const suffix = action.slice(action.lastIndexOf(".") + 1);
  if (suffix.includes("login_failed")) return "loginFailed";
  if (suffix.includes("mfa_failed")) return "mfaFailed";
  if (suffix === "login") return "login";
  if (suffix.includes("viewed")) return "viewed";
  if (suffix.includes("exported")) return "exported";
  if (suffix.includes("imported")) return "imported";
  if (/(deleted|^delete$|purge|cleanup)/.test(suffix)) return "deleted";
  if (/(created|^create$|upserted|added|requested|^upload$|duplicate)/.test(suffix)) return "created";
  if (/(restored|^restore$)/.test(suffix)) return "restored";
  if (suffix.includes("collected")) return "collected";
  if (/(revoked|withdrawn|cancel|rejected|reopened)/.test(suffix)) return "revoked";
  if (/(publish|approved)/.test(suffix)) return "published";
  if (/(updated|^update$|changed|synced|reordered|assigned|edit|reverted|regenerated|rotated|render)/.test(suffix)) return "updated";
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
