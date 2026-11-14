import { ApiError } from "@/lib/api/client";

/**
 * Übersetzte Fehlermeldung zu einer Backend-Antwort mit stabilem Code
 * (`detail: { code, message }`, z. B. role_service.RoleConflict, Einladung, Login).
 *
 * Kennt der Namespace `<prefix>.<code>`, gewinnt die Übersetzung; sonst bleibt die Meldung des
 * Backends (deutscher Fallback), sonst `fallback`. Reine Hilfsfunktion: `t` kommt vom Aufrufer
 * (useTranslations), siehe CLAUDE.md i18n Regel 3.
 */
type TranslateWithHas = ((key: string) => string) & { has: (key: string) => boolean };

export function apiErrorCode(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  const detail = error.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const code = (detail as { code?: unknown }).code;
    if (typeof code === "string" && /^[a-z_]+$/.test(code)) return code;
  }
  // 429 ohne eigenen Code (z. B. vom Traefik-Rate-Limit vor dem Backend)
  if (error.status === 429) return "rate_limited";
  return null;
}

export function apiErrorMessage(error: unknown, t: TranslateWithHas, prefix: string, fallback: string): string {
  const code = apiErrorCode(error);
  if (code && t.has(`${prefix}.${code}`)) {
    return t(`${prefix}.${code}`);
  }
  return error instanceof Error && error.message ? error.message : fallback;
}
