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

import { PhotoSimilarSeries } from "./photo-similar-series";

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
    ref_href: null,
    tags: [],
    origin_tag: "Direkt hochgeladen",
    sharpness_score: 65.0,
    exposure_score: 0.8,
    face_quality_score: null,
    face_analyzed_at: null,
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

describe("PhotoSimilarSeries", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
    confirmMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a confirmation naming the number of photos that will be deleted", async () => {
    const group = makeGroup();
    browserApiFetchMock.mockImplementation((url: string) => {
      if (url.startsWith("/api/files/similarity-groups")) return Promise.resolve([group]);
      return Promise.resolve(null);
    });
    confirmMock.mockResolvedValue(false);
    render(<PhotoSimilarSeries search="" tagFilter={[]} />);

    fireEvent.click(await screen.findByRole("button", { name: "Nur beste behalten" }));

    await waitFor(() => expect(confirmMock).toHaveBeenCalled());
    const [options] = confirmMock.mock.calls[0];
    expect(options.message).toContain("2 Bilder werden endgültig gelöscht");
  });

  it("issues no delete request when the confirmation is cancelled", async () => {
    const group = makeGroup();
    browserApiFetchMock.mockImplementation((url: string) => {
      if (url.startsWith("/api/files/similarity-groups")) return Promise.resolve([group]);
      return Promise.resolve(null);
    });
    confirmMock.mockResolvedValue(false);
    render(<PhotoSimilarSeries search="" tagFilter={[]} />);

    fireEvent.click(await screen.findByRole("button", { name: "Nur beste behalten" }));
    await waitFor(() => expect(confirmMock).toHaveBeenCalled());

    expect(browserApiFetchMock.mock.calls.some(([url]) => url === "/api/files/bulk-delete")).toBe(false);
  });

  it("deletes exactly the non-best images once confirmed", async () => {
    const group = makeGroup();
    browserApiFetchMock.mockImplementation((url: string, options?: { method?: string; body?: string }) => {
      if (url.startsWith("/api/files/similarity-groups")) return Promise.resolve([group]);
      if (url === "/api/files/bulk-delete" && options?.method === "POST") {
        return Promise.resolve({ deleted_ids: JSON.parse(options.body!).file_ids, errors: [] });
      }
      return Promise.resolve(null);
    });
    confirmMock.mockResolvedValue(true);
    render(<PhotoSimilarSeries search="" tagFilter={[]} />);

    fireEvent.click(await screen.findByRole("button", { name: "Nur beste behalten" }));

    await waitFor(() =>
      expect(browserApiFetchMock).toHaveBeenCalledWith(
        "/api/files/bulk-delete",
        expect.objectContaining({ method: "POST", body: JSON.stringify({ file_ids: ["other-1", "other-2"] }) })
      )
    );
  });

  it("keeping the series just dismisses the card without any request", async () => {
    const group = makeGroup();
    browserApiFetchMock.mockImplementation((url: string) => {
      if (url.startsWith("/api/files/similarity-groups")) return Promise.resolve([group]);
      return Promise.resolve(null);
    });
    render(<PhotoSimilarSeries search="" tagFilter={[]} />);

    fireEvent.click(await screen.findByRole("button", { name: "Serie behalten" }));

    await waitFor(() => expect(screen.queryByRole("button", { name: "Serie behalten" })).not.toBeInTheDocument());
    expect(browserApiFetchMock.mock.calls.some(([url]) => url === "/api/files/bulk-delete")).toBe(false);
  });
});
