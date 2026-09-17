import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
const showToastMock = vi.fn();
const confirmMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
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
    vi.restoreAllMocks();
  });

  it("does not claim success when every selected photo fails (audit fix, 2026-09-17)", async () => {
    browserApiFetchMock.mockImplementation((url: string) => {
      if (url === "/api/files/albums") return Promise.resolve([]);
      if (url.endsWith("/best")) return Promise.reject(new Error("kein Album"));
      return Promise.resolve(null);
    });
    const onDone = vi.fn();

    render(<PhotoBulkBar selectedIds={["a", "b"]} tagSuggestions={[]} onClearSelection={() => {}} onDone={onDone} />);

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

    fireEvent.click(await screen.findByRole("button", { name: "★ Best-of" }));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(showToastMock).toHaveBeenCalledTimes(1);
    expect(showToastMock).toHaveBeenCalledWith("Zu Best-of hinzugefügt.", "success");
  });
});
