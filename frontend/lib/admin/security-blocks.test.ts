import { describe, expect, it } from "vitest";

import { durationParts, ganttDayTicks, ganttGeometry, parseBlockMinutes, remainingPercent } from "./security-blocks";

describe("Sperren-Hilfen", () => {
  it("zerlegt Restzeiten", () => {
    expect(durationParts(90_061)).toEqual({ days: 1, hours: 1, minutes: 1, seconds: 1 });
    expect(durationParts(-5)).toEqual({ days: 0, hours: 0, minutes: 0, seconds: 0 });
  });

  it("berechnet den Restanteil begrenzt auf 0-100", () => {
    expect(remainingPercent(200, 100, 150)).toBe(50);
    expect(remainingPercent(200, 100, 300)).toBe(0);
    expect(remainingPercent(200, 200, 100)).toBe(0);
  });

  it("liest Voreinstellung oder freie Minuten", () => {
    expect(parseBlockMinutes("360", "", 43_200)).toBe(360);
    expect(parseBlockMinutes("custom", " 45 ", 43_200)).toBe(45);
    expect(parseBlockMinutes("custom", "0", 43_200)).toBeNull();
    expect(parseBlockMinutes("custom", "50000", 43_200)).toBeNull();
    expect(parseBlockMinutes("custom", "1e3", 43_200)).toBeNull();
  });

  it("legt Balken ins Fenster und schneidet ab", () => {
    const start = "2026-11-16T00:00:00Z";
    const end = "2026-11-23T00:00:00Z";
    const inside = ganttGeometry("2026-11-19T12:00:00Z", "2026-11-20T00:00:00Z", start, end);
    expect(inside.left).toBeCloseTo(50, 5);
    expect(inside.width).toBeCloseTo((12 / 168) * 100, 5);
    const clipped = ganttGeometry("2026-11-15T00:00:00Z", "2026-11-16T12:00:00Z", start, end);
    expect(clipped.left).toBe(0);
    const beyond = ganttGeometry("2026-11-22T23:00:00Z", "2026-11-30T00:00:00Z", start, end);
    expect(beyond.left + beyond.width).toBeLessThanOrEqual(100);
  });

  it("setzt Tagesmarken nur innerhalb des Fensters", () => {
    const ticks = ganttDayTicks("2026-11-16T10:00:00Z", "2026-11-23T10:00:00Z");
    expect(ticks.length).toBeGreaterThanOrEqual(6);
    expect(ticks.every((tick) => tick.left > 0 && tick.left < 100)).toBe(true);
  });
});
