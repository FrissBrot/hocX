import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FileOverviewItem } from "@/types/api";

const browserApiFetchMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiBaseUrl: "",
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

const showToastMock = vi.fn();
vi.mock("@/contexts/toast-context", () => ({ useToast: () => showToastMock }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));

import { PhotoViewer } from "./photo-viewer";
import { clearSimilarityGroupsCache } from "./use-similarity-groups";

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
    ref_end_date: null,
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
    live_video_url: null,
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

    expect(screen.getByText("Unscharf · 39/100")).toBeInTheDocument();
    expect(screen.getByText("Starkes Clipping · 42%")).toBeInTheDocument();
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
    const item = makeItem({ face_analyzed_at: "2026-07-10T09:00:00Z", face_quality_score: 3023.0 });
    render(<PhotoViewer items={[item]} index={0} onIndexChange={vi.fn()} onClose={vi.fn()} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} />);

    expect(screen.getByText("Sehr scharf · 87/100")).toBeInTheDocument();
  });

  it("advances to the next photo and updates the counter", () => {
    const items = [makeItem({ id: "a", original_name: "a.jpg" }), makeItem({ id: "b", original_name: "b.jpg" })];
    const onIndexChange = vi.fn();
    render(<PhotoViewer items={items} index={0} onIndexChange={onIndexChange} onClose={vi.fn()} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} />);

    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Nächstes Foto"));
    expect(onIndexChange).toHaveBeenCalledWith(1);
  });

  it("has no previous-photo button on the first image", () => {
    const items = [makeItem({ id: "a" }), makeItem({ id: "b" })];
    render(<PhotoViewer items={items} index={0} onIndexChange={vi.fn()} onClose={vi.fn()} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} />);

    expect(screen.queryByLabelText("Vorheriges Foto")).not.toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    const onClose = vi.fn();
    const item = makeItem();
    render(<PhotoViewer items={[item]} index={0} onIndexChange={vi.fn()} onClose={onClose} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} />);

    fireEvent.keyDown(window, { key: "Escape" });
    // Escape wartet auf den ausstehenden Speicherpfad (useDeferredPopupSave.flush), bevor geschlossen wird.
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});

