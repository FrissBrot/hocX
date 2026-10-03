import { describe, expect, it } from "vitest";
import { layoutElevationLabels } from "./hiking-tour-elevation-labels";

describe("Höhenprofil-Beschriftungen", () => {
  it("verteilt überlappende Namen auf verschiedene Höhen", () => {
    const result = layoutElevationLabels([{ x: 100, width: 100 }, { x: 120, width: 100 }, { x: 140, width: 100 }], 390);
    expect(result.map((label) => label.lane)).toEqual([0, 1, 2]);
  });
  it("verwendet freie Höhen erneut und hält Texte innerhalb der Ränder", () => {
    const result = layoutElevationLabels([{ x: 0, width: 80 }, { x: 390, width: 100 }], 390);
    expect(result).toEqual([{ x: 44, lane: 0 }, { x: 336, lane: 0 }]);
  });
  it("hält Namen bei unterschiedlichen Kurvenhöhen direkt am Punkt", () => {
    const result = layoutElevationLabels([{ x: 100, width: 100, y: 150 }, { x: 120, width: 100, y: 100 }], 390);
    expect(result.map((label) => label.lane)).toEqual([0, 0]);
  });
  it("berücksichtigt bei schmaler Darstellung erneut die Kollisionen", () => {
    const labels = [{ x: 0, width: 100 }, { x: 1000, width: 100 }];
    expect(layoutElevationLabels(labels, 1440)[1].lane).toBe(0);
    expect(layoutElevationLabels(labels, 180)[1].lane).toBe(1);
  });
});
