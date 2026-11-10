import { describe, expect, it } from "vitest";
import { fineCountsByParticipant, fineCountsByType, fineTotalsByCurrency, formatFineTotals } from "./fine-stats";

const format = (amount: number) => amount.toFixed(2);

describe("Bussen-Statistik nach Währung", () => {
  it("addiert Beträge nur innerhalb derselben Währung", () => {
    const totals = fineTotalsByCurrency([
      { count: 1, amount: 5, currency: "CHF" },
      { count: 2, amount: 10, currency: "CHF" },
      { count: 1, amount: 7, currency: "EUR" },
    ]);
    expect(totals).toEqual([
      { currency: "CHF", count: 3, amount: 15 },
      { currency: "EUR", count: 1, amount: 7 },
    ]);
    expect(formatFineTotals(totals, format)).toBe("15.00 CHF · 7.00 EUR");
    expect(formatFineTotals([], format)).toBe("0.00");
  });

  it("fasst Personen über Währungen zusammen, aber nicht bei gleichem Namen", () => {
    expect(fineCountsByParticipant([
      { name: "Anna", count: 1, participant_key: "id:1" },
      { name: "Anna", count: 2, participant_key: "id:1" },
      { name: "Anna", count: 1, participant_key: "id:2" },
    ])).toEqual([{ name: "Anna", count: 3 }, { name: "Anna", count: 1 }]);
  });

  it("zählt Bussentypen über alle Währungen", () => {
    expect(fineCountsByType([
      { fine_type: "late", label: "Verspätet", count: 1 },
      { fine_type: "late", label: "Verspätet", count: 2 },
    ])).toEqual([{ fine_type: "late", label: "Verspätet", count: 3 }]);
  });
});
