import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FileOverviewItem, StoredFileMetadata } from "@/types/api";

const browserApiFetchMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiBaseUrl: "",
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn() }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));

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

describe("Datumskennzeichnung in der Galerie", () => {
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
    expect(marker).toHaveTextContent("Geschätztes Datum"); // ohne Hover lesbar
    fireEvent.click(marker); // Touch/Klick öffnet den Hinweis (mobil kein Hover nötig)
    expect(screen.getByRole("tooltip")).toHaveTextContent("Kein Aufnahmedatum in der Datei – beim Hochladen geschätzt.");
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("1998");
  });

  it("kennzeichnet den Uploaddatum-Fallback und zählt gemischte Tage", () => {
    render(<PhotoDateGroups items={[makeItem({ date_source: "upload" }), makeItem({ date_source: "exif" })]} {...groupProps} />);
    expect(screen.getByRole("button", { name: "Aufnahmedatum unbekannt – Uploaddatum wird verwendet. (1 von 2 Bildern)" })).toHaveTextContent("Uploaddatum · 1/2");
  });

  it("fügt den Kacheln keine Textzeilen hinzu", () => {
    const { container } = render(<PhotoDateGroups items={[makeItem({ date_source: "estimated" })]} {...groupProps} />);
    expect(within(container.querySelector(".photo-grid") as HTMLElement).queryByText(/Aufnahmedatum/)).not.toBeInTheDocument();
  });
});

function renderViewer(item = makeItem({ id: "x" }), extra: Record<string, unknown> = {}) {
  return render(<PhotoViewer items={[item]} index={0} onIndexChange={vi.fn()} onClose={vi.fn()} onToggleBest={vi.fn()} onTagsSaved={vi.fn()} {...extra} />);
}

/** Antwortet auf die Metadaten-URL und die Gruppenabfrage; `handler` für alles andere. */
function api(meta: () => StoredFileMetadata, handler?: (url: string, init?: { method?: string; body?: string }) => unknown) {
  browserApiFetchMock.mockImplementation((url: string, init?: { method?: string; body?: string }) => {
    if (url.startsWith("/api/files/similarity-groups")) return Promise.resolve({ status: "ready", computed_at: null, groups: [] });
    if (!init?.method || init.method === "GET") return Promise.resolve(meta());
    return Promise.resolve(handler?.(url, init) ?? null);
  });
}

