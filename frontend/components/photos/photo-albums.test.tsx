import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
const showToastMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

vi.mock("@/contexts/toast-context", () => ({
  useToast: () => showToastMock,
}));

const confirmMock = vi.fn();
vi.mock("@/contexts/confirm-context", () => ({
  useConfirm: () => confirmMock,
}));

vi.mock("./photos-view", () => ({
  PhotosView: () => <div data-testid="photos-view" />,
}));

import { PhotoAlbums } from "./photo-albums";
import { AlbumShareRequest, PhotoAlbum } from "@/types/api";

function makeAlbum(overrides: Partial<PhotoAlbum> = {}): PhotoAlbum {
  return {
    id: "album-1",
    name: "Sommerlager",
    kind: "manual",
    photo_count: 4,
    best_of_count: 1,
    cover_thumbnail_urls: [],
    owner_tenant_name: null,
    shared_with: [],
    my_share: null,
    is_shared: false,
    pending_share_count: 0,
    ...overrides,
  };
}

function makeRequest(overrides: Partial<AlbumShareRequest> = {}): AlbumShareRequest {
  return {
    album_id: "album-2",
    album_name: "Winterlager",
    owner_tenant_name: "Nachbarverein",
    created_at: "2026-09-20T08:00:00Z",
    ...overrides,
  };
}

function mockListEndpoints(albums: PhotoAlbum[], requests: AlbumShareRequest[]) {
  browserApiFetchMock.mockImplementation((path: string) => {
    if (path === "/api/files/albums") return Promise.resolve(albums);
    if (path === "/api/files/album-share-requests") return Promise.resolve(requests);
    return Promise.resolve(undefined);
  });
}

// Konto mit photos.manage, sharing.public und Abo «Fotos teilen» (wie die Standardrolle Schreiber)
const MANAGER = { viewerPermissions: { canManage: true, canShare: true }, canShareWithTenants: true };

