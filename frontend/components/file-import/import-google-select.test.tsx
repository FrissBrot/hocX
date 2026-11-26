import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
const showToast = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiBaseUrl: "",
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => showToast }));

import type { ImportJob } from "@/lib/files/file-import";

import { GoogleDriveSelect, GooglePhotosSelect } from "./import-google-select";

const job = { id: "0194f1c2-1111-7aaa-8bbb-123456789abc", source: "google_photos", status: "draft" } as unknown as ImportJob;

describe("Google-Auswahl im Wizard", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToast.mockReset();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("Google Drive: holt ein Ticket und wechselt auf die Picker-Origin (Ticket nur im Fragment)", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { href: "http://localhost/files/import", pathname: "/files/import", search: "", hash: "", assign });
    browserApiFetchMock.mockResolvedValue({ picker_url: "https://picker.hocx.example/google-picker#ticket=abc" });
    render(<GoogleDriveSelect job={job} busy={false} onCancel={vi.fn()} errorText={() => "Fehler"} />);
    fireEvent.click(screen.getByRole("button", { name: "In Google Drive auswählen" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://picker.hocx.example/google-picker#ticket=abc"));
    expect(browserApiFetchMock).toHaveBeenCalledWith(`/api/cloud-import/jobs/${job.id}/google-drive/picker-ticket`, { method: "POST" });
  });

  it("Google Drive: Fehler beim Ticket erscheint als Meldung, Knopf wieder bedienbar", async () => {
    browserApiFetchMock.mockRejectedValue(new Error("x"));
    render(<GoogleDriveSelect job={job} busy={false} onCancel={vi.fn()} errorText={() => "Fehler"} />);
    const choose = screen.getByRole("button", { name: "In Google Drive auswählen" });
    fireEvent.click(choose);
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Fehler", "error"));
    expect(choose).toBeEnabled();
  });

  it("Google Fotos: öffnet die Auswahl im neuen Fenster, fragt ab und meldet den Auftrag weiter", async () => {
    const popup = { opener: {}, location: { href: "" }, close: vi.fn() };
    vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
    const listing = { ...job, status: "listing" };
    let polls = 0;
    browserApiFetchMock.mockImplementation(async (path: string) => {
      if (path.endsWith("/google-photos/session")) return { picker_uri: "https://photos.google.com/picker/s1", poll_seconds: 2, timeout_seconds: 600 };
      if (path.endsWith("/session/poll")) {
        polls += 1;
        return polls < 2 ? { done: false, poll_seconds: 2, job } : { done: true, poll_seconds: 2, job: listing };
      }
      throw new Error(path);
    });
    const onJob = vi.fn();
    render(<GooglePhotosSelect job={job} onJob={onJob} onCancel={vi.fn()} errorText={() => "x"} />);
    const start = screen.getByRole("button", { name: "In Google Fotos auswählen" });
    start.focus();
    fireEvent.click(start);
    await waitFor(() => expect(popup.location.href).toBe("https://photos.google.com/picker/s1/autoclose"));
    expect(popup.opener).toBeNull();
    // Ersatzlink, falls kein Fenster aufging (ohne Opener/Referrer)
    const fallback = await screen.findByRole("link", { name: "Google Fotos öffnen" });
    expect(fallback.getAttribute("rel")).toBe("noopener noreferrer");
    await waitFor(() => expect(onJob).toHaveBeenCalledWith(listing), { timeout: 8000 });
  }, 12000);

  it("Google Fotos: abgelaufene Sitzung wird gemeldet und lässt sich neu starten", async () => {
    vi.spyOn(window, "open").mockReturnValue(null);
    browserApiFetchMock.mockImplementation(async (path: string) => {
      if (path.endsWith("/google-photos/session")) return { picker_uri: "https://photos.google.com/picker/s2", poll_seconds: 2, timeout_seconds: null };
      throw Object.assign(new Error("expired"), { detail: { code: "photos_session_expired" } });
    });
    render(<GooglePhotosSelect job={job} onJob={vi.fn()} onCancel={vi.fn()} errorText={() => "x"} />);
    fireEvent.click(screen.getByRole("button", { name: "In Google Fotos auswählen" }));
    expect(await screen.findByText(/ist abgelaufen/, {}, { timeout: 6000 })).toBeTruthy();
    expect(screen.getByRole("button", { name: "In Google Fotos auswählen" })).toBeTruthy();
  }, 10000);
});
