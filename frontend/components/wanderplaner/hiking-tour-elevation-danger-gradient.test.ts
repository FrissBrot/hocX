import { describe, expect, it } from "vitest";
import { buildDangerGradientStops } from "./hiking-tour-elevation-danger-gradient";
import { ElevationProfilePoint, TerrainDangerSegment } from "@/types/api";

function point(distance_m: number): ElevationProfilePoint {
  return { distance_m, elevation_m: 1000, lat: 47, lon: 8.5 };
}

describe("Höhenprofil-Gefahren-Gradient", () => {
  it("bleibt ohne Segmente bei einer durchgehend normalen Farbe", () => {
    const points = [point(0), point(100)];
    expect(buildDangerGradientStops(points)).toEqual([
      { offset: "0%", color: "var(--chart-1)" },
      { offset: "100%", color: "var(--chart-1)" },
    ]);
  });

  it("übersetzt Segmente in prozentuale Stops mit hartem Farbwechsel an der Grenze", () => {
    const points = [point(0), point(50), point(100)];
    const segments: TerrainDangerSegment[] = [
      { from_m: 0, to_m: 50, danger: "normal" },
      { from_m: 50, to_m: 100, danger: "alpine" },
    ];
    expect(buildDangerGradientStops(points, segments)).toEqual([
      { offset: "0.00%", color: "var(--chart-1)" },
      { offset: "50.00%", color: "var(--chart-1)" },
      { offset: "50.00%", color: "var(--info)" },
      { offset: "100.00%", color: "var(--info)" },
    ]);
  });

  it("markiert sehr steile/ausgesetzte Abschnitte orange", () => {
    const points = [point(0), point(100)];
    const segments: TerrainDangerSegment[] = [{ from_m: 20, to_m: 80, danger: "steep_exposed" }];
    const stops = buildDangerGradientStops(points, segments);
    expect(stops).toEqual([
      { offset: "20.00%", color: "var(--warning)" },
      { offset: "80.00%", color: "var(--warning)" },
    ]);
  });
});
