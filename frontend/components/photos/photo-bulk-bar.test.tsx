import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

import { PhotoBulkBar } from "./photo-bulk-bar";

describe("PhotoBulkBar toggleBest", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
    confirmMock.mockReset();
    browserApiFetchMock.mockImplementation((url: string) => {
      if (url === "/api/files/albums") return Promise.resolve([]);
      return Promise.resolve(null);
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("downloads the selected photos via the export endpoint with their filenames", async () => {
    const blob = new Blob(["photo"]);
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, blob: async () => blob });
    const createUrl = vi.fn().mockReturnValue("blob:photo");
    const NativeURL = URL;
    vi.stubGlobal("URL", class extends NativeURL {
      static createObjectURL = createUrl;
      static revokeObjectURL = vi.fn();
    });
    vi.stubGlobal("fetch", fetchMock);
    const downloads: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { downloads.push(this.download); });
    render(<PhotoBulkBar selectedIds={["a", "b"]} selectedItems={[{ id: "a", original_name: "a.jpg", content_url: "/a/content" }, { id: "b", original_name: "b.jpg", content_url: "/b/content" }]} tagSuggestions={[]} onClearSelection={() => {}} onDone={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Herunterladen" }));
    await waitFor(() => expect(downloads).toEqual(["a.jpg", "b.jpg"]));
    // Export-Endpunkt (geschätztes Datum in der Kopie), nie die gespeicherte Datei selbst.
    expect(fetchMock).toHaveBeenCalledWith("/api/stored-files/a/download?part=image", { credentials: "include" });
    expect(fetchMock).toHaveBeenCalledWith("/api/stored-files/b/download?part=image", { credentials: "include" });
    expect(createUrl).toHaveBeenCalledWith(blob);
  });

  it("does not claim success when every selected photo fails (audit fix, 2026-09-17)", async () => {
    browserApiFetchMock.mockImplementation((url: string) => {
      if (url === "/api/files/albums") return Promise.resolve([]);
      if (url.endsWith("/best")) return Promise.reject(new Error("kein Album"));
      return Promise.resolve(null);
    });
    const onDone = vi.fn();

    render(<PhotoBulkBar selectedIds={["a", "b"]} tagSuggestions={[]} onClearSelection={() => {}} onDone={onDone} />);

    fireEvent.click(screen.getByRole("button", { name: "Best-of", exact: true }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "★ Best-of" }));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    const messages = showToastMock.mock.calls.map(([message]) => message);
    expect(messages).toContain("2 Foto(s) gehören zu keinem Album - Best-of nicht möglich.");
    expect(messages).not.toContain("Zu Best-of hinzugefügt.");
  });

  it("shows success when at least one selected photo succeeds", async () => {
    browserApiFetchMock.mockImplementation((url: string) => {
      if (url === "/api/files/albums") return Promise.resolve([]);
      if (url === "/api/files/a/best") return Promise.resolve({});
      if (url === "/api/files/b/best") return Promise.reject(new Error("kein Album"));
      return Promise.resolve(null);
    });
    const onDone = vi.fn();

    render(<PhotoBulkBar selectedIds={["a", "b"]} tagSuggestions={[]} onClearSelection={() => {}} onDone={onDone} />);

    fireEvent.click(screen.getByRole("button", { name: "Best-of", exact: true }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "★ Best-of" }));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    const messages = showToastMock.mock.calls.map(([message]) => message);
    expect(messages).toContain("Zu Best-of hinzugefügt.");
  });

  it("shows success with no failure note when every selected photo succeeds", async () => {
    browserApiFetchMock.mockImplementation((url: string) => {
      if (url === "/api/files/albums") return Promise.resolve([]);
      if (url.endsWith("/best")) return Promise.resolve({});
      return Promise.resolve(null);
    });
    const onDone = vi.fn();

    render(<PhotoBulkBar selectedIds={["a", "b"]} tagSuggestions={[]} onClearSelection={() => {}} onDone={onDone} />);

    fireEvent.click(screen.getByRole("button", { name: "Best-of", exact: true }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "★ Best-of" }));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(showToastMock).toHaveBeenCalledTimes(1);
    expect(showToastMock).toHaveBeenCalledWith("Zu Best-of hinzugefügt.", "success");
  });
});