describe("PhotoAlbums", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
  });

  it("shows a pending cross-tenant share request and accepts it", async () => {
    mockListEndpoints([], [makeRequest()]);

    render(<PhotoAlbums {...MANAGER} />);

    expect(await screen.findByText(/möchte das Album/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Annehmen" }));

    await waitFor(() =>
      expect(browserApiFetchMock).toHaveBeenCalledWith("/api/files/albums/album-2/respond", {
        method: "POST",
        body: JSON.stringify({ accept: true }),
      })
    );
    expect(showToastMock).toHaveBeenCalledWith("Album-Freigabe angenommen.", "success");
  });

  it("declines a pending request", async () => {
    mockListEndpoints([], [makeRequest()]);

    render(<PhotoAlbums {...MANAGER} />);
    await screen.findByText(/möchte das Album/);

    fireEvent.click(screen.getByRole("button", { name: "Ablehnen" }));

    await waitFor(() =>
      expect(browserApiFetchMock).toHaveBeenCalledWith("/api/files/albums/album-2/respond", {
        method: "POST",
        body: JSON.stringify({ accept: false }),
      })
    );
    expect(showToastMock).toHaveBeenCalledWith("Anfrage abgelehnt.", "success");
  });

  it("shows no pending-requests section when there are none", async () => {
    mockListEndpoints([makeAlbum()], []);

    render(<PhotoAlbums {...MANAGER} />);

    await screen.findByText("Sommerlager");
    expect(screen.queryByText(/möchte das Album/)).toBeNull();
  });

  it("marks an album owned by another tenant as shared, without a 'teilen' action for it", async () => {
    mockListEndpoints([makeAlbum({ owner_tenant_name: "Nachbarverein" })], []);

    render(<PhotoAlbums {...MANAGER} />);
    fireEvent.click(await screen.findByText("Sommerlager"));

    expect(await screen.findByText(/Geteilt von Nachbarverein/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Mit anderer Organisation teilen" })).toBeNull();
  });

  it("offers 'Mit anderer Organisation teilen' for the tenant's own albums", async () => {
    mockListEndpoints([makeAlbum()], []);

    render(<PhotoAlbums {...MANAGER} />);
    fireEvent.click(await screen.findByText("Sommerlager"));

    expect(await screen.findByRole("button", { name: "Mit anderer Organisation teilen" })).toBeTruthy();
  });

  it("also offers sharing for an own automatically-managed album (e.g. a Zyklus-Album)", async () => {
    mockListEndpoints([makeAlbum({ kind: "cycle", name: "Biber 2026" })], []);

    render(<PhotoAlbums {...MANAGER} />);
    fireEvent.click(await screen.findByText("Biber 2026"));

    expect(await screen.findByRole("button", { name: "Mit anderer Organisation teilen" })).toBeTruthy();
  });

  it("renames an own album via the ⋮ menu", async () => {
    mockListEndpoints([makeAlbum()], []);
    render(<PhotoAlbums {...MANAGER} />);
    fireEvent.click(await screen.findByText("Sommerlager"));

    fireEvent.click(await screen.findByRole("button", { name: "Album verwalten" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Umbenennen" }));
    const input = screen.getByDisplayValue("Sommerlager");
    fireEvent.change(input, { target: { value: "Sommerlager 2026" } });
    browserApiFetchMock.mockImplementation((path: string, init?: { method?: string }) =>
      Promise.resolve(path === "/api/files/albums/album-1" && init?.method === "PATCH" ? makeAlbum({ name: "Sommerlager 2026" }) : [])
    );
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() =>
      expect(browserApiFetchMock).toHaveBeenCalledWith("/api/files/albums/album-1", {
        method: "PATCH",
        body: JSON.stringify({ name: "Sommerlager 2026" }),
      })
    );
    expect(await screen.findByRole("heading", { name: "Sommerlager 2026" })).toBeTruthy();
  });

  it("deletes a manual album only after a danger confirmation", async () => {
    mockListEndpoints([makeAlbum()], []);
    confirmMock.mockResolvedValue(true);
    render(<PhotoAlbums {...MANAGER} />);
    fireEvent.click(await screen.findByText("Sommerlager"));

    fireEvent.click(await screen.findByRole("button", { name: "Album verwalten" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Album löschen" }));

    await waitFor(() => expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({ tone: "danger" })));
    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalledWith("/api/files/albums/album-1", { method: "DELETE" }));
  });

  it("offers no delete for automatic albums and no management menu for partners", async () => {
    mockListEndpoints([makeAlbum({ kind: "cycle", name: "Biber 2026" }), makeAlbum({ id: "album-2", name: "Fremd", owner_tenant_name: "Nachbarverein" })], []);
    const { unmount } = render(<PhotoAlbums {...MANAGER} />);
    fireEvent.click(await screen.findByText("Biber 2026"));
    fireEvent.click(await screen.findByRole("button", { name: "Album verwalten" }));
    expect(screen.getByRole("menuitem", { name: "Umbenennen" })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: "Album löschen" })).toBeNull();
    unmount();

    render(<PhotoAlbums {...MANAGER} />);
    fireEvent.click(await screen.findByText("Fremd"));
    await screen.findByText(/Geteilt von Nachbarverein/);
    expect(screen.queryByRole("button", { name: "Album verwalten" })).toBeNull();
  });

  it("offers no album actions to accounts that may only view photos (Nachtlauf 2026-11-22)", async () => {
    // photos.read ohne photos.manage/sharing.public/Abo: jede dieser Aktionen lehnte das Backend mit 403 ab
    mockListEndpoints([makeAlbum({ is_shared: true, pending_share_count: 2 })], [makeRequest()]);
    render(<PhotoAlbums />);
    await screen.findByText("Winterlager", { exact: false });
    expect(screen.queryByRole("button", { name: "Annehmen" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ablehnen" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Album erstellen/ })).not.toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: /Sommerlager/ }));
    await screen.findByRole("heading", { name: "Sommerlager" });
    expect(screen.queryByRole("button", { name: /Fotos hinzufügen/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Link/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Organisation teilen/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /freigeben/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Album verwalten/ })).not.toBeInTheDocument();
  });
});
