import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { HikingTour, HikingTourWaypoint } from "@/types/api";

const api = vi.hoisted(() => vi.fn());
const toast = vi.hoisted(() => vi.fn());
const params = vi.hoisted(() => ({ value: new URLSearchParams() }));
vi.mock("@/lib/api/client", () => ({ browserApiFetch: api }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), useSearchParams: () => params.value }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => async () => true }));
vi.mock("./hiking-tour-map", () => ({
  KIND_COLOR_TOKEN: {},
  HikingTourMap: ({ userPosition }: { userPosition?: { lat: number } | null }) => <output data-testid="map">{userPosition ? "user" : "map"}</output>,
}));
import { HikingTourMobile } from "./hiking-tour-mobile";

const point = (id: string, kind: HikingTourWaypoint["kind"], sequence: number, lon: number, extra: Partial<HikingTourWaypoint> = {}): HikingTourWaypoint => ({
  id, kind, sequence, lat: 47, lon, label: id, description: null, elevation_m: 500, break_minutes: null, break_reason: null,
  auto_generated: false, verification_status: null, decision_metrics_json: null, exit_metrics_json: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...extra,
});
const tour: HikingTour = {
  id: "tour", title: "Napf", description: null, tour_date: null, status: "analyzed",
  group_type: null, speed_factor_kmh: null, luggage_type: null, planned_start_time: "08:30:00",
  routing_profile: "wanderwege_bevorzugen",
  waypoints: [
    point("Fankhaus", "START", 0, 8.5),
    point("Brunnen", "WATER", 1, 8.5131, { auto_generated: true, verification_status: "NEEDS_VERIFICATION" }),
    point("Gipfel", "END", 2, 8.5393),
  ],
  route_legs: [{ sequence: 0, distance_m: 3000, ascent_m: 200, descent_m: 0, cost: 1, routing_profile: "wanderwege_bevorzugen",
    coordinates: [[47, 8.5], [47, 8.5393]], computed_at: "2026-01-01T00:00:00Z" }],
  route_distance_m: 3000, route_ascent_m: 200, route_descent_m: 50, route_cost: 1,
  route_computed_at: "2026-01-01T00:00:00Z", elevation_profile_fetched_at: "2026-01-01T00:00:00Z",
  terrain_danger_computed_at: "2026-01-01T00:00:00Z",
  reconnaissance_checklist: { trail_condition: true }, reconnaissance_remarks: null, reconnoitered_at: null, reconnoitered_by_name: null,
  approved_at: null, approved_by_name: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};
const profile = { fetched_at: "x", points: [0, 1, 2, 3].map((index) => ({ distance_m: index * 1000, elevation_m: 500 + index * 50, lat: 47, lon: 8.5 + index * 0.0131 })) };
const danger = { computed_at: "x", segments: [{ from_m: 1500, to_m: 1800, danger: "steep_exposed" }] };

beforeEach(() => {
  api.mockReset();
  toast.mockReset();
  params.value = new URLSearchParams();
  api.mockImplementation(async (url: string) => {
    if (url.endsWith("elevation-profile")) return profile;
    if (url.endsWith("terrain-danger")) return danger;
    return { speed_factor_kmh: 4, entries: [], summary: { total_distance_m: 3000, total_ascent_m: 200, total_descent_m: 50, total_lkm: 5, walking_duration_minutes: 75, break_duration_minutes: 20, total_duration_minutes: 95 } };
  });
});

it("shows the tour overview with stats and the view actions", async () => {
  render(<HikingTourMobile initialTour={tour} canWrite />);
  expect(screen.getByRole("heading", { name: "Napf" })).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText("1h 35min")).toBeInTheDocument());
  expect(screen.getByRole("button", { name: "Navigation starten" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "GPX" })).toHaveAttribute("href", "/api/hiking-tours/tour/gpx");
});

it("verifies an auto-detected point directly from the reconnaissance view", async () => {
  params.value = new URLSearchParams("view=reconnaissance");
  api.mockImplementation(async (url: string, init?: RequestInit) => {
    if (init?.method === "PATCH") return { ...tour.waypoints[1], verification_status: "VERIFIED" };
    return { points: [], segments: [], entries: [], summary: {} };
  });
  render(<HikingTourMobile initialTour={tour} canWrite />);
  expect(screen.getByText("1/7")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Brunnen bestätigen" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Brunnen bestätigen" })).toHaveAttribute("aria-pressed", "true"));
  const patch = api.mock.calls.find(([, init]) => init?.method === "PATCH");
  expect(patch?.[0]).toBe("/api/hiking-tours/tour/waypoints/Brunnen/verification");
  expect(JSON.parse(patch?.[1].body)).toEqual({ verification_status: "VERIFIED" });
});

it("navigates with the device position and warns before a danger zone", async () => {
  let report: PositionCallback = () => {};
  const clearWatch = vi.fn();
  Object.defineProperty(navigator, "geolocation", {
    configurable: true,
    value: { watchPosition: (success: PositionCallback) => { report = success; return 7; }, clearWatch },
  });
  params.value = new URLSearchParams("view=navigation");
  const { rerender } = render(<HikingTourMobile initialTour={tour} canWrite />);
  // Navigation läuft erst nach einem bewussten Start (Weiter), nicht schon beim Öffnen per Link.
  fireEvent.click(screen.getByRole("button", { name: "Weiter" }));
  await waitFor(() => expect(screen.getByText("GPS-Signal wird gesucht …")).toBeInTheDocument());
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/hiking-tours/tour/terrain-danger"));
  report({ coords: { latitude: 47, longitude: 8.5131, accuracy: 6, heading: null, altitude: null } } as GeolocationPosition);
  await waitFor(() => expect(screen.getByText("±6 m")).toBeInTheDocument());
  expect(screen.getByRole("alert")).toHaveTextContent("In 500 m: Steil/ausgesetzt");
  // Nächster Punkt (Brunnen ist erreicht) und Restweg: beide 2 km bis zum Gipfel.
  expect(screen.getByText("bis Gipfel")).toBeInTheDocument();
  expect(screen.getAllByText("2.0 km")).toHaveLength(2);
  expect(screen.getByTestId("map")).toHaveTextContent("user");
  fireEvent.click(screen.getByRole("button", { name: "Notausstieg" }));
  expect(screen.getByText(/keine Notausstiege erfasst/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Rega 1414" })).toHaveAttribute("href", "tel:1414");
  params.value = new URLSearchParams();
  rerender(<HikingTourMobile initialTour={tour} canWrite />);
  await waitFor(() => expect(clearWatch).toHaveBeenCalledWith(7));
});
