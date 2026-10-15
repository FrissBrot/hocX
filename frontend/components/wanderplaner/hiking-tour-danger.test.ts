import { describe, expect, it } from "vitest";
import { buildDangerLineFeatures } from "./hiking-tour-danger";
import { ElevationProfilePoint } from "@/types/api";

function point(distance_m: number, lon: number): ElevationProfilePoint {
  return { distance_m, elevation_m: 1000, lat: 47, lon };
}

describe("Gefahrensegmente auf der Karte", () => {
  const profile = [point(0, 8.0), point(100, 8.1), point(200, 8.2)];

  it("zeichnet auch kurze Segmente zwischen zwei Profilpunkten", () => {
    const [feature] = buildDangerLineFeatures(profile, [{ from_m: 20, to_m: 40, danger: "steep_exposed" }]);
    expect(feature.properties.danger).toBe("steep_exposed");
    expect(feature.geometry.coordinates[0][0]).toBeCloseTo(8.02);
    expect(feature.geometry.coordinates[1][0]).toBeCloseTo(8.04);
    expect(feature.geometry.coordinates).toHaveLength(2);
  });

  it("übernimmt Profilpunkte innerhalb eines Segments und schliesst lückenlos an", () => {
    const features = buildDangerLineFeatures(profile, [
      { from_m: 0, to_m: 150, danger: "normal" },
      { from_m: 150, to_m: 200, danger: "alpine" },
    ]);
    expect(features[0].geometry.coordinates.map(([lon]) => lon)).toEqual([8.0, 8.1, expect.closeTo(8.15)]);
    expect(features[1].geometry.coordinates[0][0]).toBeCloseTo(8.15);
    expect(features[1].geometry.coordinates.at(-1)).toEqual([8.2, 47]);
  });

  it("ignoriert leere Segmente und zu kurze Profile", () => {
    expect(buildDangerLineFeatures(profile, [{ from_m: 50, to_m: 50, danger: "alpine" }])).toEqual([]);
    expect(buildDangerLineFeatures([point(0, 8)], [{ from_m: 0, to_m: 10, danger: "alpine" }])).toEqual([]);
  });
});
