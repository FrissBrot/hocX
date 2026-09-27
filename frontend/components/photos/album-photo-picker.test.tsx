import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
const showToastMock = vi.fn();
const confirmMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiBaseUrl: "",
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

vi.mock("@/contexts/toast-context", () => ({
  useToast: () => showToastMock,
}));

vi.mock("@/contexts/confirm-context", () => ({
  useConfirm: () => confirmMock,
}));

import { AlbumPhotoPicker } from "./album-photo-picker";
import { FileOverviewItem, PhotoAlbum } from "@/types/api";

const album: PhotoAlbum = {
  id: "album-1",
  name: "Mitgliederfotos Vereinsheft",
  kind: "manual",
  photo_count: 1,
  best_of_count: 0,
  cover_thumbnail_urls: [],
  owner_tenant_name: null,
  shared_with: [],
  is_shared: false,
  pending_share_count: 0,
};

function makeItem(id: string, groupDate: string, inAlbum = false): FileOverviewItem {
  return {
    id,
    original_name: `${id}.jpg`,
    mime_type: "image/jpeg",
    file_size_bytes: 1000,
    created_at: `${groupDate}T10:00:00Z`,
    source: "gallery_upload",
    is_image: true,
    content_url: `/api/files/${id}/content`,
    thumbnail_url: `/api/files/${id}/thumbnail`,
    tags_url: "",
    metadata_url: "",
    ref_label: "",
    ref_date: null,
    ref_end_date: null,
    ref_href: null,
    tags: [],
    origin_tag: "Direkt hochgeladen",
    sharpness_score: null,
    exposure_score: null,
    face_quality_score: null,
    face_analyzed_at: null,
    width: 400,
    height: 300,
    group_date: groupDate,
    context_label: null,
    live_video_url: null,
    albums: inAlbum ? [{ id: album.id, name: album.name, kind: "manual", is_best: false }] : [],
    is_best: null,
  };
}

const items = [
  makeItem("a1", "2026-08-12"),
  makeItem("a2", "2026-08-12"),
  makeItem("b1", "2026-07-10", true),
];

describe("AlbumPhotoPicker", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
    confirmMock.mockReset();
    browserApiFetchMock.mockImplementation((path: string) => Promise.resolve(path.startsWith("/api/files?") ? items : undefined));
  });

  it("groups photos by date and marks photos already in the album", async () => {
    render(<AlbumPhotoPicker album={album} onClose={vi.fn()} onAdded={vi.fn()} />);

    expect(await screen.findByText("Album · Mitgliederfotos Vereinsheft")).toBeInTheDocument();
    expect(screen.getByText("2 Fotos")).toBeInTheDocument();
    expect(screen.getByText("Im Album")).toBeInTheDocument();
    const contained = screen.getByRole("checkbox", { name: "b1.jpg (bereits im Album)" });
    fireEvent.click(contained);
    expect(screen.getByText("Keine Fotos ausgewählt")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hinzufügen" })).toBeDisabled();
  });

  it("selects a whole date group and adds the selection in one request", async () => {
    const onAdded = vi.fn();
    const onClose = vi.fn();
    render(<AlbumPhotoPicker album={album} onClose={onClose} onAdded={onAdded} />);

    const groupToggles = await screen.findAllByRole("button", { name: "Alle auswählen" });
    fireEvent.click(groupToggles[0]);
    expect(screen.getByText("2 Fotos ausgewählt")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Auswahl aufheben" })).toBeInTheDocument();
    // Gruppe, deren Fotos alle schon im Album sind, hat nichts zu wählen.
    expect(groupToggles[1]).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Hinzufügen" }));

    await waitFor(() => expect(onAdded).toHaveBeenCalled());
    expect(browserApiFetchMock).toHaveBeenCalledWith("/api/files/albums/album-1/items", {
      method: "POST",
      body: JSON.stringify({ file_ids: ["a1", "a2"] }),
    });
    expect(showToastMock).toHaveBeenCalledWith("2 Fotos zum Album hinzugefügt.", "success");
    expect(onClose).toHaveBeenCalled();
  });

  it("does not ask for confirmation when the album is not shared", async () => {
    const onAdded = vi.fn();
    render(<AlbumPhotoPicker album={album} onClose={vi.fn()} onAdded={onAdded} />);

    fireEvent.click((await screen.findAllByRole("button", { name: "Alle auswählen" }))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Hinzufügen" }));

    await waitFor(() => expect(onAdded).toHaveBeenCalled());
    expect(confirmMock).not.toHaveBeenCalled();
  });

  it("warns before adding photos to a shared album and adds nothing when cancelled", async () => {
    confirmMock.mockResolvedValue(false);
    const onAdded = vi.fn();
    render(<AlbumPhotoPicker album={{ ...album, is_shared: true }} onClose={vi.fn()} onAdded={onAdded} />);

    fireEvent.click((await screen.findAllByRole("button", { name: "Alle auswählen" }))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Hinzufügen" }));

    await waitFor(() => expect(confirmMock).toHaveBeenCalled());
    expect(confirmMock.mock.calls[0][0]).toMatchObject({ title: "Fotos werden geteilt", confirmLabel: "Hinzufügen und teilen" });
    expect(confirmMock.mock.calls[0][0].message).toContain("2 Fotos werden damit sofort");
    expect(browserApiFetchMock).not.toHaveBeenCalledWith("/api/files/albums/album-1/items", expect.anything());
    expect(onAdded).not.toHaveBeenCalled();
  });

  it("passes source filter and exclude_album_id to the listing", async () => {
    render(<AlbumPhotoPicker album={album} onClose={vi.fn()} onAdded={vi.fn()} />);
    await screen.findAllByRole("button", { name: "Alle auswählen" });

    fireEvent.click(screen.getByRole("tab", { name: "Abgaben" }));
    fireEvent.click(screen.getByRole("switch", { name: "Bereits enthaltene ausblenden" }));

    await waitFor(() => {
      const lastUrl = browserApiFetchMock.mock.calls.at(-1)?.[0] as string;
      expect(lastUrl).toContain("source=submission_upload");
      expect(lastUrl).toContain("exclude_album_id=album-1");
    });
  });
});
