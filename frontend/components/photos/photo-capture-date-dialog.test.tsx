import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import dePhotos from "@/messages/de/photos.json";

const browserApiFetchMock = vi.fn();
const showToastMock = vi.fn();
const confirmMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiBaseUrl: "",
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => showToastMock }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => confirmMock }));

import { MAX_CAPTURE_DATE_SELECTION, PhotoCaptureDateDialog, cameraSeconds, describeOffset, noTimeShiftNote, splitOffset, wholeShiftDays } from "./photo-capture-date-dialog";

const emptyResult = { updated_ids: [], unchanged_ids: [], skipped_no_date_ids: [], invalid_ids: [], not_found_ids: [] };

function renderDialog(fileIds = ["a", "b", "c"]) {
  const onDone = vi.fn();
  const onClose = vi.fn();
  render(<PhotoCaptureDateDialog open fileIds={fileIds} onClose={onClose} onDone={onDone} />);
  return { onDone, onClose };
}

function lastPost() {
  const call = browserApiFetchMock.mock.calls.find(([url]) => url === "/api/files/bulk-capture-date");
  return call ? JSON.parse(call[1].body) : null;
}

describe("PhotoCaptureDateDialog (Mehrfachauswahl «Aufnahmedatum ändern»)", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
    confirmMock.mockReset();
  });

  it("setzt alle auf dasselbe Datum - erst nach Bestätigung mit Hinweis und Anzahl", async () => {
    confirmMock.mockResolvedValue(true);
    browserApiFetchMock.mockResolvedValue({ ...emptyResult, updated_ids: ["a", "b"], not_found_ids: ["c"] });
    const { onDone, onClose } = renderDialog();
    expect(screen.getByText("Gilt für 3 ausgewählte Bilder.")).toBeInTheDocument();
    const apply = screen.getByRole("button", { name: "Übernehmen" });
    expect(apply).toBeDisabled(); // Datum fehlt

    const date = screen.getByLabelText("Datum");
    fireEvent.change(date, { target: { value: "01.08.2024" } });
    fireEvent.blur(date);
    const time = screen.getByLabelText("Uhrzeit (optional)");
    fireEvent.change(time, { target: { value: "1430" } });
    fireEvent.blur(time);
    fireEvent.click(apply);

    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    const { message, title } = confirmMock.mock.calls[0][0];
    expect(title).toBe("Aufnahmedatum ändern?");
    expect(message).toContain("Das Aufnahmedatum von 3 Bildern wird auf 01.08.2024, 14:30 gesetzt.");
    expect(message).toContain("Reihenfolge im Zeitstrahl");
    expect(message).toContain("Zuordnung zu Terminen");
    expect(message).toContain("Das neue Datum wird auch in die Bilddateien geschrieben, Downloads und Originale enthalten es also.");
    expect(message).toContain("Das ursprüngliche Aufnahmedatum bleibt in hocX gespeichert und lässt sich jederzeit wiederherstellen.");

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(lastPost()).toEqual({ file_ids: ["a", "b", "c"], mode: "set", corrected_date: "2024-08-01", corrected_time: "14:30" });
    expect(showToastMock).toHaveBeenCalledWith("Aufnahmedatum von 2 Bildern geändert.", "success");
    expect(showToastMock).toHaveBeenCalledWith(expect.stringContaining("1 Bild nicht gefunden oder nicht änderbar"), "info");
    expect(onClose).toHaveBeenCalled();
  });

  it("öffnet aus dem Upload-Vorgang im Modus «Datum», hängt den Vorgang an und meldet Dokumente", async () => {
    confirmMock.mockResolvedValue(true);
    browserApiFetchMock.mockResolvedValue({ ...emptyResult, updated_ids: ["a"], skipped_not_image_ids: ["d"], batch_id: "batch-1" });
    const onDone = vi.fn();
    render(<PhotoCaptureDateDialog open fileIds={["a", "d"]} uploadJobId="job-1" initialMode="shift" onClose={vi.fn()} onDone={onDone} />);
    // Modus aus dem Aufrufer (hier «Verschieben»), danach auf «Datum» wechseln
    expect(screen.getByLabelText("Tage")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Auf Datum setzen" }));
    const date = screen.getByLabelText("Datum");
    fireEvent.change(date, { target: { value: "02.05.2026" } });
    fireEvent.blur(date);
    fireEvent.click(screen.getByRole("button", { name: "Übernehmen" }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(lastPost()).toEqual({ file_ids: ["a", "d"], mode: "set", corrected_date: "2026-05-02", corrected_time: null, upload_job_id: "job-1" });
    expect(showToastMock).toHaveBeenCalledWith("Aufnahmedatum von 1 Bild geändert.", "success", expect.objectContaining({ action: expect.any(Object) }));
    expect(showToastMock).toHaveBeenCalledWith(expect.stringContaining("1 Dokument hat kein Aufnahmedatum und bleibt unverändert."), "info");
  });

  it("schickt ohne Bestätigung nichts ab", async () => {
    confirmMock.mockResolvedValue(false);
    renderDialog();
    const date = screen.getByLabelText("Datum");
    fireEvent.change(date, { target: { value: "01.08.2024" } });
    fireEvent.blur(date);
    fireEvent.click(screen.getByRole("button", { name: "Übernehmen" }));
    await waitFor(() => expect(confirmMock).toHaveBeenCalled());
    expect(browserApiFetchMock).not.toHaveBeenCalled();
  });

  it("verschiebt früher um Tage, Stunden und Minuten und meldet übersprungene Bilder ohne Datum", async () => {
    confirmMock.mockResolvedValue(true);
    browserApiFetchMock.mockResolvedValue({ ...emptyResult, updated_ids: ["a", "b"], skipped_no_date_ids: ["c"], batch_id: "batch-1" });
    renderDialog();
    fireEvent.click(screen.getByRole("tab", { name: "Verschieben" }));
    fireEvent.click(screen.getByRole("tab", { name: "Früher" }));
    fireEvent.change(screen.getByLabelText("Tage"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Stunden"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Minuten"), { target: { value: "15" } });
    fireEvent.click(screen.getByRole("button", { name: "Übernehmen" }));

    await waitFor(() => expect(lastPost()).toEqual({ file_ids: ["a", "b", "c"], mode: "shift", shift_days: -1, shift_hours: -2, shift_minutes: -15 }));
    expect(confirmMock.mock.calls[0][0].message).toContain("Das Aufnahmedatum von 3 Bildern wird um 1 Tag, 2 Stunden und 15 Minuten nach früher verschoben.");
    expect(confirmMock.mock.calls[0][0].message).toContain("Bilder ohne Aufnahmedatum werden übersprungen.");
    expect(showToastMock).toHaveBeenCalledWith("1 Bild ohne Aufnahmedatum übersprungen.", "info");
    // «Rückgängig» im Erfolgs-Toast nimmt die ganze Korrektur zurück
    const success = showToastMock.mock.calls.find(([text]) => text === "Aufnahmedatum von 2 Bildern geändert.");
    expect(success?.[2]?.action?.label).toBe("Rückgängig");
    browserApiFetchMock.mockResolvedValue({ restored_ids: ["a", "b"], conflict_ids: [], not_found_ids: [] });
    success?.[2]?.action?.onClick();
    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalledWith("/api/capture-changes/batch-1/undo", { method: "POST" }));
  });

  it("weist bei Stunden darauf hin, dass bei Bildern ohne Uhrzeit nur ganze Tage wirken, und meldet sie", async () => {
    confirmMock.mockResolvedValue(true);
    browserApiFetchMock.mockResolvedValue({ ...emptyResult, updated_ids: ["a"], no_time_unchanged_ids: ["b", "c"] });
    renderDialog();
    fireEvent.click(screen.getByRole("tab", { name: "Verschieben" }));
    fireEvent.change(screen.getByLabelText("Tage"), { target: { value: "2" } });
    expect(screen.queryByText(/Bilder ohne Uhrzeit/)).not.toBeInTheDocument(); // reine Tage wirken überall
    fireEvent.change(screen.getByLabelText("Tage"), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("tab", { name: "Früher" }));
    fireEvent.change(screen.getByLabelText("Stunden"), { target: { value: "13" } });
    expect(screen.getByText("Bilder ohne Uhrzeit bleiben unverändert: bei ihnen wirken nur ganze Tage.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Übernehmen" }));

    await waitFor(() => expect(lastPost()).toEqual({ file_ids: ["a", "b", "c"], mode: "shift", shift_days: 0, shift_hours: -13 }));
    expect(confirmMock.mock.calls[0][0].message).toContain("Bilder ohne Uhrzeit bleiben unverändert");
    expect(showToastMock).toHaveBeenCalledWith("2 Bilder unverändert – keine Uhrzeit.", "info");
  });

  it("meldet Bilder ohne Uhrzeit, die nur um ganze Tage verschoben wurden", async () => {
    confirmMock.mockResolvedValue(true);
    browserApiFetchMock.mockResolvedValue({ ...emptyResult, updated_ids: ["a", "b"], date_only_ids: ["b"] });
    renderDialog(["a", "b"]);
    fireEvent.click(screen.getByRole("tab", { name: "Verschieben" }));
    fireEvent.click(screen.getByRole("tab", { name: "Früher" }));
    fireEvent.change(screen.getByLabelText("Tage"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Stunden"), { target: { value: "5" } });
    expect(screen.getByText("Bilder ohne Uhrzeit werden nur um 1 Tag verschoben: bei ihnen wirken nur ganze Tage.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Übernehmen" }));
    await waitFor(() => expect(showToastMock).toHaveBeenCalledWith("1 Bild ohne Uhrzeit nur um ganze Tage verschoben.", "info"));
  });

  it("verlangt beim Verschieben einen Versatz und nur nicht negative Ganzzahlen", () => {
    renderDialog();
    fireEvent.click(screen.getByRole("tab", { name: "Verschieben" }));
    expect(screen.getByRole("button", { name: "Übernehmen" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Stunden"), { target: { value: "1.5" } });
    expect(screen.getByRole("button", { name: "Übernehmen" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Stunden"), { target: { value: "-1" } });
    expect(screen.getByRole("button", { name: "Übernehmen" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Stunden"), { target: { value: "1" } });
    expect(screen.getByRole("button", { name: "Übernehmen" })).toBeEnabled();
  });

  it("zeigt die Vorschau des Servers und stückelt grosse Auswahlen mit derselben Korrektur", async () => {
    const ids = Array.from({ length: 501 }, (_, index) => `id-${index}`);
    browserApiFetchMock.mockImplementation((url: string, init: { body: string }) => {
      const body = JSON.parse(init.body);
      if (url === "/api/files/bulk-capture-date/preview") {
        return Promise.resolve({
          will_change: body.file_ids.length, unchanged: 0, no_date: 0, date_only_unchanged: 0, date_only_changed: 0, invalid: 0,
          not_found: 0, no_date_ids: [], samples: [], day_changes: 2, event_changes: 0, event_transitions: [],
        });
      }
      return Promise.resolve({ ...emptyResult, updated_ids: body.file_ids, batch_id: "b-7" });
    });
    confirmMock.mockResolvedValue(true);
    renderDialog(ids);
    fireEvent.click(screen.getByRole("tab", { name: "Verschieben" }));
    fireEvent.change(screen.getByLabelText("Minuten"), { target: { value: "75" } });
    fireEvent.click(screen.getByRole("button", { name: "Vorschau" }));
    expect(await screen.findByText("501 Bilder werden geändert.")).toBeInTheDocument();
    expect(screen.getByText("4 Bilder wechseln den Kalendertag.")).toBeInTheDocument(); // je Stück 2
    fireEvent.click(screen.getByRole("button", { name: "Übernehmen" }));
    await waitFor(() => expect(showToastMock).toHaveBeenCalledWith("Aufnahmedatum von 501 Bildern geändert.", "success", expect.anything()));
    const posts = browserApiFetchMock.mock.calls.filter(([url]) => url === "/api/files/bulk-capture-date").map(([, init]) => JSON.parse(init.body));
    expect(posts.map((post) => post.file_ids.length)).toEqual([500, 1]);
    expect(posts[0].batch_id).toBeUndefined();
    expect(posts[1].batch_id).toBe("b-7");
    expect(posts[0].shift_minutes).toBe(15);
    expect(posts[0].shift_hours).toBe(1);
  });

  it("stellt das Original wieder her", async () => {
    confirmMock.mockResolvedValue(true);
    browserApiFetchMock.mockResolvedValue({ ...emptyResult, updated_ids: ["a"], unchanged_ids: ["b"] });
    renderDialog(["a", "b"]);
    fireEvent.click(screen.getByRole("tab", { name: "Original wiederherstellen" }));
    fireEvent.click(screen.getByRole("button", { name: "Übernehmen" }));
    await waitFor(() => expect(lastPost()).toEqual({ file_ids: ["a", "b"], mode: "reset" }));
    expect(confirmMock.mock.calls[0][0].message).toContain("Bei 2 Bildern wird die Korrektur entfernt");
    expect(confirmMock.mock.calls[0][0].message).toContain("Auch die Bilddateien bekommen ihr ursprüngliches Datum zurück.");
  });

  it("sperrt mehr als 10 000 Bilder", () => {
    renderDialog(Array.from({ length: MAX_CAPTURE_DATE_SELECTION + 1 }, (_, index) => `id-${index}`));
    expect(screen.getByText(/Bitte höchstens 10.000 Bilder auswählen/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Original wiederherstellen" }));
    expect(screen.getByRole("button", { name: "Übernehmen" })).toBeDisabled();
  });

  it("zeigt Fehler aus dem Backend", async () => {
    confirmMock.mockResolvedValue(true);
    browserApiFetchMock.mockRejectedValue(new Error("Bitte 1 bis 500 Bilder auswählen"));
    renderDialog();
    fireEvent.click(screen.getByRole("tab", { name: "Original wiederherstellen" }));
    fireEvent.click(screen.getByRole("button", { name: "Übernehmen" }));
    await waitFor(() => expect(showToastMock).toHaveBeenCalledWith("Bitte 1 bis 500 Bilder auswählen", "error"));
  });
});

describe("describeOffset", () => {
  const t = createTranslator({ locale: "de", messages: { photos: dePhotos }, namespace: "photos.captureCorrection" });

  it("verrechnet gemischte Vorzeichen und beschreibt die Richtung", () => {
    expect(describeOffset(1, -2, t)).toEqual({ offset: "22 Stunden", direction: "later" });
    expect(describeOffset(-2, 0, t)).toEqual({ offset: "2 Tage", direction: "earlier" });
    expect(describeOffset(0, 25, t)).toEqual({ offset: "1 Tag und 1 Stunde", direction: "later" });
    expect(describeOffset(0, -1, t, -15)).toEqual({ offset: "1 Stunde und 15 Minuten", direction: "earlier" });
  });

  it("zerlegt Sekunden des Referenzfoto-Modus mit einheitlichem Vorzeichen", () => {
    expect(splitOffset(-(3600 + 15 * 60 + 7))).toEqual({ days: 0, hours: -1, minutes: -15, seconds: -7 });
    expect(splitOffset(86_400 + 60)).toEqual({ days: 1, hours: 0, minutes: 1, seconds: 0 });
  });

  it("liest die Kamerazeit aus der Korrektur bzw. dem EXIF-Datum", () => {
    expect(cameraSeconds({ capture_corrected_at: null, exif_taken_at: "2026-05-02T10:00:30+00:00" })).toBe(Date.UTC(2026, 4, 2, 10, 0, 30) / 1000);
    expect(cameraSeconds({ capture_corrected_at: "2026-05-02T12:00:00+00:00", capture_corrected_has_time: false, exif_taken_at: null })).toBeNull();
  });
});

describe("wholeShiftDays / noTimeShiftNote (wie image_metadata_service.whole_shift_days)", () => {
  const t = createTranslator({ locale: "de", messages: { photos: dePhotos }, namespace: "photos.captureCorrection" });

  it("rundet den Gesamtversatz gegen null auf ganze Tage", () => {
    expect(wholeShiftDays(0, -13)).toBe(0);
    expect(wholeShiftDays(0, 13)).toBe(0);
    expect(wholeShiftDays(1, -2)).toBe(0);
    expect(wholeShiftDays(0, -30)).toBe(-1);
    expect(wholeShiftDays(-2, -5)).toBe(-2);
    expect(wholeShiftDays(3, 0)).toBe(3);
  });

  it("hat nur bei Stundenanteil einen Hinweis", () => {
    expect(noTimeShiftNote(2, 0, t)).toBeNull();
    expect(noTimeShiftNote(0, 48, t)).toBeNull();
    expect(noTimeShiftNote(0, -13, t)).toContain("bleiben unverändert");
    expect(noTimeShiftNote(3, 4, t)).toContain("nur um 3 Tage");
  });
});
