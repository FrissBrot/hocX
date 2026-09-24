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

describe("PhotoAlbums", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
  });

  it("shows a pending cross-tenant share request and accepts it", async () => {
    mockListEndpoints([], [makeRequest()]);

    render(<PhotoAlbums />);

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

    render(<PhotoAlbums />);
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

    render(<PhotoAlbums />);

    await screen.findByText("Sommerlager");
    expect(screen.queryByText(/möchte das Album/)).toBeNull();
  });

  it("marks an album owned by another tenant as shared, without a 'teilen' action for it", async () => {
    mockListEndpoints([makeAlbum({ owner_tenant_name: "Nachbarverein" })], []);

    render(<PhotoAlbums />);
    fireEvent.click(await screen.findByText("Sommerlager"));

    expect(await screen.findByText(/Geteilt von Nachbarverein/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Mit anderem Mandanten teilen" })).toBeNull();
  });

  it("offers 'Mit anderem Mandanten teilen' only for the tenant's own manual albums", async () => {
    mockListEndpoints([makeAlbum()], []);

    render(<PhotoAlbums />);
    fireEvent.click(await screen.findByText("Sommerlager"));

    expect(await screen.findByRole("button", { name: "Mit anderem Mandanten teilen" })).toBeTruthy();
  });
});
