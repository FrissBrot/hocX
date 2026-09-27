import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
const showToastMock = vi.fn();
const routerPushMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

vi.mock("@/contexts/toast-context", () => ({
  useToast: () => showToastMock,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPushMock }),
}));

import { HikingTourManager } from "./hiking-tour-manager";
import { HikingTour, HikingTourSummary } from "@/types/api";

const summary = (overrides: Partial<HikingTourSummary> = {}): HikingTourSummary => ({
  id: "tour-1",
  title: "Rigi Kulm ab Goldau",
  tour_date: "2026-06-01",
  status: "draft",
  created_at: "2026-01-01T10:00:00Z",
  updated_at: "2026-01-01T10:00:00Z",
  ...overrides,
});

describe("HikingTourManager", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
    routerPushMock.mockReset();
  });

  it("lists existing tours with title, date and status", () => {
    render(<HikingTourManager initialTours={[summary()]} canWrite={false} />);

    expect(screen.getByText("Rigi Kulm ab Goldau")).toBeTruthy();
    expect(screen.getByText("Entwurf")).toBeTruthy();
  });

  it("hides the create button for read-only users", () => {
    render(<HikingTourManager initialTours={[]} canWrite={false} />);

    expect(screen.queryByRole("button", { name: "Neue Wanderung" })).toBeNull();
  });

  it("creates a tour with start/end coordinates and navigates to its detail page", async () => {
    const created: HikingTour = {
      id: "tour-2",
      title: "Pilatus Höhenweg",
      description: null,
      tour_date: null,
      status: "draft",
      group_type: null,
      speed_factor_kmh: null,
      luggage_type: null,
      planned_start_time: null,
      routing_profile: null,
      waypoints: [],
      created_at: "2026-01-01T10:00:00Z",
      updated_at: "2026-01-01T10:00:00Z",
    };
    browserApiFetchMock.mockResolvedValue(created);

    render(<HikingTourManager initialTours={[]} canWrite />);
    fireEvent.click(screen.getByRole("button", { name: "Neue Wanderung" }));
    fireEvent.change(screen.getByLabelText("Titel"), { target: { value: "Pilatus Höhenweg" } });
    fireEvent.change(screen.getByLabelText("Start – Breite (Lat)"), { target: { value: "47.05" } });
    fireEvent.change(screen.getByLabelText("Start – Länge (Lon)"), { target: { value: "8.48" } });
    fireEvent.change(screen.getByLabelText("Ziel – Breite (Lat)"), { target: { value: "46.98" } });
    fireEvent.change(screen.getByLabelText("Ziel – Länge (Lon)"), { target: { value: "8.25" } });
    fireEvent.click(screen.getByRole("button", { name: "Wanderung erstellen" }));

    await waitFor(() => expect(routerPushMock).toHaveBeenCalledWith("/wanderplaner/tour-2"));
    const [url, init] = browserApiFetchMock.mock.calls[0];
    expect(url).toBe("/api/hiking-tours");
    const body = JSON.parse(init.body);
    expect(body.title).toBe("Pilatus Höhenweg");
    expect(body.start).toEqual({ lat: 47.05, lon: 8.48 });
    expect(body.end).toEqual({ lat: 46.98, lon: 8.25 });
  });
});
