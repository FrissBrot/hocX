import { describe, expect, it } from "vitest";
import { eventMatchesCycleFilter } from "./cycle";

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
