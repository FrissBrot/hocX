import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/client";
import { formatMoney } from "@/lib/utils/format";

import { financeErrorMessage, lockedReasonText } from "./finance-errors";

const t = (key: string, values?: Record<string, string | number>) => (values ? `${key}:${JSON.stringify(values)}` : key);

describe("financeErrorMessage", () => {
  it("übersetzt 409 anhand des Codes statt den Backend-Text zu zeigen", () => {
    const error = new ApiError("Diese Buchung gehört …", "conflict", 409, { code: "todo_fine_transaction", message: "x" });
    expect(financeErrorMessage(error, t, "saveTxFailed")).toBe("errors.todo_fine_transaction");
    expect(financeErrorMessage(new ApiError("x", "conflict", 409, { code: "unbekannt" }), t, "saveTxFailed")).toBe("errors.conflict");
  });

  it("erkennt den Nur-Lesen-Zustand und sonstige Fehler", () => {
    expect(financeErrorMessage(new ApiError("Feature 'finance' nur noch lesend (nicht mehr im Abo)", "backend", 403), t, "saveTxFailed")).toBe("errors.readOnly");
    expect(financeErrorMessage(new ApiError("Permission required", "backend", 403), t, "saveTxFailed")).toBe("errors.forbidden");
    expect(financeErrorMessage(new ApiError("Transaction could not be created", "backend", 400), t, "saveTxFailed")).toBe("saveTxFailed");
  });
});

describe("lockedReasonText", () => {
  it("erklärt gesperrte Buchungen", () => {
    expect(lockedReasonText({ locked_reason: null }, t)).toBeNull();
    expect(lockedReasonText({ locked_reason: "todo_fine_transaction", locked_detail: "Max" }, t)).toBe('locked.todoFine:{"name":"Max"}');
    expect(lockedReasonText({ locked_reason: "protocol_finalized", locked_detail: "12" }, t)).toBe('locked.protocolNumber:{"number":"12"}');
    expect(lockedReasonText({ locked_reason: "protocol_finalized", locked_detail: null }, t)).toBe("locked.protocol");
  });
});

describe("formatMoney", () => {
  it("formatiert mit Schweizer Tausendertrennung und Währung", () => {
    expect(formatMoney(1234.5, "CHF", "de")).toMatch(/^1['’]234\.50 CHF$/); // Trennzeichen je nach ICU-Version
    expect(formatMoney(-3, "EUR", "de", { currencyFirst: true })).toBe("EUR −3.00");
    expect(formatMoney(2, "", "de", { sign: true })).toBe("+2.00");
  });
});
