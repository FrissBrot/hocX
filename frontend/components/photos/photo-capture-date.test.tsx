import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FileOverviewItem, StoredFileMetadata } from "@/types/api";

const browserApiFetchMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiBaseUrl: "",
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

import { UploadResultsModal, uploadResultsSummary } from "@/components/files/upload-results-modal";
import { PhotoDateGroups } from "./photo-date-groups";
import { PhotoViewer } from "./photo-viewer";
import { createTranslator } from "next-intl";
import deFiles from "@/messages/de/files.json";

function makeItem(overrides: Partial<FileOverviewItem> = {}): FileOverviewItem {
  const id = overrides.id ?? `file-${Math.random().toString(36).slice(2)}`;
  return {
    id, original_name: `${id}.jpg`, mime_type: "image/jpeg", file_size_bytes: 1000, created_at: "2026-07-10T08:02:00Z",
    source: "gallery_upload", is_image: true, content_url: `/c/${id}`, thumbnail_url: `/t/${id}`, tags_url: `/api/stored-files/${id}/tags`,
    metadata_url: `/api/stored-files/${id}/metadata`, ref_label: "", ref_date: null, ref_end_date: null, ref_href: null, tags: [],
    origin_tag: "Direkt hochgeladen", sharpness_score: null, exposure_score: null, face_quality_score: null, face_analyzed_at: null,
    width: 4, height: 3, group_date: "2026-07-10", context_label: null, live_video_url: null, albums: [], is_best: false,
    date_source: "exif", ...overrides,
  };
}

function metadata(overrides: Partial<StoredFileMetadata> = {}): StoredFileMetadata {
  return {
    id: "x", original_name: "x.jpg", mime_type: "image/jpeg", file_size_bytes: 1, created_at: "2026-07-10T08:02:00Z", checksum_sha256: null,
    source: "gallery_upload", ref_label: "", ref_date: null, tags: [], origin_tag: "Direkt hochgeladen", width: 4, height: 3,
    exif_taken_at: null, exif_camera: null, uploaded_by_name: null, estimated_taken_on: null, date_source: "upload",
    effective_date: "2026-07-10", gps: null, can_edit_capture_date: true, ...overrides,
  };
}

const groupProps = { grouped: true, selectedIds: new Set<string>(), onOpen: vi.fn(), onToggleSelect: vi.fn(), onToggleGroup: vi.fn() };

