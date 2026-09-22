import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FileOverviewItem } from "@/types/api";

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

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

class FakeIntersectionObserver implements IntersectionObserver {
  static instances: FakeIntersectionObserver[] = [];
  readonly root = null;
  readonly rootMargin = "";
  readonly thresholds: ReadonlyArray<number> = [];
  constructor(private callback: IntersectionObserverCallback) {
    FakeIntersectionObserver.instances.push(this);
  }
  intersect() { this.callback([{ isIntersecting: true, intersectionRatio: 1 } as IntersectionObserverEntry], this); }
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
}

import { PhotosView } from "./photos-view";

function makeItem(overrides: Partial<FileOverviewItem> = {}): FileOverviewItem {
  const id = overrides.id ?? `file-${Math.random().toString(36).slice(2)}`;
  return {
    id,
    original_name: "urlaubsfoto.jpg",
    mime_type: "image/jpeg",
    file_size_bytes: 12_345,
    created_at: "2026-07-10T10:00:00Z",
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
    sharpness_score: null,
    exposure_score: null,
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

function mockFilesAndProgress(items: FileOverviewItem[], progress: { total_images: number; analyzed_images: number; pending_images: number; active_jobs: number; active_job_image_count: number }) {
  browserApiFetchMock.mockImplementation((url: string) => {
    if (url === "/api/files/analysis-progress") return Promise.resolve(progress);
    if (url === "/api/files/tags") return Promise.resolve([]);
    if (url === "/api/files/albums") return Promise.resolve([]);
    if (url.startsWith("/api/files?")) return Promise.resolve(items);
    return Promise.resolve([]);
  });
}

const NO_PROGRESS = { total_images: 0, analyzed_images: 0, pending_images: 0, active_jobs: 0, active_job_image_count: 0 };

describe("PhotosView", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
    confirmMock.mockReset();
    FakeIntersectionObserver.instances = [];
    vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows the Alle Fotos / Alben / Duplikate / Ähnliche tabs", () => {
    mockFilesAndProgress([], NO_PROGRESS);
    render(<PhotosView />);
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Alle Fotos", "Alben", "Duplikate", "Ähnliche"]);
  });

  it("preserves photos after a pagination failure, pauses automatic loading and retries the same page", async () => {
    const items = Array.from({ length: 60 }, (_, index) => makeItem({ id: `photo-${index}` }));
    mockFilesAndProgress([], NO_PROGRESS);
    browserApiFetchMock.mockImplementation((url: string) => {
      if (url === "/api/files/analysis-progress") return Promise.resolve(NO_PROGRESS);
      if (url.startsWith("/api/files?")) return url.includes("skip=0") ? Promise.resolve(items) : Promise.reject(new Error("Backend nicht erreichbar"));
      return Promise.resolve([]);
    });
    render(<PhotosView />);
    await screen.findByRole("button", { name: "Mehr laden (60 geladen)" });

    fireEvent.click(screen.getByRole("button", { name: "Mehr laden (60 geladen)" }));
    const retry = await screen.findByRole("button", { name: "Erneut versuchen" });
    expect(showToastMock).toHaveBeenCalledWith(expect.stringContaining("Weitere Fotos"), "error");
    expect(screen.getAllByRole("checkbox")).toHaveLength(60);
    const observerCount = FakeIntersectionObserver.instances.length;

    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    expect(FakeIntersectionObserver.instances).toHaveLength(observerCount);

    browserApiFetchMock.mockImplementation((url: string) => {
      if (url.startsWith("/api/files?")) return Promise.resolve([makeItem({ id: "next-photo" })]);
      return Promise.resolve([]);
    });
    fireEvent.click(retry);
    await waitFor(() => expect(screen.getAllByRole("checkbox")).toHaveLength(61));
    const pageRequests = browserApiFetchMock.mock.calls.filter(([url]) => url.startsWith("/api/files?") && url.includes("skip=60"));
    expect(pageRequests).toHaveLength(2);
    expect(pageRequests[0][0]).toContain("skip=60");
    expect(pageRequests[1][0]).toBe(pageRequests[0][0]);
    expect(screen.queryByRole("button", { name: "Erneut versuchen" })).not.toBeInTheDocument();
  });

  it("renders controls and placeholders while photos are pending, then reveals each loaded image", async () => {
    let resolvePhotos!: (items: FileOverviewItem[]) => void;
    const pendingPhotos = new Promise<FileOverviewItem[]>((resolve) => { resolvePhotos = resolve; });
    browserApiFetchMock.mockImplementation((url: string) => {
      if (url.startsWith("/api/files?")) return pendingPhotos;
      if (url === "/api/files/analysis-progress") return Promise.resolve(NO_PROGRESS);
      return Promise.resolve([]);
    });
    render(<PhotosView />);

    expect(screen.getByRole("heading", { name: "Fotos" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ Bilder hochladen" })).toBeEnabled();
    expect(screen.getByRole("status", { name: "Fotos werden geladen" })).toBeInTheDocument();
    expect(screen.queryByText("Keine Fotos gefunden.")).not.toBeInTheDocument();
    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/files?")));

    resolvePhotos([makeItem({ id: "pending" })]);
    const image = await screen.findByRole("img", { name: "urlaubsfoto.jpg" });
    expect(screen.queryByRole("status", { name: "Fotos werden geladen" })).not.toBeInTheDocument();
    expect(image.parentElement).toHaveStyle({ aspectRatio: "1.3333333333333333" });
    expect(image.parentElement).not.toHaveClass("photo-tile-preview-loaded");
    act(() => FakeIntersectionObserver.instances.forEach((observer) => observer.intersect()));
    fireEvent.load(image);
    expect(image.parentElement).toHaveClass("photo-tile-preview-loaded");
  });

  it("groups photos under a date header with weekday/date and count", async () => {
    const items = [
      makeItem({ id: "a", group_date: "2026-07-10" }),
      makeItem({ id: "b", group_date: "2026-07-10" }),
    ];
    mockFilesAndProgress(items, NO_PROGRESS);
    render(<PhotosView />);

    expect(await screen.findByText(/Freitag, 10\. Juli 2026/)).toBeInTheDocument();
    expect(screen.getByText(/2 Fotos/)).toBeInTheDocument();
  });

  it("shows the bulk-action bar with a count once photos are selected", async () => {
    const items = [makeItem({ id: "a" }), makeItem({ id: "b" })];
    mockFilesAndProgress(items, NO_PROGRESS);
    render(<PhotosView />);

    const checkboxes = await screen.findAllByRole("checkbox");
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);

    await waitFor(() => expect(screen.getByText("2 ausgewählt")).toBeInTheDocument());
  });

  it("never renders the analysis progress bar text", async () => {
    mockFilesAndProgress([], NO_PROGRESS);
    render(<PhotosView />);

    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalledWith("/api/files/analysis-progress"));
    expect(screen.queryByText(/Foto-Analyse läuft/)).not.toBeInTheDocument();
  });

  it("shows the analysis pill next to the page title while pending", async () => {
    mockFilesAndProgress([], { total_images: 30, analyzed_images: 19, pending_images: 11, active_jobs: 1, active_job_image_count: 11 });
    render(<PhotosView />);

    expect(await screen.findByText(/Analyse läuft · 11 Bilder/)).toBeInTheDocument();
    expect(screen.queryByText(/19 von 30 Bildern bewertet/)).not.toBeInTheDocument();
  });
});
