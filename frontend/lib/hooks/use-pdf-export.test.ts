import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePdfExport } from "./use-pdf-export";

const { apiFetch, showToast } = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  showToast: vi.fn(),
}));
vi.mock("@/lib/api/client", () => ({
  ApiError: class ApiError extends Error {},
  browserApiBaseUrl: "https://hocx.test",
  browserApiFetch: apiFetch,
}));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => showToast }));

const protocol = {
  id: "protocol-1",
  protocol_number: "P-1",
  latest_pdf_url: "/old.pdf",
};
const exported = {
  content_url: "/current.pdf",
  version_label: "v0.2",
};
// POST /api/documents/render liefert einen PDF-Auftrag (job-worker, Concurrency-Audit Paket 10).
const done = (result: object) => ({ id: "job-1", status: "done", export: result, error_status: null, error: null, created_at: "" });

describe("usePdfExport", () => {
  const pdfWindow = { opener: {}, closed: false, location: { replace: vi.fn() }, close: vi.fn() };

  beforeEach(() => {
    vi.clearAllMocks();
    apiFetch.mockReset();
    vi.spyOn(window, "open").mockReturnValue(pdfWindow as unknown as Window);
  });

  it("generates from saved data even when an older PDF URL exists, on every open", async () => {
    apiFetch.mockResolvedValueOnce(done(exported)).mockResolvedValueOnce(done({ ...exported, content_url: "/changed.pdf" }));
    const onExported = vi.fn();
    const { result } = renderHook(() => usePdfExport());

    await act(async () => { await result.current.openOrGeneratePdf(protocol, onExported); });
    expect(apiFetch).toHaveBeenCalledWith(
      "/api/documents/render",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ protocol_id: "protocol-1", document_type: "protocol" }) })
    );
    expect(pdfWindow.location.replace).toHaveBeenLastCalledWith("https://hocx.test/current.pdf");
    expect(onExported).toHaveBeenCalledWith({ content_url: "/current.pdf", version_label: "v0.2", version_major: 0, version_minor: 2 });

    await act(async () => { await result.current.openOrGeneratePdf(protocol); });
    expect(apiFetch).toHaveBeenCalledTimes(2);
    expect(pdfWindow.location.replace).toHaveBeenLastCalledWith("https://hocx.test/changed.pdf");
    expect(result.current.busyByProtocol[protocol.id]).toBe(false);
  });

  it("prevents duplicate requests while generation is running", async () => {
    let finish!: (value: ReturnType<typeof done>) => void;
    apiFetch.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const { result } = renderHook(() => usePdfExport());
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.openOrGeneratePdf(protocol);
      void result.current.openOrGeneratePdf(protocol);
    });
    expect(result.current.busyByProtocol[protocol.id]).toBe(true);
    expect(apiFetch).toHaveBeenCalledTimes(1);
    await act(async () => { finish(done(exported)); await pending; });
    expect(result.current.busyByProtocol[protocol.id]).toBe(false);
  });

  it("closes the empty tab on failure, never opens the stale PDF, and allows retry", async () => {
    apiFetch.mockRejectedValueOnce(new Error("Export fehlgeschlagen")).mockResolvedValueOnce(done(exported));
    const { result } = renderHook(() => usePdfExport());
    await act(async () => { await result.current.openOrGeneratePdf(protocol); });
    expect(pdfWindow.close).toHaveBeenCalledOnce();
    expect(pdfWindow.location.replace).not.toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledWith("Export fehlgeschlagen", "error");
    expect(result.current.busyByProtocol[protocol.id]).toBe(false);
    await act(async () => { await result.current.openOrGeneratePdf(protocol); });
    expect(pdfWindow.location.replace).toHaveBeenCalledWith("https://hocx.test/current.pdf");
  });

  it("provides a link to the fresh PDF if the browser blocks the new tab", async () => {
    vi.mocked(window.open).mockReturnValue(null);
    apiFetch.mockResolvedValue(done(exported));
    const { result } = renderHook(() => usePdfExport());
    await act(async () => { await result.current.openOrGeneratePdf(protocol); });
    const options = showToast.mock.calls[0][2];
    options.onMessageClick();
    expect(window.open).toHaveBeenLastCalledWith("https://hocx.test/current.pdf", "_blank", "noopener,noreferrer");
  });

  it("treats a missing content URL as an error instead of falling back to the old file", async () => {
    apiFetch.mockResolvedValue({ ...exported, content_url: null });
    const { result } = renderHook(() => usePdfExport());
    await act(async () => { await result.current.openOrGeneratePdf(protocol); });
    expect(pdfWindow.close).toHaveBeenCalledOnce();
    expect(pdfWindow.location.replace).not.toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledWith("Der Export ist fehlgeschlagen.", "error");
  });
});
