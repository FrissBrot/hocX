import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

// Die Listen-Seite reicht alle Termine als Auswahl für Terminspalten an die Listen weiter. GET
// /api/events liefert pro Seite höchstens 100 (Standard) bzw. 500 Termine, neueste zuerst - ältere
// Termine fehlten sonst in der Auswahl und Einträge, die auf sie verweisen, zeigten keinen Termin.
const { fetchMock, fetchAllMock, managerMock } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  fetchAllMock: vi.fn(),
  managerMock: vi.fn((_props: { availableEvents: unknown[] }) => null),
}));
vi.mock("@/lib/api/server", () => ({
  backendFetchWithSession: fetchMock,
  backendFetchAllPagesWithSession: fetchAllMock,
  requireSession: async () => ({ permissions: ["meetings.edit"], roles: [], current_tenant: { id: "t", enabled_features: [] } }),
}));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));
vi.mock("@/components/ui/app-shell", () => ({ AppShell: ({ children }: { children: React.ReactNode }) => children }));
vi.mock("@/components/mobile/responsive-view", () => ({ ResponsiveView: ({ desktop }: { desktop: React.ReactNode }) => desktop }));
vi.mock("@/components/mobile/areas/mobile-lists", () => ({ MobileLists: () => null }));
vi.mock("@/components/lists/list-manager", () => ({ ListManager: managerMock }));

import ListsPage from "./page";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const events = (count: number) => Array.from({ length: count }, (_, index) => ({ id: `e${index}`, title: `Termin ${index}` }));

it("übergibt alle Termine, nicht nur die erste Seite", async () => {
  fetchMock.mockImplementation(async (path: string) => (path.startsWith("/api/events") ? events(100) : []));
  fetchAllMock.mockImplementation(async (path: string) => (path.startsWith("/api/events") ? events(250) : []));

  render(await ListsPage());

  expect(managerMock).toHaveBeenCalled();
  expect(managerMock.mock.calls[0][0].availableEvents).toHaveLength(250);
});
