// formatDate: reine Daten bleiben wie geliefert, Zeitstempel zählen nach Schweizer Zeit
// (Nachtlauf 2026-11-22: die Prüfseite zeigte das Erstelldatum eines Dokuments als UTC-Datum,
// ein um 00:30 erstelltes Dokument stand dort mit dem Vortag).
import { describe, expect, it } from "vitest";

import { formatDate } from "@/lib/format";

describe("formatDate", () => {
  it("formats plain ISO dates without shifting them", () => {
    expect(formatDate("2026-11-22")).toBe("22.11.2026");
    expect(formatDate("2026-01-01")).toBe("01.01.2026");
  });

  it("uses the Swiss calendar day for timestamps", () => {
    expect(formatDate("2026-11-21T23:30:00+00:00")).toBe("22.11.2026");
    expect(formatDate("2026-11-21T23:30:00Z")).toBe("22.11.2026");
    expect(formatDate("2026-06-30T22:15:00Z")).toBe("01.07.2026");
    expect(formatDate("2026-05-01T00:00:00Z")).toBe("01.05.2026");
    expect(formatDate("2026-11-22T00:30:00+01:00")).toBe("22.11.2026");
  });

  it("handles empty and invalid input", () => {
    expect(formatDate(null)).toBe("");
    expect(formatDate("")).toBe("");
    expect(formatDate("kein Datum")).toBe("kein Datum");
  });
});
