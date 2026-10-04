import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
const showToastMock = vi.fn();
const confirmMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

vi.mock("@/contexts/toast-context", () => ({
  useToast: () => showToastMock,
}));

vi.mock("@/contexts/confirm-context", () => ({
  useConfirm: () => confirmMock,
}));

import { SharedLinksView } from "./shared-links-view";
import { ShareLink } from "@/types/api";

function makeLink(overrides: Partial<ShareLink> = {}): ShareLink {
  return {
    id: "link-1",
    name: "Sommerlager-Fotos",
    url: "/share/tok-1",
    album_name: "Sommerlager",
    file_count: 12,
    created_at: "2026-09-20T08:00:00Z",
    created_by_name: "Leiter Anna",
    expires_at: null,
    revoked_at: null,
    status: "active",
    share_location: false,
    share_capture_date: true,
    share_camera: false,
    ...overrides,
  };
}

/** The component re-fetches its own list on mount (GET /api/share-links) - mocking it to
 * echo back the same `links` the test passes as initialLinks keeps that refetch from
 * silently overwriting what the test set up. */
function mockListRefetch(links: ShareLink[]) {
  browserApiFetchMock.mockImplementation((path: string) => (path === "/api/share-links" ? Promise.resolve(links) : Promise.resolve(undefined)));
}

describe("SharedLinksView", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
    confirmMock.mockReset();
  });

  it("shows an empty state when there are no links at all", () => {
    mockListRefetch([]);
    render(<SharedLinksView initialLinks={[]} />);

    expect(screen.getByText("Noch keine Links vorhanden")).toBeTruthy();
  });

  it("renders each link's scope, creator and status", () => {
    const links = [
      makeLink(),
      makeLink({ id: "link-2", name: "Dateien-Auswahl", album_name: null, file_count: 3, status: "revoked", created_by_name: "Leiter Bruno" }),
    ];
    mockListRefetch(links);
    render(<SharedLinksView initialLinks={links} />);
    fireEvent.click(screen.getByRole("tab", { name: /Alle/ })); // the revoked link-2 isn't in the default "Aktiv" filter

    const activeRow = screen.getByText("Sommerlager-Fotos").closest("tr")!;
    const revokedRow = screen.getByText("Dateien-Auswahl").closest("tr")!;
    expect(within(activeRow).getByText('Album „Sommerlager“')).toBeTruthy();
    expect(within(activeRow).getByText("Leiter Anna")).toBeTruthy();
    expect(within(activeRow).getByText("Aktiv")).toBeTruthy();
    expect(within(revokedRow).getByText("3 Dateien")).toBeTruthy();
    expect(within(revokedRow).getByText("Leiter Bruno")).toBeTruthy();
    expect(within(revokedRow).getByText("Widerrufen")).toBeTruthy();
  });

  it("filters to active-only by default and shows everything on 'Alle'", () => {
    const links = [makeLink(), makeLink({ id: "link-2", name: "Alter Link", status: "revoked" })];
    mockListRefetch(links);
    render(<SharedLinksView initialLinks={links} />);

    expect(screen.queryByText("Alter Link")).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: /Alle/ }));

    expect(screen.getByText("Alter Link")).toBeTruthy();
  });

  it("revokes a link after confirmation, dropping it out of the default 'Aktiv' filter", async () => {
    confirmMock.mockResolvedValue(true);
    mockListRefetch([makeLink()]);

    render(<SharedLinksView initialLinks={[makeLink()]} />);
    fireEvent.click(screen.getByRole("button", { name: /Aktionen für/ }));
    fireEvent.click(screen.getByText("Widerrufen"));

    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalledWith("/api/share-links/link-1", { method: "DELETE" }));
    expect(showToastMock).toHaveBeenCalledWith("Link widerrufen.", "success");
    await waitFor(() => expect(screen.queryByText("Sommerlager-Fotos")).toBeNull());

    fireEvent.click(screen.getByRole("tab", { name: /Alle/ }));
    expect(screen.getByText("Sommerlager-Fotos")).toBeTruthy();
    expect(screen.getByText("Widerrufen")).toBeTruthy();
  });

  it("does not offer 'Widerrufen' for an already revoked link", () => {
    // "Widerrufen" is also the status badge's own label for a revoked link, so this checks
    // the ActionMenu's menu items specifically, not just any text with that word on the page.
    const links = [makeLink({ status: "revoked" })];
    mockListRefetch(links);
    render(<SharedLinksView initialLinks={links} />);

    fireEvent.click(screen.getByRole("tab", { name: /Alle/ }));
    fireEvent.click(screen.getByRole("button", { name: /Aktionen für/ }));

    expect(screen.queryByRole("menuitem", { name: "Widerrufen" })).toBeNull();
  });
});
