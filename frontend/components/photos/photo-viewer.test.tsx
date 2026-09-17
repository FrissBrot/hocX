import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FileOverviewItem } from "@/types/api";

const browserApiFetchMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiBaseUrl: "",
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

import { PhotoViewer } from "./photo-viewer";

function makeItem(overrides: Partial<FileOverviewItem> = {}): FileOverviewItem {
  const id = overrides.id ?? `file-${Math.random().toString(36).slice(2)}`;
  return {
    id,
    original_name: "IMG_4118.jpg",
    mime_type: "image/jpeg",
    file_size_bytes: 1_800_000,
    created_at: "2026-07-10T08:02:00Z",
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
    sharpness_score: 34.0,
    exposure_score: 0.42,
    face_quality_score: null,
    face_analyzed_at: null,
    width: null,
    height: null,
    group_date: "2026-07-10",
    context_label: null,
    albums: [],
    is_best: false,
    ...overrides,
  };
}

describe("PhotoViewer", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    browserApiFetchMock.mockResolvedValue(null);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("keeps the thumbnail visible until the original is decoded", async () => {
    let finishDecode!: () => void;
    const original = { src: "", onload: null as (() => Promise<void>) | null, decode: vi.fn(() => new Promise<void>((resolve) => { finishDecode = resolve; })) };
    vi.stubGlobal("Image", vi.fn(function () { return original; }));
    const item = makeItem();
    render(<PhotoViewer items={[item]} index={0} onIndexChange={vi.fn()} onClose={vi.fn()} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} />);

    expect(screen.getByRole("img")).toHaveAttribute("src", item.thumbnail_url);
    expect(original.src).toBe(item.content_url);
    expect(screen.getByRole("status", { name: "Originalbild wird geladen" })).toBeInTheDocument();
    const loading = original.onload!();
    expect(screen.getByRole("img")).toHaveAttribute("src", item.thumbnail_url);
    await act(async () => { finishDecode(); await loading; });
    expect(screen.getByRole("img")).toHaveAttribute("src", item.content_url);
    expect(screen.queryByRole("status", { name: "Originalbild wird geladen" })).not.toBeInTheDocument();
  });

  it("ignores an old decode after navigating and keeps the preview if decoding fails", async () => {
    let finishDecode!: () => void;
    const originals: { src: string; onload: (() => Promise<void>) | null; decode: () => Promise<void> }[] = [];
    vi.stubGlobal("Image", vi.fn(function () {
      const original = { src: "", onload: null, decode: vi.fn(() => new Promise<void>((resolve) => { finishDecode = resolve; })) };
      originals.push(original);
      return original;
    }));
    const items = [makeItem({ id: "a" }), makeItem({ id: "b" })];
    const props = { items, onIndexChange: vi.fn(), onClose: vi.fn(), onToggleBest: vi.fn(), onTagsSaved: vi.fn() };
    const { rerender } = render(<PhotoViewer {...props} index={0} />);
    const loading = originals[0].onload!();
    rerender(<PhotoViewer {...props} index={1} />);
    expect(screen.getByRole("img")).toHaveAttribute("src", items[1].thumbnail_url);
    await act(async () => { finishDecode(); await loading; });
    expect(screen.getByRole("img")).toHaveAttribute("src", items[1].thumbnail_url);
    originals[1].decode = () => Promise.reject(new Error("Invalid image"));
    await act(async () => { await originals[1].onload!(); });
    expect(screen.getByRole("img")).toHaveAttribute("src", items[1].thumbnail_url);
    expect(screen.queryByRole("status", { name: "Originalbild wird geladen" })).not.toBeInTheDocument();
  });

  it("uses the original directly when no thumbnail exists", () => {
    const item = makeItem({ thumbnail_url: null });
    render(<PhotoViewer items={[item]} index={0} onIndexChange={vi.fn()} onClose={vi.fn()} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} />);
    expect(screen.getByRole("img")).toHaveAttribute("src", item.content_url);
    expect(screen.getByRole("status", { name: "Originalbild wird geladen" })).toBeInTheDocument();
    fireEvent.load(screen.getByRole("img"));
    expect(screen.queryByRole("status", { name: "Originalbild wird geladen" })).not.toBeInTheDocument();
  });

  it("shows formatted Schärfe/Belichtung values and 'Analyse ausstehend' for face quality when not yet analyzed", async () => {
    const item = makeItem({ sharpness_score: 34.0, exposure_score: 0.42, face_analyzed_at: null, face_quality_score: null });
    render(<PhotoViewer items={[item]} index={0} onIndexChange={vi.fn()} onClose={vi.fn()} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} />);

    expect(screen.getByText("34.0")).toBeInTheDocument();
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(screen.getByText("Analyse ausstehend")).toBeInTheDocument();
  });

  it("shows '0 Bytes' instead of hiding the Grösse row for a 0-byte file (audit fix, 2026-09-17)", () => {
    const item = makeItem({ file_size_bytes: 0 });
    render(<PhotoViewer items={[item]} index={0} onIndexChange={vi.fn()} onClose={vi.fn()} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} />);

    expect(screen.getByText("Grösse")).toBeInTheDocument();
  });

  it("shows 'Kein Gesicht erkannt' once analyzed with no detected face", () => {
    const item = makeItem({ face_analyzed_at: "2026-07-10T09:00:00Z", face_quality_score: null });
    render(<PhotoViewer items={[item]} index={0} onIndexChange={vi.fn()} onClose={vi.fn()} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} />);

    expect(screen.getByText("Kein Gesicht erkannt")).toBeInTheDocument();
  });

  it("shows the face-quality score once analyzed with a detected face", () => {
    const item = makeItem({ face_analyzed_at: "2026-07-10T09:00:00Z", face_quality_score: 3.6 });
    render(<PhotoViewer items={[item]} index={0} onIndexChange={vi.fn()} onClose={vi.fn()} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} />);

    expect(screen.getByText("3.6 / 10")).toBeInTheDocument();
  });

  it("advances to the next photo and updates the counter", () => {
    const items = [makeItem({ id: "a", original_name: "a.jpg" }), makeItem({ id: "b", original_name: "b.jpg" })];
    const onIndexChange = vi.fn();
    render(<PhotoViewer items={items} index={0} onIndexChange={onIndexChange} onClose={vi.fn()} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} />);

    expect(screen.getByText(/1\/2/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Nächstes Foto"));
    expect(onIndexChange).toHaveBeenCalledWith(1);
  });

  it("has no previous-photo button on the first image", () => {
    const items = [makeItem({ id: "a" }), makeItem({ id: "b" })];
    render(<PhotoViewer items={items} index={0} onIndexChange={vi.fn()} onClose={vi.fn()} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} />);

    expect(screen.queryByLabelText("Vorheriges Foto")).not.toBeInTheDocument();
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    const item = makeItem();
    render(<PhotoViewer items={[item]} index={0} onIndexChange={vi.fn()} onClose={onClose} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} />);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });
});