describe("PhotoBulkBar Aus Album nehmen", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    browserApiFetchMock.mockResolvedValue([]);
  });

  it("zeigt die Aktion nur in der Albumansicht und ruft sie auf", () => {
    const onRemove = vi.fn();
    const { rerender } = render(
      <PhotoBulkBar selectedIds={["a"]} tagSuggestions={[]} onClearSelection={vi.fn()} onDone={vi.fn()} />
    );
    expect(screen.queryByRole("button", { name: "Aus Album nehmen" })).toBeNull();

    rerender(
      <PhotoBulkBar selectedIds={["a"]} tagSuggestions={[]} onClearSelection={vi.fn()} onDone={vi.fn()} onRemoveFromAlbum={onRemove} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Aus Album nehmen" }));
    expect(onRemove).toHaveBeenCalledOnce();
  });
});

describe("PhotoBulkBar Stückelung und Termin (Upload-Verlauf)", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
  });

  it("setzt Tags für grosse Auswahlen in Stücken zu 200 und zeigt Teilfehler", async () => {
    const ids = Array.from({ length: 450 }, (_, index) => `id-${index}`);
    let call = 0;
    browserApiFetchMock.mockImplementation((url: string) => {
      if (url === "/api/files/albums") return Promise.resolve([]);
      if (url === "/api/files/bulk-tags") {
        call += 1;
        return call === 2 ? Promise.reject(new Error("kaputt")) : Promise.resolve(null);
      }
      return Promise.resolve(null);
    });
    const onDone = vi.fn();
    render(<PhotoBulkBar selectedIds={ids} tagSuggestions={[]} onClearSelection={() => {}} onDone={onDone} />);
    fireEvent.click(screen.getByRole("button", { name: "Tags" }));
    const input = document.querySelector(".photo-bulk-bar-tagging input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Lager" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Anwenden" }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    const sizes = browserApiFetchMock.mock.calls
      .filter(([url]) => url === "/api/files/bulk-tags")
      .map(([, init]) => JSON.parse(init.body).file_ids.length);
    expect(sizes).toEqual([200, 200, 50]);
    expect(showToastMock).toHaveBeenCalledWith(expect.stringContaining("1 Teil konnte nicht gespeichert werden."), "error");
  });

  it("ordnet einen Termin zu und gibt Fotos an die automatische Zuordnung zurück", async () => {
    browserApiFetchMock.mockImplementation((url: string) => {
      if (url.startsWith("/api/events")) return Promise.resolve([{ id: "ev-1", title: "Lager", event_date: "2026-05-02" }]);
      if (url === "/api/files/bulk-event-link") return Promise.resolve({ updated_ids: ["a"], not_found_ids: [] });
      return Promise.resolve([]);
    });
    render(<PhotoBulkBar selectedIds={["a"]} tagSuggestions={[]} onClearSelection={() => {}} onDone={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Termin" }));
    fireEvent.click(await screen.findByRole("button", { name: "Automatisch nach Datum" }));
    await waitFor(() =>
      expect(browserApiFetchMock).toHaveBeenCalledWith("/api/files/bulk-event-link", {
        method: "POST",
        body: JSON.stringify({ file_ids: ["a"], mode: "auto", event_id: null }),
      }),
    );
    expect(showToastMock).toHaveBeenCalledWith("1 Foto wird wieder automatisch nach Datum zugeordnet.", "success");
  });

  it("bietet im Upload-Vorgang «Alle dieses Uploads auswählen» an", () => {
    browserApiFetchMock.mockResolvedValue([]);
    const onSelectAllInJob = vi.fn();
    render(<PhotoBulkBar selectedIds={["a"]} tagSuggestions={[]} onClearSelection={() => {}} onDone={() => {}} onSelectAllInJob={onSelectAllInJob} />);
    fireEvent.click(screen.getByRole("button", { name: "Alle dieses Uploads auswählen" }));
    expect(onSelectAllInJob).toHaveBeenCalled();
  });
});
