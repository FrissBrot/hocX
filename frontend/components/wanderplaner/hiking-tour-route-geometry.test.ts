import { describe, expect, it } from "vitest";

import { MarchTimeEntry } from "@/types/api";

import { buildTrack, dangerAhead, dangerLengths, elevationAt, formatClock, plannedMinutesAt, projectOnTrack, remainingAscent } from "./hiking-tour-route-geometry";

const profile = [
  { distance_m: 0, elevation_m: 500, lat: 47, lon: 8.5 },
  { distance_m: 1000, elevation_m: 600, lat: 47, lon: 8.5131 },
  { distance_m: 2000, elevation_m: 550, lat: 47, lon: 8.5262 },
  { distance_m: 3000, elevation_m: 700, lat: 47, lon: 8.5393 },
];

const entry = (sequence: number, kind: MarchTimeEntry["kind"], segment: number, cumulative: number, minutes: number, breakMinutes = 0): MarchTimeEntry => ({
  sequence, label: null, kind, elevation_m: null, segment_distance_m: segment, cumulative_distance_m: cumulative,
  segment_ascent_m: 0, segment_descent_m: 0, segment_lkm: 0, cumulative_lkm: 0, segment_duration_minutes: minutes,
  cumulative_duration_minutes: 0, planned_arrival: null, break_minutes: breakMinutes, planned_departure: null, remarks: null,
});

describe("hiking tour route geometry", () => {
  it("projects a position onto the route and reports the offset", () => {
    const track = buildTrack(profile, []);
    const projection = projectOnTrack(track, 47.0005, 8.5196);
    expect(projection?.distance_m).toBeGreaterThan(1450);
    expect(projection?.distance_m).toBeLessThan(1550);
    expect(projection?.offset_m).toBeGreaterThan(50);
    expect(projection?.offset_m).toBeLessThan(60);
  });

  it("builds distances from route coordinates when no profile exists", () => {
    const track = buildTrack(null, [[47, 8.5], [47, 8.5131]]);
    expect(track[1].distance_m).toBeGreaterThan(990);
    expect(track[1].distance_m).toBeLessThan(1000);
  });

  it("interpolates elevation and sums only the remaining ascent", () => {
    const track = buildTrack(profile, []);
    expect(elevationAt(track, 500)).toBe(550);
    expect(remainingAscent(track, 500)).toBe(50 + 150);
  });

  it("warns inside a danger zone and ahead of the next one", () => {
    const segments = [
      { from_m: 0, to_m: 1000, danger: "normal" as const },
      { from_m: 1000, to_m: 1200, danger: "steep_exposed" as const },
      { from_m: 2500, to_m: 3000, danger: "alpine" as const },
    ];
    expect(dangerAhead(segments, 1100)).toEqual({ state: "inside", danger: "steep_exposed", remaining_m: 100 });
    expect(dangerAhead(segments, 1300)).toEqual({ state: "ahead", danger: "alpine", distance_m: 1200, length_m: 500 });
    expect(dangerAhead(segments, 300)).toEqual({ state: "ahead", danger: "steep_exposed", distance_m: 700, length_m: 200 });
    expect(dangerAhead(segments, 300, 500)).toBeNull();
    expect(dangerLengths(segments)).toEqual({ steep_exposed: 200, alpine: 500 });
  });

  it("includes breaks of passed waypoints in the planned time and skips emergency exits", () => {
    const entries = [
      entry(0, "START", 0, 0, 0),
      entry(1, "BREAK", 1000, 1000, 20, 15),
      entry(500001, "EMERGENCY_EXIT", 400, 1400, 10),
      entry(2, "END", 1000, 2000, 30),
    ];
    expect(plannedMinutesAt(entries, 500)).toBe(10);
    expect(plannedMinutesAt(entries, 1500)).toBe(20 + 15 + 15);
    expect(formatClock(8 * 60 + 5)).toBe("8:05");
  });
});
