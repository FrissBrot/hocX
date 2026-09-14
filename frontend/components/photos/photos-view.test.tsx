import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

  it("shows the Alle Fotos / Alben / Ähnliche tabs", () => {
    mockFilesAndProgress([], NO_PROGRESS);
    render(<PhotosView />);
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Alle Fotos", "Alben", "Ähnliche"]);
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

  it("hides the analysis progress bar once nothing is pending", async () => {
    mockFilesAndProgress([], NO_PROGRESS);
    render(<PhotosView />);

    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalledWith("/api/files/analysis-progress"));
    expect(screen.queryByText(/Foto-Analyse läuft/)).not.toBeInTheDocument();
  });

  it("shows the analysis progress bar with the analyzed/total count while pending", async () => {
    mockFilesAndProgress([], { total_images: 30, analyzed_images: 19, pending_images: 11, active_jobs: 1, active_job_image_count: 11 });
    render(<PhotosView />);

    expect(await screen.findByText(/19 von 30 Bildern bewertet/)).toBeInTheDocument();
  });
});
