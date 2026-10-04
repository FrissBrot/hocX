import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { HikingTour, HikingTourWaypoint } from "@/types/api";

const api = vi.hoisted(() => vi.fn());
const toast = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ browserApiFetch: api }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => async () => true }));
vi.mock("./hiking-tour-elevation-chart", () => ({ HikingTourElevationChart: () => <div /> }));
vi.mock("./hiking-tour-march-table", () => ({ HikingTourMarchTable: () => <div /> }));
vi.mock("./hiking-tour-map", () => ({
  HikingTourMap: ({ waypoints, onMarkerDragEnd, onMapClick }: {
    waypoints: HikingTourWaypoint[]; onMarkerDragEnd?: (id: string, lat: number, lon: number) => void;
    onMapClick?: (lat: number, lon: number) => void;
  }) => <div>
    <output data-testid="position">{waypoints[0]?.lat}</output>
    <output data-testid="count">{waypoints.length}</output>
    <button type="button" onClick={() => onMarkerDragEnd?.("start", 47.01, 8.5)}>Punkt verschieben</button>
    <button type="button" onClick={() => onMapClick?.(47, 8.51)}>Via platzieren</button>
  </div>,
}));
import { HikingTourDetail } from "./hiking-tour-detail";

const point = (id: string, kind: "START" | "END", sequence: number): HikingTourWaypoint => ({
  id, kind, sequence, lat: 47, lon: kind === "START" ? 8.5 : 8.52, label: id, description: null,
  elevation_m: 500, break_minutes: null, break_reason: null, auto_generated: false,
  verification_status: null, decision_metrics_json: null, exit_metrics_json: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
});
const initial: HikingTour = {
  id: "tour", title: "Tour", description: null, tour_date: null, status: "analyzed",
  group_type: null, speed_factor_kmh: null, luggage_type: null, planned_start_time: null,
  routing_profile: "wanderwege_bevorzugen", waypoints: [point("start", "START", 0), point("end", "END", 1)],
  route_legs: [{ sequence: 0, distance_m: 1000, ascent_m: 100, descent_m: 0, cost: 1000,
    routing_profile: "wanderwege_bevorzugen", coordinates: [[47, 8.5], [47, 8.52]], computed_at: "2026-01-01T00:00:00Z" }],
  route_distance_m: 1000, route_ascent_m: 100, route_descent_m: 0, route_cost: 1000,
  route_computed_at: "2026-01-01T00:00:00Z", elevation_profile_fetched_at: "2026-01-01T00:00:00Z",
  reconnaissance_checklist: {}, reconnaissance_remarks: null, reconnoitered_at: null, reconnoitered_by_name: null,
  approved_at: null, approved_by_name: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};
beforeEach(() => {
  api.mockReset(); toast.mockReset();
  api.mockImplementation(async (url: string) => url.endsWith("elevation-profile") ? { points: [] } : { entries: [] });
});

it("keeps a moved point local until saving and sends one complete planning request", async () => {
  render(<HikingTourDetail initialTour={initial} canWrite />);
  expect(screen.queryByRole("button", { name: "Speichern" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Route berechnen" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Höhenprofil abrufen" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Automatisch analysieren" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Punkt verschieben" }));
  expect(screen.getByTestId("position").textContent).toBe("47.01");
  expect(api.mock.calls.filter(([, init]) => init?.method)).toHaveLength(0);
  const saved = { ...initial, waypoints: [{ ...initial.waypoints[0], lat: 47.01 }, initial.waypoints[1]] };
  api.mockImplementation(async (url: string) => url.endsWith("/plan") ? saved : { points: [], entries: [] });
  fireEvent.click(screen.getByRole("button", { name: "Speichern" }));
  await waitFor(() => expect(toast).toHaveBeenCalledWith("Wanderung gespeichert und neu berechnet", "success"));
  const mutations = api.mock.calls.filter(([, init]) => init?.method);
  expect(mutations).toHaveLength(1);
  expect(mutations[0][0]).toBe("/api/hiking-tours/tour/plan");
  expect(JSON.parse(mutations[0][1].body).updates).toEqual([{ id: "start", lat: 47.01, lon: 8.5 }]);
  expect(screen.queryByRole("button", { name: "Speichern" })).toBeNull();
});

it("discards local additions and profile changes without writing to the server", () => {
  render(<HikingTourDetail initialTour={initial} canWrite />);
  fireEvent.change(screen.getByLabelText("Routingprofil"), { target: { value: "schnellste_route" } });
  fireEvent.click(screen.getByRole("button", { name: "Via-Punkt hinzufügen" }));
  fireEvent.click(screen.getByRole("button", { name: "Via platzieren" }));
  expect(screen.getByTestId("count").textContent).toBe("3");
  fireEvent.click(screen.getByRole("button", { name: "Änderungen verwerfen" }));
  expect(screen.getByTestId("count").textContent).toBe("2");
  expect(screen.getByLabelText("Routingprofil")).toHaveValue("wanderwege_bevorzugen");
  expect(api.mock.calls.filter(([, init]) => init?.method)).toHaveLength(0);
});

it("retains unsaved positions after a failed save so it can be retried", async () => {
  render(<HikingTourDetail initialTour={initial} canWrite />);
  fireEvent.click(screen.getByRole("button", { name: "Punkt verschieben" }));
  api.mockImplementation(async (url: string) => { if (url.endsWith("/plan")) throw new Error("Abruf fehlgeschlagen"); return { points: [], entries: [] }; });
  fireEvent.click(screen.getByRole("button", { name: "Speichern" }));
  await waitFor(() => expect(toast).toHaveBeenCalledWith("Abruf fehlgeschlagen", "error"));
  expect(screen.getByTestId("position").textContent).toBe("47.01");
  expect(screen.getByRole("button", { name: "Speichern" })).toBeEnabled();
});
