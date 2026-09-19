import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FileOverviewItem } from "@/types/api";

const browserApiFetchMock = vi.fn();
const routerPushMock = vi.fn();
const showToastMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiBaseUrl: "",
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

vi.mock("@/contexts/toast-context", () => ({
  useToast: () => showToastMock,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPushMock }),
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

import { FilesView } from "./files-view";

function makeItem(overrides: Partial<FileOverviewItem> = {}): FileOverviewItem {
  const id = overrides.id ?? `file-${Math.random().toString(36).slice(2)}`;
  return {
    id,
    original_name: "bericht.pdf",
    mime_type: "application/pdf",
    file_size_bytes: 12_345,
    created_at: "2026-08-01T10:00:00Z",
    source: "word_import",
    is_image: false,
    content_url: `/api/stored-files/${id}/content`,
    thumbnail_url: null,
    tags_url: `/api/stored-files/${id}/tags`,
    metadata_url: `/api/stored-files/${id}/metadata`,
    ref_label: "1. Hock",
    ref_date: null,
    ref_href: null,
    tags: [],
    origin_tag: "Word-Import: 1. Hock",
    sharpness_score: null,
    exposure_score: null,
    face_quality_score: null,
    face_analyzed_at: null,
    width: null,
    height: null,
    group_date: "2026-08-01",
    context_label: "1. Hock",
    albums: [],
    is_best: null,
    ...overrides,
  };
}

describe("FilesView (Dateien)", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    routerPushMock.mockReset();
    showToastMock.mockReset();
    FakeIntersectionObserver.instances = [];
    vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
    browserApiFetchMock.mockResolvedValue([]);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders the stat cards", async () => {
    browserApiFetchMock.mockImplementation((url: string) => {
      if (url === "/api/files/stats") return Promise.resolve({ document_count: 48, photo_count: 266, total_bytes: 1_900_000_000 });
      return Promise.resolve([]);
    });
    render(<FilesView initialItems={[]} />);

    expect(await screen.findByText("Dokumente")).toBeInTheDocument();
    expect(await screen.findByText("48")).toBeInTheDocument();
    expect(screen.getByText("Fotos")).toBeInTheDocument();
    expect(screen.getByText("266")).toBeInTheDocument();
    expect(screen.getByText("Speicher")).toBeInTheDocument();
  });

  it("renders each file as a table row with name/source badge/size", () => {
    const item = makeItem({ id: "a1", original_name: "1. Hock vom 14.10.2026.docx", source: "word_import" });
    render(<FilesView initialItems={[item]} />);

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("1. Hock vom 14.10.2026.docx")).toBeInTheDocument();
    expect(screen.getByText("Word-Import", { selector: ".badge" })).toBeInTheDocument();
  });

  it("offers a Download link pointing at the file's content URL", () => {
    const item = makeItem({ id: "a1" });
    render(<FilesView initialItems={[item]} />);

    const link = screen.getByRole("link", { name: "Download" }) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toContain("/api/stored-files/a1/content");
  });

  it("shows an empty state when there are no files", () => {
    render(<FilesView initialItems={[]} />);
    expect(screen.getByText("Keine Dateien gefunden.")).toBeInTheDocument();
  });

  it("shows a load-more sentinel once a full page has loaded", () => {
    const fullPage = Array.from({ length: 60 }, (_, i) => makeItem({ id: `page1-${i}` }));
    render(<FilesView initialItems={fullPage} />);

    expect(screen.getByText(/Mehr laden/)).toBeInTheDocument();
  });

  it("hides the load-more sentinel once a short page indicates there is nothing left", () => {
    const shortPage = [makeItem({ id: "only-one" })];
    render(<FilesView initialItems={shortPage} />);

    expect(screen.queryByText(/Mehr laden/)).not.toBeInTheDocument();
  });

  it("opens the document upload window from the header button", () => {
    render(<FilesView initialItems={[]} />);
    expect(screen.queryByText("Dateien hochladen", { selector: "h2" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "+ Dateien hochladen" }));

    expect(screen.getByText("Dateien hochladen", { selector: "h2" })).toBeInTheDocument();
    expect(screen.getByText("Noch keine Dateien ausgewählt.")).toBeInTheDocument();
  });
});
