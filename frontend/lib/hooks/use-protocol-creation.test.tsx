import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { browserApiFetch } from "@/lib/api/client";
import { useProtocolCreation } from "./use-protocol-creation";

vi.mock("@/lib/api/client", () => ({ browserApiFetch: vi.fn() }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));

afterEach(() => vi.clearAllMocks());

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("Protokollerstellung", () => {
  it("verwirft alte Vorschauen nach einem Template- oder Datumswechsel", async () => {
    const old = deferred<{ protocol_number: string; title: string }>();
    const latest = deferred<{ protocol_number: string; title: string }>();
    vi.mocked(browserApiFetch).mockReturnValueOnce(old.promise).mockReturnValueOnce(latest.promise);
    const { result, rerender } = renderHook(({ id, date }) => useProtocolCreation(true, id, date), {
      initialProps: { id: "a", date: "2026-10-12" },
    });
    await waitFor(() => expect(browserApiFetch).toHaveBeenCalledTimes(1));
    rerender({ id: "b", date: "2026-10-13" });
    expect(result.current.preview).toBeNull();
    await waitFor(() => expect(browserApiFetch).toHaveBeenCalledTimes(2));
    await act(async () => latest.resolve({ protocol_number: "B-2", title: "13.10.2026" }));
    await act(async () => old.resolve({ protocol_number: "A-1", title: "12.10.2026" }));
    expect(result.current.preview).toEqual({ protocol_number: "B-2", title: "13.10.2026" });
    expect(vi.mocked(browserApiFetch).mock.calls[1][0]).toContain("template_id=b&protocol_date=2026-10-13");
  });

  it("speichert schnelle Auswahlwechsel in derselben Reihenfolge", async () => {
    const first = deferred<null>();
    vi.mocked(browserApiFetch).mockReturnValueOnce(first.promise).mockResolvedValueOnce(null);
    const { result } = renderHook(() => useProtocolCreation(false, "a", "2026-10-12"));
    act(() => {
      result.current.rememberTemplate("b");
      result.current.rememberTemplate("c");
    });
    await waitFor(() => expect(browserApiFetch).toHaveBeenCalledTimes(1));
    expect(vi.mocked(browserApiFetch).mock.calls[0][1]?.body).toBe('{"template_id":"b"}');
    await act(async () => first.resolve(null));
    await waitFor(() => expect(browserApiFetch).toHaveBeenCalledTimes(2));
    expect(vi.mocked(browserApiFetch).mock.calls[1][1]?.body).toBe('{"template_id":"c"}');
  });
});
