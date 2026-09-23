import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FileOverviewItem, SimilarityGroup } from "@/types/api";

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

import { PhotoSimilarGroups } from "./photo-similar-groups";

function makeItem(overrides: Partial<FileOverviewItem> = {}): FileOverviewItem {
  const id = overrides.id ?? `file-${Math.random().toString(36).slice(2)}`;
  return {
    id,
    original_name: "foto.jpg",
    mime_type: "image/jpeg",
    file_size_bytes: 1000,
    created_at: "2026-07-10T14:32:00Z",
    source: "gallery_upload",
    is_image: true,
    content_url: `/api/stored-files/${id}/content`,
    thumbnail_url: `/api/stored-files/${id}/thumbnail`,
    tags_url: `/api/stored-files/${id}/tags`,
    metadata_url: `/api/stored-files/${id}/metadata`,
    ref_label: "",
    ref_date: null,
    ref_end_date: null,
    ref_href: null,
    tags: [],
    origin_tag: "Direkt hochgeladen",
    sharpness_score: 65.0,
    exposure_score: 0.8,
    face_quality_score: null,
    face_analyzed_at: null,
    width: null,
    height: null,
    group_date: "2026-07-10",
    context_label: null,
    albums: [],
    is_best: null,
    ...overrides,
  };
}

function makeGroup(): SimilarityGroup {
  const best = makeItem({ id: "best", sharpness_score: 65.0 });
  const others = [makeItem({ id: "other-1", sharpness_score: 34.0 }), makeItem({ id: "other-2", sharpness_score: 30.0 })];
  return { best_id: best.id, images: [best, ...others] };
}

describe("PhotoSimilarGroups", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
    confirmMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("requests the looser series threshold, not the tight duplicate one", async () => {
    browserApiFetchMock.mockImplementation((url: string) =>
      Promise.resolve(url.startsWith("/api/files/similarity-groups") ? [] : null)
    );
    render(<PhotoSimilarGroups search="" tagFilter={[]} />);

    await waitFor(() =>
      expect(browserApiFetchMock).toHaveBeenCalledWith(expect.stringContaining("kind=series"))
    );
  });

  it("preselects only the best image to keep, and toggling it back off is a no-op", async () => {
    const group = makeGroup();
    browserApiFetchMock.mockImplementation((url: string) =>
      Promise.resolve(url.startsWith("/api/files/similarity-groups") ? [group] : null)
    );
    render(<PhotoSimilarGroups search="" tagFilter={[]} />);

    const bestCheckbox = await screen.findByRole("checkbox", { name: "foto.jpg nicht mehr behalten" });
    expect(bestCheckbox).toHaveAttribute("aria-checked", "true");
    const otherCheckboxes = screen.getAllByRole("checkbox", { name: "foto.jpg behalten" });
    expect(otherCheckboxes).toHaveLength(2);

    // The only kept image can't be unchecked - at least one must always remain kept.
    fireEvent.click(bestCheckbox);
    expect(bestCheckbox).toHaveAttribute("aria-checked", "true");
  });

  it("deletes only the images that stayed unchecked, keeping the checked ones", async () => {
    const group = makeGroup();
    browserApiFetchMock.mockImplementation((url: string, options?: { method?: string; body?: string }) => {
      if (url.startsWith("/api/files/similarity-groups")) return Promise.resolve([group]);
      if (url === "/api/files/bulk-delete" && options?.method === "POST") {
        return Promise.resolve({ deleted_ids: JSON.parse(options.body!).file_ids, errors: [] });
      }
      return Promise.resolve(null);
    });
    confirmMock.mockResolvedValue(true);
    render(<PhotoSimilarGroups search="" tagFilter={[]} />);

    // Additionally keep "other-1" - only "other-2" should end up deleted.
    const otherCheckboxes = await screen.findAllByRole("checkbox", { name: "foto.jpg behalten" });
    fireEvent.click(otherCheckboxes[0]);

    fireEvent.click(await screen.findByRole("button", { name: "Auswahl löschen" }));
    await waitFor(() => expect(confirmMock).toHaveBeenCalled());

    await waitFor(() =>
      expect(browserApiFetchMock).toHaveBeenCalledWith(
        "/api/files/bulk-delete",
        expect.objectContaining({ method: "POST", body: JSON.stringify({ file_ids: ["other-2"] }) })
      )
    );
  });

  it("keeps the group visible with the remaining images after a delete, instead of dismissing it", async () => {
    const group = makeGroup();
    browserApiFetchMock.mockImplementation((url: string, options?: { method?: string; body?: string }) => {
      if (url.startsWith("/api/files/similarity-groups")) return Promise.resolve([group]);
      if (url === "/api/files/bulk-delete" && options?.method === "POST") {
        return Promise.resolve({ deleted_ids: JSON.parse(options.body!).file_ids, errors: [] });
      }
      return Promise.resolve(null);
    });
    confirmMock.mockResolvedValue(true);
    render(<PhotoSimilarGroups search="" tagFilter={[]} />);

    expect(await screen.findByText("3 ähnliche Fotos")).toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: "Auswahl löschen" }));
    await waitFor(() => expect(confirmMock).toHaveBeenCalled());

    // Both non-best images were deleted (neither was checked) - the card itself must stay,
    // now showing only the one remaining (kept) image, not disappear.
    await waitFor(() => expect(screen.getByText("1 ähnliche Fotos")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Serie ausblenden" })).toBeInTheDocument();
  });

  it("reports the actually deleted ids to the gallery via onDeleted", async () => {
    const group = makeGroup();
    browserApiFetchMock.mockImplementation((url: string) => {
      if (url.startsWith("/api/files/similarity-groups")) return Promise.resolve([group]);
      if (url === "/api/files/bulk-delete") return Promise.resolve({ deleted_ids: ["other-1"], errors: ["other-2 fehlgeschlagen"] });
      return Promise.resolve(null);
    });
    confirmMock.mockResolvedValue(true);
    const onDeleted = vi.fn();
    render(<PhotoSimilarGroups search="" tagFilter={[]} onDeleted={onDeleted} />);

    fireEvent.click(await screen.findByRole("button", { name: "Auswahl löschen" }));

    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith(["other-1"]));
  });

  it("hiding the series just dismisses the card without any request", async () => {
    const group = makeGroup();
    browserApiFetchMock.mockImplementation((url: string) => {
      if (url.startsWith("/api/files/similarity-groups")) return Promise.resolve([group]);
      return Promise.resolve(null);
    });
    render(<PhotoSimilarGroups search="" tagFilter={[]} />);

    fireEvent.click(await screen.findByRole("button", { name: "Serie ausblenden" }));

    await waitFor(() => expect(screen.queryByRole("button", { name: "Serie ausblenden" })).not.toBeInTheDocument());
    expect(browserApiFetchMock.mock.calls.some(([url]) => url === "/api/files/bulk-delete")).toBe(false);
  });

  it("opens the clicked photo in the viewer", async () => {
    const group = makeGroup();
    group.images.forEach((image, index) => { image.original_name = `serie-${index}.jpg`; });
    browserApiFetchMock.mockImplementation((url: string) =>
      Promise.resolve(url.startsWith("/api/files/similarity-groups") ? [group] : null)
    );
    render(<PhotoSimilarGroups search="" tagFilter={[]} />);

    fireEvent.click(await screen.findByRole("button", { name: "serie-1.jpg öffnen" }));
    expect(screen.getByRole("dialog", { name: "serie-1.jpg" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    // Escape wartet auf den ausstehenden Speicherpfad (useDeferredPopupSave.flush), bevor geschlossen wird.
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
