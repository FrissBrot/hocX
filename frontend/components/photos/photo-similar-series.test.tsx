import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import type { FileOverviewItem, SimilarityGroup, SimilarityGroupList } from "@/types/api";

const browserApiFetchMock = vi.fn();
const showToastMock = vi.fn();
const confirmMock = vi.fn();

vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return {
    ApiError: actual.ApiError,
    browserApiBaseUrl: "",
    browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
  };
});

vi.mock("@/contexts/toast-context", () => ({
  useToast: () => showToastMock,
}));

vi.mock("@/contexts/confirm-context", () => ({
  useConfirm: () => confirmMock,
}));

import { PhotoSimilarSeries } from "./photo-similar-series";
import { clearSimilarityGroupsCache, SIMILARITY_PENDING_POLL_MS } from "./use-similarity-groups";

function ready(groups: SimilarityGroup[]): SimilarityGroupList {
  return { status: "ready", computed_at: "2026-10-24T09:00:00Z", groups };
}

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

describe("PhotoSimilarSeries", () => {
  beforeEach(() => {
    clearSimilarityGroupsCache();
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
    confirmMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("opens the clicked photo and navigates only within its series with arrow keys", async () => {
    const group = makeGroup();
    group.images.forEach((image, index) => { image.original_name = `serie-${index}.jpg`; });
    const otherGroup = { best_id: "separate", images: [makeItem({ id: "separate" }), makeItem({ id: "separate-other" })] };
    browserApiFetchMock.mockImplementation((url: string) =>
      Promise.resolve(url.startsWith("/api/files/similarity-groups") ? ready([group, otherGroup]) : null)
    );
    render(<PhotoSimilarSeries search="" tagFilter={[]} />);

    fireEvent.click(await screen.findByRole("button", { name: "serie-1.jpg öffnen" }));
    expect(screen.getByRole("dialog", { name: "serie-1.jpg" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "ArrowRight" });
    const lastPhoto = screen.getByRole("dialog", { name: "serie-2.jpg" });
    expect(within(lastPhoto).queryByRole("button", { name: "Nächstes Foto" })).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByRole("dialog", { name: "serie-2.jpg" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    const firstPhoto = screen.getByRole("dialog", { name: "serie-0.jpg" });
    expect(within(firstPhoto).queryByRole("button", { name: "Vorheriges Foto" })).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    // Escape wartet auf den ausstehenden Speicherpfad (useDeferredPopupSave.flush), bevor geschlossen wird.
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("shows a confirmation naming the number of photos that will be deleted", async () => {
    const group = makeGroup();
    browserApiFetchMock.mockImplementation((url: string) => {
      if (url.startsWith("/api/files/similarity-groups")) return Promise.resolve(ready([group]));
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
      if (url.startsWith("/api/files/similarity-groups")) return Promise.resolve(ready([group]));
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
      if (url.startsWith("/api/files/similarity-groups")) return Promise.resolve(ready([group]));
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

  it("reports the actually deleted ids to the gallery via onDeleted", async () => {
    const group = makeGroup();
    browserApiFetchMock.mockImplementation((url: string) => {
      if (url.startsWith("/api/files/similarity-groups")) return Promise.resolve(ready([group]));
      if (url === "/api/files/bulk-delete") return Promise.resolve({ deleted_ids: ["other-1"], errors: ["other-2 fehlgeschlagen"] });
      return Promise.resolve(null);
    });
    confirmMock.mockResolvedValue(true);
    const onDeleted = vi.fn();
    render(<PhotoSimilarSeries search="" tagFilter={[]} onDeleted={onDeleted} />);

    fireEvent.click(await screen.findByRole("button", { name: "Nur beste behalten" }));

    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith(["other-1"]));
  });

  it("ignores a stale similarity-groups response that resolves after a newer one (audit fix, 2026-09-17)", async () => {
    // Regression test: unlike its sibling fetch effects elsewhere in the app, this one had
    // no requestId/cancelled guard, so a slow response to an earlier search term could
    // overwrite the result of a later, faster one - and the destructive "Nur beste
    // behalten" button acts on whatever is currently rendered.
    const staleBest = makeItem({ id: "stale-best", context_label: "STALE-LABEL" });
    const staleGroup: SimilarityGroup = { best_id: staleBest.id, images: [staleBest, makeItem({ id: "stale-other" })] };
    const freshBest = makeItem({ id: "fresh-best", context_label: "FRESH-LABEL" });
    const freshGroup: SimilarityGroup = { best_id: freshBest.id, images: [freshBest, makeItem({ id: "fresh-other" })] };
    let resolveStale: (value: SimilarityGroupList) => void = () => {};
    let resolveFresh: (value: SimilarityGroupList) => void = () => {};
    const stalePromise = new Promise<SimilarityGroupList>((resolve) => {
      resolveStale = resolve;
    });
    const freshPromise = new Promise<SimilarityGroupList>((resolve) => {
      resolveFresh = resolve;
    });
    let call = 0;
    browserApiFetchMock.mockImplementation((url: string) => {
      if (url.startsWith("/api/files/similarity-groups")) {
        call += 1;
        return call === 1 ? stalePromise : freshPromise;
      }
      return Promise.resolve(null);
    });

    const { rerender } = render(<PhotoSimilarSeries search="cam" tagFilter={[]} />);
    rerender(<PhotoSimilarSeries search="camp2026" tagFilter={[]} />);

    // The newer (second) request's response lands first; the older (first) request's
    // stale response arrives after it - the opposite of request order, plausible under
    // normal network jitter.
    resolveFresh(ready([freshGroup]));
    await waitFor(() => expect(screen.queryByText(/FRESH-LABEL/)).not.toBeNull());
    resolveStale(ready([staleGroup]));

    // Give the stale promise's .then a tick to run (and be ignored, if the fix holds)
    // before asserting - without the fix, this is exactly where it would overwrite.
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(screen.queryByText(/FRESH-LABEL/)).not.toBeNull();
    expect(screen.queryByText(/STALE-LABEL/)).toBeNull();
  });

  it("requests the tight duplicate threshold, not the looser series one", async () => {
    browserApiFetchMock.mockImplementation((url: string) =>
      Promise.resolve(url.startsWith("/api/files/similarity-groups") ? ready([]) : null)
    );
    render(<PhotoSimilarSeries search="" tagFilter={[]} />);

    await waitFor(() =>
      expect(browserApiFetchMock).toHaveBeenCalledWith(expect.stringContaining("kind=duplicate"))
    );
  });

  it("keeping the series just dismisses the card without any request", async () => {
    const group = makeGroup();
    browserApiFetchMock.mockImplementation((url: string) => {
      if (url.startsWith("/api/files/similarity-groups")) return Promise.resolve(ready([group]));
      return Promise.resolve(null);
    });
    render(<PhotoSimilarSeries search="" tagFilter={[]} />);

    fireEvent.click(await screen.findByRole("button", { name: "Serie behalten" }));

    await waitFor(() => expect(screen.queryByRole("button", { name: "Serie behalten" })).not.toBeInTheDocument());
    expect(browserApiFetchMock.mock.calls.some(([url]) => url === "/api/files/bulk-delete")).toBe(false);
  });

  it("shows a hint while the server has not grouped the photos yet and asks again", async () => {
    vi.useFakeTimers();
    try {
      browserApiFetchMock.mockResolvedValueOnce({ status: "pending", computed_at: null, groups: [] });
      browserApiFetchMock.mockResolvedValueOnce(ready([makeGroup()]));
      render(<PhotoSimilarSeries search="" tagFilter={[]} />);
      await act(() => vi.advanceTimersByTimeAsync(0));
      expect(screen.getByText(/werden im Hintergrund gruppiert/)).toBeInTheDocument();

      await act(() => vi.advanceTimersByTimeAsync(SIMILARITY_PENDING_POLL_MS));
      expect(browserApiFetchMock).toHaveBeenCalledTimes(2);
      expect(screen.getByRole("button", { name: "Nur beste behalten" })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("explains when the tenant has too many photos for automatic grouping", async () => {
    browserApiFetchMock.mockResolvedValue({ status: "too_many", computed_at: "2026-10-24T09:00:00Z", groups: [] });
    render(<PhotoSimilarSeries search="" tagFilter={[]} />);

    expect(await screen.findByText(/Zu viele Fotos für die automatische Gruppierung/)).toBeInTheDocument();
  });

  it("shows when the groups were computed", async () => {
    browserApiFetchMock.mockResolvedValue(ready([makeGroup()]));
    render(<PhotoSimilarSeries search="" tagFilter={[]} />);

    expect(await screen.findByText(/^Stand .* neue Fotos erscheinen nach wenigen Minuten\.$/)).toBeInTheDocument();
  });

  it("shows the cached groups immediately when the tab is opened again and refreshes them quietly", async () => {
    const group = makeGroup();
    group.images[0].context_label = "CACHED-LABEL";
    browserApiFetchMock.mockResolvedValueOnce(ready([group]));
    const first = render(<PhotoSimilarSeries search="" tagFilter={[]} />);
    expect(await screen.findByText(/CACHED-LABEL/)).toBeInTheDocument();
    first.unmount();

    let resolveRefresh: (value: SimilarityGroupList) => void = () => {};
    browserApiFetchMock.mockReturnValueOnce(new Promise<SimilarityGroupList>((resolve) => { resolveRefresh = resolve; }));
    render(<PhotoSimilarSeries search="" tagFilter={[]} />);

    expect(screen.getByText(/CACHED-LABEL/)).toBeInTheDocument();
    expect(screen.queryByText("Serien werden geladen…")).not.toBeInTheDocument();
    expect(browserApiFetchMock).toHaveBeenCalledTimes(2);

    const refreshed = makeGroup();
    refreshed.images[0].context_label = "REFRESHED-LABEL";
    resolveRefresh(ready([refreshed]));
    expect(await screen.findByText(/REFRESHED-LABEL/)).toBeInTheDocument();
  });

  it("keeps the cached groups when the quiet refresh fails", async () => {
    const group = makeGroup();
    group.images[0].context_label = "CACHED-LABEL";
    browserApiFetchMock.mockResolvedValueOnce(ready([group]));
    const first = render(<PhotoSimilarSeries search="" tagFilter={[]} />);
    expect(await screen.findByText(/CACHED-LABEL/)).toBeInTheDocument();
    first.unmount();

    browserApiFetchMock.mockRejectedValueOnce(new ApiError("timeout", "timeout"));
    render(<PhotoSimilarSeries search="" tagFilter={[]} />);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(screen.getByText(/CACHED-LABEL/)).toBeInTheDocument();
    expect(screen.queryByText("Ähnliche Fotos konnten nicht geladen werden.")).not.toBeInTheDocument();
  });

  it("does not bring back a cleaned group from the cache after switching tabs", async () => {
    const group = makeGroup();
    group.images[0].context_label = "CLEANED-LABEL";
    let refresh: Promise<SimilarityGroupList> = Promise.resolve(ready([group]));
    browserApiFetchMock.mockImplementation((url: string) => {
      if (url.startsWith("/api/files/similarity-groups")) return refresh;
      if (url === "/api/files/bulk-delete") return Promise.resolve({ deleted_ids: ["other-1", "other-2"], errors: [] });
      return Promise.resolve(null);
    });
    confirmMock.mockResolvedValue(true);
    const first = render(<PhotoSimilarSeries search="" tagFilter={[]} />);
    fireEvent.click(await screen.findByRole("button", { name: "Nur beste behalten" }));
    await waitFor(() => expect(screen.queryByText(/CLEANED-LABEL/)).not.toBeInTheDocument());
    first.unmount();

    refresh = new Promise(() => {});
    render(<PhotoSimilarSeries search="" tagFilter={[]} />);

    expect(screen.queryByText(/CLEANED-LABEL/)).not.toBeInTheDocument();
    expect(screen.getByText("Keine ähnlichen Fotos gefunden.")).toBeInTheDocument();
  });
});
