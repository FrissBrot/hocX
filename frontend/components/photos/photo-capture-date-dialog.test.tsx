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

import { MAX_CAPTURE_DATE_BULK, PhotoCaptureDateDialog, describeOffset } from "./photo-capture-date-dialog";

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

  it("verschiebt um Tage und Stunden und meldet übersprungene Bilder ohne Datum", async () => {
    confirmMock.mockResolvedValue(true);
    browserApiFetchMock.mockResolvedValue({ ...emptyResult, updated_ids: ["a", "b"], skipped_no_date_ids: ["c"] });
    renderDialog();
    fireEvent.click(screen.getByRole("tab", { name: "Verschieben" }));
    fireEvent.change(screen.getByLabelText("Tage"), { target: { value: "-1" } });
    fireEvent.change(screen.getByLabelText("Stunden"), { target: { value: "-2" } });
    fireEvent.click(screen.getByRole("button", { name: "Übernehmen" }));

    await waitFor(() => expect(lastPost()).toEqual({ file_ids: ["a", "b", "c"], mode: "shift", shift_days: -1, shift_hours: -2 }));
    expect(confirmMock.mock.calls[0][0].message).toContain("Das Aufnahmedatum von 3 Bildern wird um 1 Tag und 2 Stunden nach früher verschoben.");
    expect(confirmMock.mock.calls[0][0].message).toContain("Bilder ohne Aufnahmedatum werden übersprungen.");
    expect(confirmMock.mock.calls[0][0].message).toContain("auch in die Bilddateien geschrieben");
    expect(showToastMock).toHaveBeenCalledWith("1 Bild ohne Aufnahmedatum übersprungen.", "info");
  });

  it("verlangt beim Verschieben einen Versatz", () => {
    renderDialog();
    fireEvent.click(screen.getByRole("tab", { name: "Verschieben" }));
    expect(screen.getByRole("button", { name: "Übernehmen" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Stunden"), { target: { value: "1.5" } });
    expect(screen.getByRole("button", { name: "Übernehmen" })).toBeDisabled();
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

  it("sperrt mehr als 500 Bilder", () => {
    renderDialog(Array.from({ length: MAX_CAPTURE_DATE_BULK + 1 }, (_, index) => `id-${index}`));
    expect(screen.getByText("Bitte höchstens 500 Bilder auswählen.")).toBeInTheDocument();
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
  });
});