describe("PhotoViewer Live Photo", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    browserApiFetchMock.mockResolvedValue(null);
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("offers no LIVE button for an ordinary photo", () => {
    render(<PhotoViewer items={[makeItem()]} index={0} onIndexChange={vi.fn()} onClose={vi.fn()} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Live Photo abspielen" })).not.toBeInTheDocument();
  });

  it("plays the clip via the LIVE button (touch/keyboard) and stops it on a second press", () => {
    vi.useFakeTimers();
    const item = makeItem({ live_video_url: "/api/stored-files/clip/content" });
    render(<PhotoViewer items={[item]} index={0} onIndexChange={vi.fn()} onClose={vi.fn()} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} />);
    const button = screen.getByRole("button", { name: "Live Photo abspielen" });
    expect(button).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(button);
    act(() => { vi.advanceTimersByTime(200); });
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();

    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-pressed", "false");
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
  });

  it("plays the clip while the pointer is over the photo", () => {
    vi.useFakeTimers();
    const item = makeItem({ live_video_url: "/api/stored-files/clip/content" });
    render(<PhotoViewer items={[item]} index={0} onIndexChange={vi.fn()} onClose={vi.fn()} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} />);
    const stage = document.querySelector(".photo-viewer-stage")!;

    fireEvent.mouseEnter(stage);
    act(() => { vi.advanceTimersByTime(200); });
    expect(document.querySelector("video")).toHaveAttribute("src", "/api/stored-files/clip/content");
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
  });

  it("lets the user choose image, video or both when downloading a Live Photo", () => {
    const item = makeItem({ id: "live-1", live_video_url: "/api/stored-files/clip/content" });
    render(<PhotoViewer items={[item]} index={0} onIndexChange={vi.fn()} onClose={vi.fn()} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} />);
    expect(screen.queryByRole("menuitem")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Herunterladen/ }));

    expect(screen.getByRole("menuitem", { name: "Bild (JPEG)" })).toHaveAttribute("href", "/api/stored-files/live-1/download?part=image");
    expect(screen.getByRole("menuitem", { name: "Video (MP4)" })).toHaveAttribute("href", "/api/stored-files/live-1/download?part=video");
    expect(screen.getByRole("menuitem", { name: "Bild und Video (ZIP)" })).toHaveAttribute("href", "/api/stored-files/live-1/download?part=both");
  });

  it("downloads an ordinary photo directly, without a choice", () => {
    render(<PhotoViewer items={[makeItem({ id: "plain" })]} index={0} onIndexChange={vi.fn()} onClose={vi.fn()} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /Herunterladen/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Herunterladen" })).toHaveAttribute("href", "/api/stored-files/plain/download?part=image");
  });

  it("navigates with arrow keys, but not while typing in the tag field (Audit MAIN-FE-006)", () => {
    const onIndexChange = vi.fn();
    const items = [makeItem({ id: "a" }), makeItem({ id: "b" }), makeItem({ id: "c" })];
    render(<PhotoViewer items={items} index={1} onIndexChange={onIndexChange} onClose={vi.fn()} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} canManage />);

    const input = screen.getAllByRole("textbox")[0];
    input.focus();
    fireEvent.keyDown(input, { key: "ArrowLeft" });
    fireEvent.keyDown(input, { key: "ArrowRight" });
    expect(onIndexChange).not.toHaveBeenCalled();

    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(onIndexChange).toHaveBeenCalledWith(0);
  });

  it("ignores a late metadata response of the previous photo (Audit MAIN-FE-007)", async () => {
    const pending: Record<string, (value: unknown) => void> = {};
    browserApiFetchMock.mockImplementation((url: string) => new Promise((resolve) => { pending[url] = resolve; }));
    const a = makeItem({ id: "a" });
    const b = makeItem({ id: "b" });
    const props = { onIndexChange: vi.fn(), onClose: vi.fn(), onToggleBest: vi.fn(), onTagsSaved: vi.fn() };
    const { rerender } = render(<PhotoViewer items={[a, b]} index={0} {...props} />);
    rerender(<PhotoViewer items={[a, b]} index={1} {...props} />);

    await act(async () => { pending[b.metadata_url]({ exif_camera: "Kamera B" }); });
    await act(async () => { pending[a.metadata_url]({ exif_camera: "Kamera A" }); });

    expect(screen.getByText("Kamera B")).toBeInTheDocument();
    expect(screen.queryByText("Kamera A")).not.toBeInTheDocument();
  });

  it("Kopfzeile: beim Blättern weder Metadaten des vorigen Fotos noch Lücken, bis die neuen da sind (1.6)", async () => {
    const pending: Record<string, (value: unknown) => void> = {};
    browserApiFetchMock.mockImplementation((url: string) => new Promise((resolve) => { pending[url] = resolve; }));
    const a = makeItem({ id: "a", date_source: "corrected", capture_corrected_at: "2026-07-10T14:32:00" });
    const b = makeItem({ id: "b", group_date: "2026-07-11", date_source: "exif", exif_taken_at: "2026-07-11T09:15:00" });
    const props = { onIndexChange: vi.fn(), onClose: vi.fn(), onToggleBest: vi.fn(), onTagsSaved: vi.fn() };
    const { container, rerender } = render(<PhotoViewer items={[a, b]} index={0} {...props} />);
    const subtitle = () => container.ownerDocument.querySelector(".photo-viewer-subtitle") as HTMLElement;
    await act(async () => {
      pending[a.metadata_url]({ id: "a", date_source: "corrected", capture_corrected_at: "2026-07-10T14:32:00", capture_corrected_has_time: true });
    });
    expect(subtitle()).toHaveTextContent("14:32");
    expect(subtitle()).toHaveTextContent("korrigiert");

    // b lädt noch: Uhrzeit aus der Liste, kein Badge und keine Uhrzeit von a
    rerender(<PhotoViewer items={[a, b]} index={1} {...props} />);
    expect(subtitle()).toHaveTextContent("09:15");
    expect(subtitle()).not.toHaveTextContent("korrigiert");
    expect(subtitle()).not.toHaveTextContent("14:32");
    // Datum, Ort (Zeile bleibt reserviert) und Position stehen immer in derselben Struktur
    expect(subtitle().querySelector(".photo-viewer-subtitle-date")).not.toBeNull();
    expect(subtitle().querySelector(".photo-viewer-subtitle-place")).not.toBeNull();
    expect(subtitle().querySelector(".photo-viewer-subtitle-position")).toHaveTextContent("2 / 2");

    await act(async () => { pending[b.metadata_url]({ id: "b", date_source: "exif", exif_taken_at: "2026-07-11T09:15:00" }); });
    expect(subtitle()).toHaveTextContent("09:15");
  });
});

