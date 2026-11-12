import type { FinanceTransaction } from "@/types/api";

type TFunc = (key: string, values?: Record<string, string | number>) => string;

const CONFLICT_CODES = new Set(["fine_transaction", "todo_fine_transaction", "protocol_finalized", "account_not_empty"]);

/**
 * Backend-Fehler im Finanzbereich als übersetzte Meldung statt rohem (englischem) Backend-Text:
 * 409 mit Code (finance_repository.FinanceConflictError), 403 im Nur-Lesen-Zustand bzw. ohne
 * Recht, 422 bei ungültiger Eingabe, sonst der Bereichs-Fallback. `t` ist useTranslations("finances").
 */
export function financeErrorMessage(error: unknown, t: TFunc, fallbackKey: string): string {
  // Duck-Typing statt instanceof ApiError: so greift es auch für Fehlerobjekte aus Tests/Mocks
  const { status, detail } = (error ?? {}) as { status?: number; detail?: unknown };
  if (status === 409) {
    const code = detail && typeof detail === "object" && "code" in detail ? String((detail as { code: unknown }).code) : "";
    return CONFLICT_CODES.has(code) ? t(`errors.${code}`) : t("errors.conflict");
  }
  if (status === 403) {
    const text = error instanceof Error ? error.message : "";
    return text.includes("nur noch lesend") ? t("errors.readOnly") : t("errors.forbidden");
  }
  if (status === 422) return t("errors.invalid");
  return t(fallbackKey);
}

/** Erklärung, warum eine Buchung gesperrt ist (Tooltip/Hinweis am Schloss). */
export function lockedReasonText(tx: Pick<FinanceTransaction, "locked_reason" | "locked_detail">, t: TFunc): string | null {
  if (!tx.locked_reason) return null;
  const detail = tx.locked_detail ?? "";
  if (tx.locked_reason === "protocol_finalized") return detail ? t("locked.protocolNumber", { number: detail }) : t("locked.protocol");
  if (tx.locked_reason === "todo_fine_transaction") return t("locked.todoFine", { name: detail });
  return t("locked.fine", { name: detail });
}
