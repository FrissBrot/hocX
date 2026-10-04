import { render } from "@testing-library/react";
import { expect, it } from "vitest";
import { HikingTourElevationPreview } from "./hiking-tour-elevation-preview";

it("positions points by distance and height", () => {
  const { container } = render(<HikingTourElevationPreview points={[[0, 500], [250, 1000], [1000, 500]]} />);
  expect(container.querySelector("polyline")?.getAttribute("points")).toBe("2.00,38.00 41.00,8.00 158.00,38.00");
});

it("handles flat profiles and missing data", () => {
  const { container, rerender } = render(<HikingTourElevationPreview points={[[0, 500], [1000, 500]]} />);
  expect(container.querySelector("polyline")?.getAttribute("points")).toBe("2.00,23.00 158.00,23.00");
  rerender(<HikingTourElevationPreview />);
  expect(container.querySelector("svg")).toBeNull();
});
