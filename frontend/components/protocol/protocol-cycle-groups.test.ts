import { describe, expect, it } from "vitest";

import { groupProtocolsByCycle, visibleCycleGroupCount } from "./protocol-cycle-groups";
import { ProtocolListCycle, ProtocolSummary } from "@/types/api";

const cycle = (year: number, isCurrent = false): ProtocolListCycle => ({
  key: `cfg:${year}`,
  name: `Zyklus ${year}/${year + 1}`,
  cycle_year: year,
  start_date: `${year}-08-01`,
  end_date: `${year + 1}-07-31`,
  is_current: isCurrent,
});

const protocol = (id: string, date: string, c: ProtocolListCycle | null): ProtocolSummary => ({
  id,
  protocol_number: id,
  title: null,
  protocol_date: date,
  status: "abgeschlossen",
  cycle: c,
});

describe("groupProtocolsByCycle", () => {
  it("sortiert nach Zyklus und innerhalb des Zyklus nach Datum, jeweils neueste zuerst", () => {
    const groups = groupProtocolsByCycle([
      protocol("a", "2025-09-01", cycle(2025)),
      protocol("b", "2026-08-12", cycle(2026, true)),
      protocol("c", "2026-06-28", cycle(2025)),
      protocol("d", "2024-10-01", cycle(2024)),
    ]);
    expect(groups.map((g) => g.cycle?.cycle_year)).toEqual([2026, 2025, 2024]);
    expect(groups[1].protocols.map((p) => p.id)).toEqual(["c", "a"]);
  });
});

describe("visibleCycleGroupCount", () => {
  it("zeigt bis zum aktuellen Zyklus plus den vorherigen", () => {
    const groups = groupProtocolsByCycle([2027, 2026, 2025, 2024, 2023].map((y) => protocol(String(y), `${y}-09-01`, cycle(y, y === 2026))));
    expect(visibleCycleGroupCount(groups)).toBe(3);
  });

  it("zeigt ohne aktuellen Zyklus die zwei neuesten Gruppen", () => {
    const groups = groupProtocolsByCycle([2024, 2023, 2022].map((y) => protocol(String(y), `${y}-09-01`, cycle(y))));
    expect(visibleCycleGroupCount(groups)).toBe(2);
  });
});