describe("Foto-Ansicht: Aufnahmedatum", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    vi.stubGlobal("Image", vi.fn(function () { return { src: "", decode: () => Promise.resolve() }; }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("zeigt echtes Datum in Kamerazeit (ohne Zeitzonenverschiebung), Upload und Standort", async () => {
    api(() => metadata({ exif_taken_at: "2023-07-14T10:30:00Z", exif_taken_offset: "+02:00", estimated_taken_on: "1999-01-01", date_source: "exif", uploaded_by_name: "Lara Meier", gps: { latitude: -33.86882, longitude: -70.66933, altitude_m: 540, direction_deg: null, accuracy_m: null, timestamp: null, source: "server" } }));
    renderViewer();
    expect(await screen.findByText("14.07.2023, 10:30 (+02:00)")).toBeInTheDocument();
    expect(screen.getByText("Aus der Kamera (EXIF)")).toBeInTheDocument();
    expect(screen.queryByText("Geschätzt")).toBeNull();
    expect(screen.getByText(/Lara Meier/)).toBeInTheDocument();
    expect(screen.getByText("-33.86882, -70.66933 · 540 m ü. M.")).toBeInTheDocument();
  });

  it("korrigiert ein falsches EXIF-Datum erst nach der zweiten Bestätigung", async () => {
    const onCaptureDateSaved = vi.fn();
    const exif = { exif_taken_at: "2001-01-01T00:05:00Z", date_source: "exif" as const, effective_date: "2001-01-01" };
    api(() => metadata(exif), (_url, init) => {
      const { corrected_date, corrected_time } = JSON.parse(init?.body ?? "{}");
      return metadata({ ...exif, capture_corrected_at: `${corrected_date}T${corrected_time}:00Z`, capture_corrected_has_time: true, date_source: "corrected", effective_date: corrected_date, capture_file_state: "pending" });
    });
    renderViewer(makeItem({ id: "x" }), { onCaptureDateSaved });
    fireEvent.click(await screen.findByRole("button", { name: "Ändern" }));
    const date = screen.getByLabelText("Datum") as HTMLInputElement;
    expect(date.value).toBe("01.01.2001"); // vorbelegt mit dem gültigen Datum
    fireEvent.change(date, { target: { value: "14.07.2023" } });
    fireEvent.blur(date);
    const time = screen.getByLabelText("Uhrzeit (optional)");
    fireEvent.change(time, { target: { value: "10:30" } });
    fireEvent.blur(time);
    fireEvent.click(screen.getByRole("button", { name: "Übernehmen" }));

    // Erster Klick: nur der Hinweis, noch nichts gespeichert.
    expect(screen.getByText("Datum auf 14.07.2023, 10:30 setzen?")).toBeInTheDocument();
    expect(screen.getByText(/im Zeitstrahl neu einsortiert/)).toHaveTextContent("bleibt in hocX gespeichert");
    expect(browserApiFetchMock.mock.calls.some(([, init]) => init?.method === "PATCH")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Bestätigen" }));

    await waitFor(() => expect(onCaptureDateSaved).toHaveBeenCalledWith("x", expect.objectContaining({ date_source: "corrected" })));
    const patch = browserApiFetchMock.mock.calls.find(([, init]) => init?.method === "PATCH")!;
    expect(patch[0]).toBe("/api/stored-files/x/capture-correction");
    expect(JSON.parse(patch[1].body)).toEqual({ corrected_date: "2023-07-14", corrected_time: "10:30" });
    expect(await screen.findByText("Korrigiert")).toBeInTheDocument();
    expect(screen.getByText("14.07.2023, 10:30")).toBeInTheDocument();
    expect(screen.getByText("Ursprünglich (EXIF): 01.01.2001, 00:05")).toBeInTheDocument();
    expect(screen.getByText("Die Bilddatei wird im Hintergrund aktualisiert.")).toBeInTheDocument();
  });

  it("verschiebt um Tage und Stunden mit Vorschau über den Mehrfach-Endpunkt", async () => {
    let shifted = false;
    const exif = { exif_taken_at: "2001-01-01T00:05:00Z", date_source: "exif" as const };
    api(
      () => metadata(shifted ? { ...exif, capture_corrected_at: "2000-12-31T02:05:00Z", capture_corrected_has_time: true, date_source: "corrected" } : exif),
      () => {
        shifted = true;
        return { updated_ids: ["x"], unchanged_ids: [], skipped_no_date_ids: [], invalid_ids: [], not_found_ids: [] };
      }
    );
    renderViewer();
    fireEvent.click(await screen.findByRole("button", { name: "Ändern" }));
    fireEvent.click(screen.getByRole("radio", { name: "Verschieben" }));
    fireEvent.change(screen.getByLabelText("Tage"), { target: { value: "-1" } });
    fireEvent.change(screen.getByLabelText("Stunden"), { target: { value: "2" } });
    expect(screen.getByText("Neu: 31.12.2000, 02:05")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Übernehmen" }));
    expect(screen.getByText("Datum auf 31.12.2000, 02:05 verschieben?")).toBeInTheDocument();
    // Eingabe ändern verlangt eine neue Bestätigung
    fireEvent.change(screen.getByLabelText("Stunden"), { target: { value: "3" } });
    expect(screen.queryByRole("button", { name: "Bestätigen" })).toBeNull();
    fireEvent.change(screen.getByLabelText("Stunden"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Übernehmen" }));
    fireEvent.click(screen.getByRole("button", { name: "Bestätigen" }));
    await waitFor(() => expect(screen.getByText("Korrigiert")).toBeInTheDocument());
    const post = browserApiFetchMock.mock.calls.find(([url]) => url === "/api/files/bulk-capture-date")!;
    expect(JSON.parse(post[1].body)).toEqual({ file_ids: ["x"], mode: "shift", shift_days: -1, shift_hours: 2 });
  });

  it("Verschieben ist ohne Aufnahmedatum nicht möglich", async () => {
    api(() => metadata({ date_source: "upload" }));
    renderViewer();
    expect(await screen.findByText("Datum setzen, damit das Foto richtig einsortiert wird. Bis dahin gilt das Uploaddatum.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ändern" }));
    expect(screen.getByRole("radio", { name: "Verschieben" })).toBeDisabled();
  });

  it("setzt eine Korrektur zurück, mit Hinweis auf das wieder gültige Datum", async () => {
    const corrected = { exif_taken_at: "2001-01-01T00:05:00Z", capture_corrected_at: "2023-07-14T12:00:00Z", capture_corrected_has_time: false, date_source: "corrected" as const };
    api(() => metadata(corrected), () => metadata({ exif_taken_at: corrected.exif_taken_at, date_source: "exif" }));
    renderViewer();
    expect(await screen.findByText("14.07.2023")).toBeInTheDocument(); // ohne Uhrzeit nur der Tag
    fireEvent.click(screen.getByRole("button", { name: "Ändern" }));
    fireEvent.click(screen.getByRole("radio", { name: "Zurücksetzen" }));
    expect(screen.getByText("Die Korrektur wird entfernt – es gilt wieder das EXIF-Datum 01.01.2001, 00:05.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Übernehmen" }));
    expect(screen.getByText("Korrektur entfernen?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Bestätigen" }));
    await waitFor(() => expect(browserApiFetchMock.mock.calls.some(([, init]) => init?.method === "PATCH")).toBe(true));
    const patch = browserApiFetchMock.mock.calls.find(([, init]) => init?.method === "PATCH")!;
    expect(JSON.parse(patch[1].body)).toEqual({ corrected_date: null });
    expect(await screen.findByText("Aus der Kamera (EXIF)")).toBeInTheDocument();
  });

  it("zeigt, ob die Datei das korrigierte Datum schon enthält oder das Format es nicht kann", async () => {
    const corrected = { exif_taken_at: null, capture_corrected_at: "2023-07-14T12:00:00Z", capture_corrected_has_time: false, date_source: "corrected" as const };
    api(() => metadata({ ...corrected, capture_file_state: "written" }));
    const { unmount } = renderViewer();
    expect(await screen.findByText("Das Datum ist auch in der Bilddatei gespeichert.")).toBeInTheDocument();
    expect(screen.getByText("Das Bild hatte ursprünglich kein Aufnahmedatum.")).toBeInTheDocument();
    unmount();
    api(() => metadata({ ...corrected, capture_file_state: "unsupported" }));
    renderViewer();
    expect(await screen.findByText("Dieses Dateiformat kann das Datum nicht aufnehmen. Die Korrektur gilt nur in hocX.")).toBeInTheDocument();
  });

  it("bietet ohne Schreibrecht (z. B. Partner-Foto) keine Änderung an", async () => {
    api(() => metadata({ can_edit_capture_date: false, estimated_taken_on: "1999-05-05", date_source: "estimated" }));
    renderViewer();
    expect(await screen.findByText("05.05.1999")).toBeInTheDocument();
    expect(screen.getByText("Geschätzt")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ändern" })).toBeNull();
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
