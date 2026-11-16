import { describe, expect, it } from "vitest";
import { eventMatchesCycleFilter, getCycleYear } from "./cycle";

const vereinsjahr = { id: "vj", reset_month: 7, reset_day: 31 };

describe("eventMatchesCycleFilter", () => {
  it("filtert ohne Zyklus nicht", () => {
    expect(eventMatchesCycleFilter([], null, "2026-10-12", 0)).toBe(true);
  });

  it("trifft den Zyklus des Referenzdatums", () => {
    const assignments = [{ cycle_config_id: "vj", cycle_year: 2026 }];
    expect(eventMatchesCycleFilter(assignments, vereinsjahr, "2026-10-12", 0)).toBe(true);
    expect(eventMatchesCycleFilter(assignments, vereinsjahr, "2026-07-31", 0)).toBe(false);
  });

  it("verschiebt um den Offset", () => {
    const assignments = [{ cycle_config_id: "vj", cycle_year: 2025 }];
    expect(eventMatchesCycleFilter(assignments, vereinsjahr, "2026-10-12", -1)).toBe(true);
    expect(eventMatchesCycleFilter(assignments, vereinsjahr, "2026-10-12", 0)).toBe(false);
  });

  it("ignoriert Zuordnungen anderer Zyklen", () => {
    const assignments = [{ cycle_config_id: "semester", cycle_year: 2026 }];
    expect(eventMatchesCycleFilter(assignments, vereinsjahr, "2026-10-12", 0)).toBe(false);
  });
});

// Muss mit backend/app/core/cycle_utils.py::get_cycle_year übereinstimmen: ein Stichtag, den es
// im Monat nicht gibt (29.02. ausserhalb von Schaltjahren, 31.04., 30.02.), wird auf den letzten
// Tag des Monats gekappt - nicht in den Folgemonat übertragen.
describe("getCycleYear mit nicht existierendem Stichtag", () => {
  it("kappt 29.02. in Nicht-Schaltjahren auf den 28.02.", () => {
    expect(getCycleYear("2025-02-28", 2, 29)).toBe(2024);
    expect(getCycleYear("2025-03-01", 2, 29)).toBe(2025);
    expect(getCycleYear("2024-02-29", 2, 29)).toBe(2023);
    expect(getCycleYear("2024-03-01", 2, 29)).toBe(2024);
  });

  it("kappt 31.04. auf den 30.04.", () => {
    expect(getCycleYear("2026-04-30", 4, 31)).toBe(2025);
    expect(getCycleYear("2026-05-01", 4, 31)).toBe(2026);
  });

  it("kappt 30.02. auf den letzten Februartag", () => {
    expect(getCycleYear("2026-03-01", 2, 30)).toBe(2026);
    expect(getCycleYear("2026-03-02", 2, 30)).toBe(2026);
  });

  it("Zyklusfilter trifft die Zuordnung, die das Backend für den Termin anlegt", () => {
    const config = { id: "fj", reset_month: 2, reset_day: 29 };
    expect(eventMatchesCycleFilter([{ cycle_config_id: "fj", cycle_year: 2025 }], config, "2025-03-01", 0)).toBe(true);
  });
});