describe("Dezente Datumskennzeichnung in der Galerie", () => {
  beforeEach(() => {
    vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("zeigt bei echtem Aufnahmedatum keine Kennzeichnung", () => {
    render(<PhotoDateGroups items={[makeItem({ date_source: "exif" })]} {...groupProps} />);
    expect(screen.queryByRole("button", { name: /Aufnahmedatum/ })).not.toBeInTheDocument();
  });

  it("kennzeichnet ein geschätztes Datum mit zugänglichem Hinweis, auch per Tippen", () => {
    render(<PhotoDateGroups items={[makeItem({ date_source: "estimated", group_date: "1998-08-01" })]} {...groupProps} />);
    const marker = screen.getByRole("button", { name: "Geschätztes Aufnahmedatum" });
    expect(marker).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(marker); // Touch/Klick öffnet den Hinweis (mobil kein Hover nötig)
    expect(screen.getByRole("tooltip")).toHaveTextContent("Geschätztes Aufnahmedatum");
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("1998");
  });

  it("kennzeichnet den Uploaddatum-Fallback und zählt gemischte Tage", () => {
    render(<PhotoDateGroups items={[makeItem({ date_source: "upload" }), makeItem({ date_source: "exif" })]} {...groupProps} />);
    expect(screen.getByRole("button", { name: "Aufnahmedatum unbekannt – Uploaddatum wird verwendet. (1 von 2 Bildern)" })).toBeInTheDocument();
  });

  it("fügt den Kacheln keine Textzeilen hinzu", () => {
    const { container } = render(<PhotoDateGroups items={[makeItem({ date_source: "estimated" })]} {...groupProps} />);
    expect(within(container.querySelector(".photo-grid") as HTMLElement).queryByText(/Aufnahmedatum/)).not.toBeInTheDocument();
  });
});

describe("Bilddetails: drei getrennte Datumsarten", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    vi.stubGlobal("Image", vi.fn(function () { return { src: "", decode: () => Promise.resolve() }; }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("zeigt echtes Datum in Kamerazeit (ohne Zeitzonenverschiebung), Schätzung und Upload getrennt", async () => {
    browserApiFetchMock.mockResolvedValue(
      metadata({ exif_taken_at: "2023-07-14T10:30:00Z", exif_taken_offset: "+02:00", estimated_taken_on: "1999-01-01", date_source: "exif", gps: { latitude: -33.86882, longitude: -70.66933, altitude_m: 540, direction_deg: null, accuracy_m: null, timestamp: null, source: "server" } }),
    );
    render(<PhotoViewer items={[makeItem()]} index={0} onIndexChange={vi.fn()} onClose={vi.fn()} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} />);
    expect(await screen.findByText("14.07.2023, 10:30 (+02:00)")).toBeInTheDocument();
    expect(screen.getByText("Das echte Aufnahmedatum hat Vorrang.")).toBeInTheDocument();
    expect(screen.getByText("Hochgeladen")).toBeInTheDocument();
    expect(screen.getByText("-33.86882, -70.66933 · 540 m ü. M.")).toBeInTheDocument();
  });

  it("speichert, ändert und entfernt ein geschätztes Datum über den Bearbeitungsweg", async () => {
    const onCaptureDateSaved = vi.fn();
    browserApiFetchMock.mockImplementation((url: string, init?: { method?: string; body?: string }) => {
      if (init?.method === "PATCH") {
        const { estimated_taken_on } = JSON.parse(init.body ?? "{}");
        return Promise.resolve(metadata({ id: "x", estimated_taken_on, date_source: estimated_taken_on ? "estimated" : "upload", effective_date: estimated_taken_on ?? "2026-07-10" }));
      }
      return Promise.resolve(metadata({ id: "x" }));
    });
    const item = makeItem({ id: "x", date_source: "upload" });
    render(<PhotoViewer items={[item]} index={0} onIndexChange={vi.fn()} onClose={vi.fn()} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} onCaptureDateSaved={onCaptureDateSaved} />);
    expect(await screen.findByText("Unbekannt")).toBeInTheDocument();
    const input = document.querySelector(".photo-viewer-estimate input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "01.08.1998" } });
    fireEvent.blur(input);
    await waitFor(() => expect(onCaptureDateSaved).toHaveBeenCalledWith("x", expect.objectContaining({ estimated_taken_on: "1998-08-01" })));
    const patch = browserApiFetchMock.mock.calls.find(([, init]) => init?.method === "PATCH")!;
    expect(patch[0]).toBe("/api/stored-files/x/capture-date");

    fireEvent.click(await screen.findByRole("button", { name: "Entfernen" }));
    await waitFor(() => expect(onCaptureDateSaved).toHaveBeenLastCalledWith("x", expect.objectContaining({ estimated_taken_on: null })));
  });

  it("bietet ohne Schreibrecht keine Bearbeitung an", async () => {
    browserApiFetchMock.mockResolvedValue(metadata({ can_edit_capture_date: false, estimated_taken_on: "1999-05-05" }));
    render(<PhotoViewer items={[makeItem()]} index={0} onIndexChange={vi.fn()} onClose={vi.fn()} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} />);
    expect(await screen.findByText("05.05.1999")).toBeInTheDocument();
    expect(document.querySelector(".photo-viewer-estimate input")).toBeNull();
  });
});

describe("Upload-Ergebnisanzeige", () => {
  const t = createTranslator({ locale: "de", messages: { files: deFiles }, namespace: "files" });

  it("fasst zusammen, ohne Dateien doppelt zu zählen", () => {
    const results = [
      ...Array.from({ length: 12 }, (_, i) => ({ name: `u${i}`, status: "uploaded" as const })),
      ...Array.from({ length: 8 }, (_, i) => ({ name: `s${i}`, status: "skipped" as const })),
      ...Array.from({ length: 4 }, (_, i) => ({ name: `m${i}`, status: "metadata_updated" as const, applied: ["gps" as const] })),
    ];
    expect(uploadResultsSummary(results, t, "images")).toBe("24 Bilder verarbeitet: 12 hochgeladen, 8 übersprungen, 4 übersprungen und Metadaten ergänzt.");
  });

  it("zeigt je Datei Hochgeladen, Übersprungen, Übersprungen · Metadaten ergänzt und Fehlgeschlagen", () => {
    render(
      <UploadResultsModal
        noun="images"
        onClose={vi.fn()}
        results={[
          { name: "neu.jpg", status: "uploaded" },
          { name: "alt.jpg", status: "skipped" },
          { name: "ergänzt.jpg", status: "metadata_updated", applied: ["estimated_taken_on", "gps"] },
          { name: "kaputt.jpg", status: "failed", message: "kein unterstütztes Bildformat" },
        ]}
      />,
    );
    expect(screen.getByText("Hochgeladen")).toBeInTheDocument();
    expect(screen.getByText("Übersprungen")).toBeInTheDocument();
    expect(screen.getByText("Übersprungen · Metadaten ergänzt")).toBeInTheDocument();
    expect(screen.getByText("Ergänzt: geschätztes Aufnahmedatum, Standort (GPS)")).toBeInTheDocument();
    expect(screen.getByText("Fehlgeschlagen")).toBeInTheDocument();
    expect(screen.getByText("kein unterstütztes Bildformat")).toBeInTheDocument();
  });
});