describe("Foto-Ansicht: Tastatur, Löschen und Vergleich", () => {
  const items = [
    makeItem({ id: "best", original_name: "best.jpg", sharpness_score: 1200, exposure_score: 0.97 }),
    makeItem({ id: "blurry", original_name: "blurry.jpg", sharpness_score: 20 }),
    makeItem({ id: "proto", original_name: "proto.jpg", source: "protocol_image", origin_tag: "Protokoll", context_label: "Lagerbericht", ref_href: "/protocols/p1" }),
    makeItem({ id: "lonely", original_name: "lonely.jpg" }),
  ];
  const series = { best_id: "best", images: items.slice(0, 3) };

  function mockApi(handler?: (url: string, init?: { method?: string; body?: string }) => unknown) {
    browserApiFetchMock.mockImplementation((url: string, init?: { method?: string; body?: string }) => {
      if (url.startsWith("/api/files/similarity-groups")) {
        return Promise.resolve({ status: "ready", computed_at: null, groups: url.includes("kind=series") ? [series] : [] });
      }
      return Promise.resolve(handler?.(url, init) ?? null);
    });
  }

  function renderViewer(index: number, extra: Record<string, unknown> = {}) {
    const props = { onIndexChange: vi.fn(), onClose: vi.fn(), onToggleBest: vi.fn(), onTagsSaved: vi.fn(), onRemoved: vi.fn(), onRestored: vi.fn(), ...extra };
    render(<PhotoViewer items={items} index={index} canManage {...props} />);
    return props;
  }

  beforeEach(() => {
    clearSimilarityGroupsCache();
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
    vi.stubGlobal("Image", vi.fn(function () { return { src: "", decode: () => Promise.resolve() }; }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("B schaltet Best-of um, ←/→ blättern - nur mit Schreibrecht für B", () => {
    mockApi();
    const props = renderViewer(1);
    fireEvent.keyDown(window, { key: "b" });
    expect(props.onToggleBest).toHaveBeenCalledWith(items[1]);
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(props.onIndexChange).toHaveBeenLastCalledWith(2);
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(props.onIndexChange).toHaveBeenLastCalledWith(0);
    expect(screen.getByRole("button", { name: /Best-of/ })).toHaveAttribute("aria-keyshortcuts", "B");
  });

  it("ohne photos.manage keine Best-of-, Lösch- oder Vergleichsbedienung", async () => {
    mockApi();
    const onToggleBest = vi.fn();
    render(<PhotoViewer items={items} index={0} onIndexChange={vi.fn()} onClose={vi.fn()} onToggleBest={onToggleBest} onTagsSaved={vi.fn()} />);
    fireEvent.keyDown(window, { key: "b" });
    fireEvent.keyDown(window, { key: "Delete" });
    expect(onToggleBest).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Löschen/ })).toBeNull();
    expect(screen.queryByRole("dialog", { name: "In den Papierkorb verschieben?" })).toBeNull();
    expect(screen.queryByText("Doppelt & ähnlich")).toBeNull();
  });

  it("Entf öffnet die Rückfrage, Escape schliesst nur sie; bestätigt landet das Foto im Papierkorb mit Rückgängig", async () => {
    mockApi((url) => {
      if (url === "/api/files/trash") return { file_ids: ["lonely"], errors: [] };
      if (url === "/api/files/trash/restore") return { file_ids: ["lonely"], errors: [] };
      return null;
    });
    const props = renderViewer(3);
    fireEvent.keyDown(window, { key: "Delete" });
    const dialog = await screen.findByRole("dialog", { name: "In den Papierkorb verschieben?" });
    expect(dialog).toHaveTextContent("«lonely.jpg» verschwindet aus Galerie und Alben");
    // Start auf «Abbrechen» (Löschen-Rückfragen starten nie auf der zerstörerischen Aktion)
    expect(document.activeElement).toHaveTextContent("Abbrechen");
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "In den Papierkorb verschieben?" })).toBeNull());
    expect(props.onClose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /Löschen/ }));
    fireEvent.click(await screen.findByRole("button", { name: "In den Papierkorb" }));
    await waitFor(() => expect(props.onRemoved).toHaveBeenCalledWith(["lonely"], null));
    expect(JSON.parse(browserApiFetchMock.mock.calls.find(([url]) => url === "/api/files/trash")![1].body)).toEqual({ file_ids: ["lonely"] });
    const [message, tone, options] = showToastMock.mock.calls.at(-1)!;
    expect(message).toBe("«lonely.jpg» in den Papierkorb verschoben");
    expect(tone).toBe("success");
    await act(async () => { options.action.onClick(); });
    await waitFor(() => expect(props.onRestored).toHaveBeenCalledWith(["lonely"]));
  });

  it("ein Protokollfoto ist hier nicht löschbar und verweist auf die Herkunft", async () => {
    mockApi();
    renderViewer(2);
    fireEvent.keyDown(window, { key: "Delete" });
    const dialog = await screen.findByRole("dialog", { name: "Hier nicht löschbar" });
    expect(dialog).toHaveTextContent("Dieses Foto gehört zu Lagerbericht");
    expect(screen.getByRole("link", { name: "Zur Herkunft: Protokoll ›" })).toHaveAttribute("href", "/protocols/p1");
    expect(screen.queryByRole("button", { name: "In den Papierkorb" })).toBeNull();
  });

  it("Vergleich: Vorschlag vorausgefüllt, gesperrte bleiben, Anwenden legt in den Papierkorb und markiert geprüft", async () => {
    mockApi((url) => (url === "/api/files/bulk-delete" ? { deleted_ids: ["blurry"], errors: [] } : null));
    const props = renderViewer(1);
    // Hinweis auf der Bühne und Karte in der Seitenleiste
    fireEvent.click(await screen.findByRole("button", { name: /2 ähnliche · Vergleichen/ }));
    const region = screen.getByRole("region", { name: "Vergleich" });
    expect(region).toHaveTextContent("2 behalten");
    expect(region).toHaveTextContent("1 in den Papierkorb");
    expect(screen.getByRole("button", { name: "«blurry.jpg» doch behalten" })).toHaveAttribute("aria-pressed", "true");
    expect(region).toHaveTextContent("Bleibt – nur über «Protokoll» löschbar");

    // Umschalten per Klick aufs Bild und zurück per Segment
    fireEvent.click(screen.getByRole("button", { name: "«blurry.jpg» doch behalten" }));
    expect(region).toHaveTextContent("3 behalten");
    expect(screen.getByRole("button", { name: "Als geprüft markieren" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Nur das beste behalten" }));
    fireEvent.click(screen.getByRole("button", { name: "1 in den Papierkorb" }));

    await waitFor(() => expect(props.onRemoved).toHaveBeenCalledWith(["blurry"], "best"));
    expect(JSON.parse(browserApiFetchMock.mock.calls.find(([url]) => url === "/api/files/bulk-delete")![1].body)).toEqual({ file_ids: ["blurry"] });
    expect(showToastMock.mock.calls.at(-1)![0]).toBe("1 Foto in den Papierkorb verschoben");
    // Gruppe gilt als geprüft: kein Hinweis mehr
    await waitFor(() => expect(screen.queryByRole("region", { name: "Vergleich" })).toBeNull());
    expect(screen.queryByRole("button", { name: /Vergleichen/ })).toBeNull();
  });

  it("Escape verlässt zuerst den Vergleich, dann die Ansicht", async () => {
    mockApi();
    const props = renderViewer(0);
    fireEvent.click((await screen.findAllByRole("button", { name: /Vergleichen/ }))[0]);
    expect(screen.getByRole("region", { name: "Vergleich" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("region", { name: "Vergleich" })).toBeNull());
    expect(props.onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(props.onClose).toHaveBeenCalled());
  });
});
