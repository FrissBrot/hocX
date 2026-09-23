import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePdfExport } from "./use-pdf-export";

const { apiFetch, showToast } = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  showToast: vi.fn(),
}));
vi.mock("@/lib/api/client", () => ({
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
  status: "generated",
  export_format: "pdf",
};

describe("usePdfExport", () => {
  const pdfWindow = { opener: {}, closed: false, location: { replace: vi.fn() }, close: vi.fn() };

  beforeEach(() => {
    vi.clearAllMocks();
    apiFetch.mockReset();
    vi.spyOn(window, "open").mockReturnValue(pdfWindow as unknown as Window);
  });

  it("generates from saved data even when an older PDF URL exists, on every open", async () => {
    apiFetch.mockResolvedValueOnce(exported).mockResolvedValueOnce({ ...exported, content_url: "/changed.pdf" });
    const onExported = vi.fn();
    const { result } = renderHook(() => usePdfExport());

    await act(async () => { await result.current.openOrGeneratePdf(protocol, onExported); });
    expect(apiFetch).toHaveBeenCalledWith("/api/protocols/protocol-1/exports/pdf", { method: "POST" });
    expect(pdfWindow.location.replace).toHaveBeenLastCalledWith("https://hocx.test/current.pdf");
    expect(onExported).toHaveBeenCalledWith(exported);

    await act(async () => { await result.current.openOrGeneratePdf(protocol); });
    expect(apiFetch).toHaveBeenCalledTimes(2);
    expect(pdfWindow.location.replace).toHaveBeenLastCalledWith("https://hocx.test/changed.pdf");
    expect(result.current.busyByProtocol[protocol.id]).toBe(false);
  });

  it("prevents duplicate requests while generation is running", async () => {
    let finish!: (value: typeof exported) => void;
    apiFetch.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const { result } = renderHook(() => usePdfExport());
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.openOrGeneratePdf(protocol);
      void result.current.openOrGeneratePdf(protocol);
    });
    expect(result.current.busyByProtocol[protocol.id]).toBe(true);
    expect(apiFetch).toHaveBeenCalledTimes(1);
    await act(async () => { finish(exported); await pending; });
    expect(result.current.busyByProtocol[protocol.id]).toBe(false);
  });

  it("closes the empty tab on failure, never opens the stale PDF, and allows retry", async () => {
    apiFetch.mockRejectedValueOnce(new Error("Export fehlgeschlagen")).mockResolvedValueOnce(exported);
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
    apiFetch.mockResolvedValue(exported);
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
    expect(showToast).toHaveBeenCalledWith("Die PDF konnte nicht bereitgestellt werden.", "error");
  });
});
