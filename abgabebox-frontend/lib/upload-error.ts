// Fehlerantworten und Hinweise des Abgabebox-Backends in der gewählten Sprache.
// Das Backend liefert neben dem deutschen `detail` einen stabilen `code` mit `params`
// (abgabebox-backend/app/public_errors.py); übersetzt wird über `errors.server.<code>`.
// Unbekannte oder fehlende Codes ergeben die allgemeine Meldung, nie deutschen Rohtext.

export const SERVER_ERROR_CODES = [
  "not_found",
  "feature_disabled",
  "element_closed",
  "captcha_invalid",
  "captcha_expired",
  "no_file",
  "too_many_files_request",
  "file_type_not_allowed",
  "file_too_large",
  "upload_too_large",
  "content_mismatch",
  "storage_limit",
  "too_many_files_total",
  "save_failed",
  "malware",
  "scan_failed",
  "upload_busy",
  "db_busy",
  "storage_write_fenced",
  "maintenance",
] as const;

export type ServerErrorCode = (typeof SERVER_ERROR_CODES)[number];

type Translate = (key: string, values?: Record<string, string | number>) => string;

function isServerErrorCode(value: unknown): value is ServerErrorCode {
  return typeof value === "string" && (SERVER_ERROR_CODES as readonly string[]).includes(value);
}

function scalarParams(value: unknown): Record<string, string | number> {
  if (!value || typeof value !== "object") return {};
  const params: Record<string, string | number> = {};
  for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
    if (typeof entry === "string" || typeof entry === "number") params[key] = entry;
  }
  return params;
}

/** Meldung zu einer Fehlerantwort (geparster JSON-Body oder null), `t` im Namespace `abgabebox.upload`. */
export function serverErrorMessage(t: Translate, body: unknown): string {
  const code = body && typeof body === "object" ? (body as { code?: unknown }).code : undefined;
  if (!isServerErrorCode(code)) return t("errors.uploadFailedGeneric");
  return t(`errors.server.${code}`, scalarParams((body as { params?: unknown }).params));
}

/** Hinweise «ähnelt einem bereits hochgeladenen Bild» aus der Upload-Antwort. */
export function duplicateWarnings(t: Translate, result: unknown): string[] {
  const files = result && typeof result === "object" ? (result as { image_duplicate_files?: unknown }).image_duplicate_files : undefined;
  if (!Array.isArray(files)) return [];
  return files.filter((name): name is string => typeof name === "string").map((filename) => t("duplicateWarning", { filename }));
}
