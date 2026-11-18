import { describe, expect, it } from "vitest";

import { buildTimelineLayout, chunkDaysForLoading, dayIndexAt, DAY_GAP, GAP, HEADING_HEIGHT, LOAD_LIMIT, scrubberMarks } from "./timeline-layout";

const days = [
  { date: "2026-06-03", count: 7 },
  { date: "2026-05-30", count: 1 },
  { date: "2025-12-24", count: 12 },
  { date: "2023-08-01", count: 3 },
];

describe("buildTimelineLayout", () => {
  it("berechnet Höhen allein aus der Anzahl - ohne ein Bild zu kennen", () => {
    const layout = buildTimelineLayout(days, 1000);
    // 1000 px: (1000 + 8) / (180 + 8) = 5 Spalten
    expect(layout.columns).toBe(5);
    const tile = (1000 - GAP * 4) / 5;
    expect(layout.tile).toBeCloseTo(tile);
    expect(layout.heights[0]).toBeCloseTo(HEADING_HEIGHT + 2 * tile + GAP); // 7 Fotos = 2 Reihen
    expect(layout.offsets[1]).toBeCloseTo(layout.heights[0] + DAY_GAP);
    expect(layout.total).toBeCloseTo(layout.offsets[3] + layout.heights[3]);
  });

  it("nimmt auf schmalen Bildschirmen kleinere Kacheln", () => {
    expect(buildTimelineLayout(days, 390).columns).toBe(3);
  });
});

describe("dayIndexAt", () => {
  it("findet den Tag an einer Position", () => {
    const offsets = [0, 100, 250];
    expect(dayIndexAt(offsets, -5)).toBe(-1);
    expect(dayIndexAt(offsets, 0)).toBe(0);
    expect(dayIndexAt(offsets, 249)).toBe(1);
    expect(dayIndexAt(offsets, 900)).toBe(2);
  });
});

describe("chunkDaysForLoading", () => {
  it("bündelt nur aufeinanderfolgende Tage und bleibt unter dem Limit", () => {
    const missing = [days[0], days[1], days[3]];
    const chunks = chunkDaysForLoading(missing, days);
    // 2026-05-30 und 2023-08-01 sind nicht benachbart (2025-12-24 liegt dazwischen und ist geladen)
    expect(chunks.map((chunk) => [chunk.from, chunk.to, chunk.total])).toEqual([
      ["2026-05-30", "2026-06-03", 8],
      ["2023-08-01", "2023-08-01", 3],
    ]);
  });

  it("teilt bei mehr als LOAD_LIMIT Fotos", () => {
    const big = [{ date: "2026-01-02", count: LOAD_LIMIT - 10 }, { date: "2026-01-01", count: 20 }];
    expect(chunkDaysForLoading(big, big)).toHaveLength(2);
  });
});

describe("scrubberMarks", () => {
  it("setzt Jahre und Monate proportional und lässt zu dichte Beschriftungen aus", () => {
    const layout = buildTimelineLayout(days, 1000);
    const { years, months } = scrubberMarks(layout.days, layout.offsets, layout.total, 400);
    expect(years.map((mark) => mark.label)).toEqual(["2026", "2025", "2023"]);
    expect(months.map((mark) => mark.key)).toContain("2025-12");
    expect(years[0].y).toBe(0);
    expect(Math.max(...years.map((mark) => mark.y))).toBeLessThanOrEqual(400);
  });
});
