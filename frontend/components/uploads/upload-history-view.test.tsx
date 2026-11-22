import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
const showToastMock = vi.fn();
vi.mock("@/lib/api/client", () => ({ browserApiBaseUrl: "", browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args) }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => showToastMock }));

import { UploadHistoryView } from "./upload-history-view";
import { RecentUploadHint } from "./recent-upload-hint";

function job(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id, channel: "gallery", actor_kind: "user", created_by_name: "Anna Muster", created_by_deleted: false, is_mine: true,
    status: "partial", reconstructed: false, created_at: new Date().toISOString(), finished_at: null,
    counts: { total: 52, uploaded: 48, duplicates: 3, metadata_updated: 0, rejected: 1, infected: 0, failed: 0, discarded: 0 },
    ref: { kind: "event", id: "ev", label: "Sommerlager", on_date: "2026-07-01" }, ...overrides,
  };
}

describe("UploadHistoryView", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
  });

  it("zeigt Vorgänge mit Ergebnis, filtert und lädt per Cursor nach", async () => {
    browserApiFetchMock.mockImplementation((url: string) =>
      Promise.resolve(url.includes("cursor=") ? { items: [job("b", { channel: "abgabebox", actor_kind: "anonymous_link" })], next_cursor: null } : { items: [job("a")], next_cursor: "c1" }),
    );
    render(<UploadHistoryView area="photos" canSeeAll />);
    expect(await screen.findByText("48 hochgeladen · 3 Duplikate · 1 abgelehnt")).toBeInTheDocument();
    expect(screen.getByText("Anna Muster")).toBeInTheDocument();
    expect(screen.getByText("Sommerlager · 01.07.2026")).toBeInTheDocument();
    const first = String(browserApiFetchMock.mock.calls[0][0]);
    expect(first).toContain("channel=gallery");
    expect(first).not.toContain("mine=true");
    fireEvent.click(screen.getByRole("button", { name: "Mehr laden" }));
    expect(await screen.findByText("Abgabebox", { selector: "td" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Meine" }));
    await waitFor(() => expect(String(browserApiFetchMock.mock.calls.at(-1)?.[0])).toContain("mine=true"));
    fireEvent.click(screen.getByRole("checkbox", { name: "Nur mit Problemen" }));
    await waitFor(() => expect(String(browserApiFetchMock.mock.calls.at(-1)?.[0])).toContain("problems=true"));
  });

  it("zeigt ohne Recht auf alle nur die eigenen Vorgänge", async () => {
    browserApiFetchMock.mockResolvedValue({ items: [], next_cursor: null });
    render(<UploadHistoryView area="files" canSeeAll={false} />);
    expect(await screen.findByText("Keine Uploads für diese Auswahl.")).toBeInTheDocument();
    expect(String(browserApiFetchMock.mock.calls[0][0])).toContain("mine=true");
    expect(String(browserApiFetchMock.mock.calls[0][0])).toContain("channel=document");
    expect(screen.queryByRole("tab", { name: "Alle" })).not.toBeInTheDocument();
  });
});

describe("RecentUploadHint", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    window.localStorage.clear();
  });

  it("zeigt den eigenen Upload der letzten 24 h und lässt sich ausblenden", async () => {
    browserApiFetchMock.mockResolvedValue({ items: [job("a", { status: "done" })], next_cursor: null });
    render(<RecentUploadHint channels={["gallery"]} basePath="/photos/uploads" noun="photos" />);
    expect(await screen.findByText("48 Fotos hochgeladen.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Bearbeiten" })).toHaveAttribute("href", "/photos/uploads/a");
    fireEvent.click(screen.getByRole("button", { name: "Hinweis ausblenden" }));
    expect(screen.queryByText("48 Fotos hochgeladen.")).not.toBeInTheDocument();
  });

  it("schweigt bei älteren Uploads", async () => {
    browserApiFetchMock.mockResolvedValue({ items: [job("a", { status: "done", created_at: "2020-01-01T00:00:00Z" })], next_cursor: null });
    render(<RecentUploadHint channels={["gallery"]} basePath="/photos/uploads" noun="photos" />);
    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalled());
    expect(screen.queryByText(/hochgeladen/)).not.toBeInTheDocument();
  });
});
