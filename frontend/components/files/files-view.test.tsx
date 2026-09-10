import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

// jsdom has no real IntersectionObserver - fake one so the "load more" sentinel can be
// triggered deterministically instead of depending on real scroll/layout.
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
  trigger(isIntersecting: boolean) {
    this.callback([{ isIntersecting } as IntersectionObserverEntry], this);
  }
}

import { FilesView } from "./files-view";

function makeItem(overrides: Partial<FileOverviewItem> = {}): FileOverviewItem {
  const id = overrides.id ?? `file-${Math.random().toString(36).slice(2)}`;
  return {
    id,
    original_name: "urlaubsfoto.jpg",
    mime_type: "image/jpeg",
    file_size_bytes: 12_345,
    created_at: "2026-08-01T10:00:00Z",
    source: "gallery_upload",
    is_image: true,
    content_url: `/api/stored-files/${id}`,
    thumbnail_url: `/api/stored-files/${id}/thumbnail`,
    tags_url: `/api/stored-files/${id}/tags`,
    metadata_url: `/api/stored-files/${id}/metadata`,
    ref_label: "",
    ref_date: null,
    ref_href: null,
    tags: [],
    origin_tag: "Galerie",
    ...overrides,
  };
}

describe("FilesView (Fotos gallery)", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    routerPushMock.mockReset();
    showToastMock.mockReset();
    FakeIntersectionObserver.instances = [];
    vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
    // Every mount fetches the tag-suggestions list; resolve it for every test unless
    // a test overrides this first call itself.
    browserApiFetchMock.mockResolvedValue([]);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows only all photos and albums tabs", () => {
    render(<FilesView mode="photos" initialItems={[]} />);
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Alle Fotos", "Alben"]);
  });

  it("shows a quality-focused sort selector for photos, not the files name/size options", () => {
    render(<FilesView mode="photos" initialItems={[]} />);
    expect(screen.getByText("Schärfe (am schärfsten zuerst)")).toBeInTheDocument();
    expect(screen.getByText("Gesichtsqualität (am besten zuerst)")).toBeInTheDocument();
    expect(screen.queryByText("Name (A-Z)")).not.toBeInTheDocument();
    expect(screen.queryByText(/Grösse/)).not.toBeInTheDocument();
  });

  it("creates a persistent album and opens its photos", async () => {
    browserApiFetchMock.mockImplementation((url: string, options?: { method?: string }) => {
      if (url === "/api/files/albums" && options?.method === "POST") {
        return Promise.resolve({ id: "album-1", name: "Sommerlager" });
      }
      return Promise.resolve([]);
    });
    render(<FilesView mode="photos" initialItems={[]} />);
    fireEvent.click(screen.getByRole("tab", { name: "Alben" }));
    fireEvent.click(screen.getByRole("button", { name: "+ Album erstellen" }));
    fireEvent.change(screen.getByLabelText("Albumname"), { target: { value: "Sommerlager" } });
    fireEvent.click(screen.getByRole("button", { name: "Album erstellen" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Sommerlager" })).toBeInTheDocument());
    await waitFor(() => expect(browserApiFetchMock.mock.calls.some(([url]) => url.includes("album_id=album-1") && url.includes("sort_by=created_at") && url.includes("sort_dir=desc"))).toBe(true));
  });

  it("renders each photo's <img> with the thumbnail URL and native lazy loading", () => {
    const item = makeItem({ id: "a1" });
    render(<FilesView mode="photos" initialItems={[item]} />);

    const img = screen.getByAltText("urlaubsfoto.jpg") as HTMLImageElement;
    expect(img.getAttribute("loading")).toBe("lazy");
    expect(img.getAttribute("decoding")).toBe("async");
    expect(img.src).toContain("/api/stored-files/a1/thumbnail");
  });

  it("falls back to the full-size content URL when no thumbnail exists yet", () => {
    const item = makeItem({ id: "b2", thumbnail_url: null });
    render(<FilesView mode="photos" initialItems={[item]} />);

    const img = screen.getByAltText("urlaubsfoto.jpg") as HTMLImageElement;
    expect(img.src).toContain("/api/stored-files/b2");
    expect(img.src).not.toContain("thumbnail");
  });

  it("does not render an <img> for non-image files (icon tile instead)", () => {
    const item = makeItem({ id: "c3", is_image: false, original_name: "bericht.pdf", mime_type: "application/pdf" });
    render(<FilesView mode="files" initialItems={[item]} />);

    expect(screen.queryByAltText("bericht.pdf")).not.toBeInTheDocument();
    expect(screen.getByText("PDF")).toBeInTheDocument();
  });

  it("shows a load-more sentinel once a full page has loaded, and paginates via manual click", async () => {
    const fullPage = Array.from({ length: 60 }, (_, i) => makeItem({ id: `page1-${i}` }));
    const secondPage = [makeItem({ id: "page2-0" })];

    render(<FilesView mode="photos" initialItems={fullPage} />);

    expect(screen.getByText(/Mehr laden/)).toBeInTheDocument();

    browserApiFetchMock.mockResolvedValueOnce(secondPage);
    fireEvent.click(screen.getByText(/Mehr laden/));

    await waitFor(() => expect(screen.getAllByRole("img")).toHaveLength(61));
    const [calledUrl] = browserApiFetchMock.mock.calls.at(-1)!;
    expect(calledUrl).toContain("skip=60");
  });

  it("auto-loads the next page once the sentinel scrolls into view (infinite scroll)", async () => {
    const fullPage = Array.from({ length: 60 }, (_, i) => makeItem({ id: `p1-${i}` }));
    const secondPage = [makeItem({ id: "p2-0" })];

    render(<FilesView mode="photos" initialItems={fullPage} />);
    expect(FakeIntersectionObserver.instances.length).toBeGreaterThan(0);

    browserApiFetchMock.mockResolvedValueOnce(secondPage);
    FakeIntersectionObserver.instances.at(-1)!.trigger(true);

    await waitFor(() => expect(screen.getAllByRole("img")).toHaveLength(61));
  });

  it("hides the load-more sentinel once a short page indicates there is nothing left", () => {
    const shortPage = [makeItem({ id: "only-one" })];
    render(<FilesView mode="photos" initialItems={shortPage} />);

    expect(screen.queryByText(/Mehr laden/)).not.toBeInTheDocument();
  });
});
