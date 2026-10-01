import { render } from "@testing-library/react";
import { StrictMode } from "react";
import { beforeEach, expect, it, vi } from "vitest";

const markers = vi.hoisted(() => [] as { position?: number[]; attached: boolean }[]);
vi.mock("maplibre-gl", () => ({
  default: {
    Map: class {
      addControl() {}
      on() {}
      once() {}
      isStyleLoaded() { return false; }
      remove() {}
    },
    NavigationControl: class {},
    Marker: class {
      position?: number[];
      attached = false;
      constructor() { markers.push(this); }
      setLngLat(position: number[]) { this.position = position; return this; }
      addTo() {
        // MapLibre projects the position immediately when attaching a marker.
        if (!this.position) throw new Error("Marker has no coordinates");
        this.attached = true;
        return this;
      }
      remove() { this.attached = false; return this; }
    },
  },
}));
import { HikingTourMap } from "./hiking-tour-map";

beforeEach(() => { markers.length = 0; });

it("positions, updates and removes the elevation hover marker", () => {
  const { rerender, unmount } = render(<HikingTourMap waypoints={[]} highlightPoint={{ lat: 47, lon: 8 }} />);
  expect(markers).toHaveLength(1);
  expect(markers[0]).toMatchObject({ position: [8, 47], attached: true });
  rerender(<HikingTourMap waypoints={[]} highlightPoint={{ lat: 46, lon: 9 }} />);
  expect(markers).toHaveLength(1);
  expect(markers[0].position).toEqual([9, 46]);
  rerender(<HikingTourMap waypoints={[]} highlightPoint={null} />);
  expect(markers[0].attached).toBe(false);
  rerender(<HikingTourMap waypoints={[]} highlightPoint={{ lat: 47, lon: 8 }} />);
  expect(markers[1].attached).toBe(true);
  unmount();
  expect(markers.every(marker => !marker.attached)).toBe(true);
});

it("reattaches the highlight after StrictMode recreates the map", () => {
  const { unmount } = render(<StrictMode><HikingTourMap waypoints={[]} highlightPoint={{ lat: 47, lon: 8 }} /></StrictMode>);
  expect(markers.filter(marker => marker.attached)).toHaveLength(1);
  expect(markers.at(-1)?.position).toEqual([8, 47]);
  unmount();
  expect(markers.every(marker => !marker.attached)).toBe(true);
});
