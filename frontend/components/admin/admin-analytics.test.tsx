import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

const replaceMock = vi.fn();
let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
  usePathname: () => "/admin/analytics",
  useSearchParams: () => new URLSearchParams(search),
}));

// recharts braucht Layout-Masse, die jsdom nicht hat - das Diagramm selbst ist hier nicht Gegenstand.
vi.mock("next/dynamic", () => ({ default: () => () => <div data-testid="analytics-chart" /> }));

import { AdminAnalytics } from "./admin-analytics";

const EMPTY = { series: "growth", range: "90d", bucket: "day", metrics: ["tenants.total"], collecting_since: null, points: [] };
const GROWTH = {
  series: "growth",
  range: "90d",
  bucket: "day",
  metrics: ["tenants.total", "tenants.new", "users.total"],
  collecting_since: "2026-11-01",
  points: [{ bucket: "2026-11-20", values: { "tenants.total": 42, "tenants.new": 1, "users.total": 318 } }],
};

describe("AdminAnalytics", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    replaceMock.mockReset();
    search = "";
  });

  it("zeigt den ehrlichen Leerzustand ohne Rollup-Daten", async () => {
    browserApiFetchMock.mockResolvedValue(EMPTY);
    render(<AdminAnalytics isOwner />);
    expect(await screen.findByText(/Noch keine Daten/)).toBeInTheDocument();
    expect(screen.getByText("Keine Werte im Zeitraum")).toBeInTheDocument();
    expect(browserApiFetchMock).toHaveBeenCalledWith("/api/admin/analytics/growth?range=90d", expect.anything());
  });

  it("zeigt Sammelbeginn, Werte als Tabelle und lädt neu beim Zeitraumwechsel", async () => {
    browserApiFetchMock.mockResolvedValue(GROWTH);
    render(<AdminAnalytics isOwner />);
    expect(await screen.findByText(/seit 01.11.2026 gesammelt/)).toBeInTheDocument();
    expect(screen.getByTestId("analytics-chart")).toBeInTheDocument();
    expect(screen.getByText("318")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "30 Tage" }));
    await waitFor(() => expect(browserApiFetchMock).toHaveBeenLastCalledWith("/api/admin/analytics/growth?range=30d", expect.anything()));
  });

  it("schreibt den Tab in die URL und blendet Owner-Tabs für Support aus", async () => {
    browserApiFetchMock.mockResolvedValue(EMPTY);
    const { unmount } = render(<AdminAnalytics isOwner />);
    fireEvent.click(await screen.findByRole("tab", { name: "Umsatz" }));
    expect(replaceMock).toHaveBeenCalledWith("/admin/analytics?tab=revenue", { scroll: false });
    expect(screen.getByRole("tab", { name: "Fehler" })).toBeInTheDocument();
    unmount();

    search = "tab=errors";
    render(<AdminAnalytics isOwner={false} />);
    expect(screen.queryByRole("tab", { name: "Fehler" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Nutzung" })).not.toBeInTheDocument();
    // Ein Owner-Tab in der URL fällt für Support auf «Wachstum» zurück.
    await waitFor(() => expect(browserApiFetchMock).toHaveBeenLastCalledWith("/api/admin/analytics/growth?range=90d", expect.anything()));
  });
});
