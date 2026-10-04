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

  it("downloads the selected originals with their filenames", async () => {
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
    render(<PhotoBulkBar selectedIds={["a", "b"]} selectedItems={[{ original_name: "a.jpg", content_url: "/a/content" }, { original_name: "b.jpg", content_url: "/b/content" }]} tagSuggestions={[]} onClearSelection={() => {}} onDone={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Herunterladen" }));
    await waitFor(() => expect(downloads).toEqual(["a.jpg", "b.jpg"]));
    expect(fetchMock).toHaveBeenCalledWith("/a/content", { credentials: "include" });
    expect(fetchMock).toHaveBeenCalledWith("/b/content", { credentials: "include" });
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
    fireEvent.click(await screen.findByRole("button", { name: "★ Best-of" }));

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
    fireEvent.click(await screen.findByRole("button", { name: "★ Best-of" }));

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
    fireEvent.click(await screen.findByRole("button", { name: "★ Best-of" }));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(showToastMock).toHaveBeenCalledTimes(1);
    expect(showToastMock).toHaveBeenCalledWith("Zu Best-of hinzugefügt.", "success");
  });
});
