import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { IMAGE_RETRY_DELAYS_MS, jitteredDelay, useImageRetry, withRetryParam } from "./use-image-retry";

const URL_A = "/api/stored-files/a/thumbnail";

describe("useImageRetry", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("lädt nach einem Fehler mit neuer URL nach und zeigt solange keinen Platzhalter", () => {
    const { result } = renderHook(() => useImageRetry(URL_A, { random: () => 0.5 }));
    expect(result.current.src).toBe(URL_A);
    act(() => result.current.onError());
    expect(result.current.waiting).toBe(true);
    expect(result.current.failed).toBe(false);
    expect(result.current.src).toBe(URL_A);
    act(() => vi.advanceTimersByTime(IMAGE_RETRY_DELAYS_MS[0] - 1));
    expect(result.current.attempt).toBe(0);
    act(() => vi.advanceTimersByTime(1));
    expect(result.current).toMatchObject({ attempt: 1, waiting: false, failed: false, src: `${URL_A}?retry=1` });
  });

  it("gibt nach allen Versuchen auf (höchstens 4 Requests) und meldet dann failed", () => {
    const { result } = renderHook(() => useImageRetry(URL_A, { random: () => 0.5 }));
    for (const delay of IMAGE_RETRY_DELAYS_MS) {
      act(() => result.current.onError());
      act(() => vi.advanceTimersByTime(delay));
    }
    expect(result.current.attempt).toBe(IMAGE_RETRY_DELAYS_MS.length);
    act(() => result.current.onError());
    expect(result.current).toMatchObject({ failed: true, waiting: false });
    act(() => vi.advanceTimersByTime(60_000));
    expect(result.current.attempt).toBe(IMAGE_RETRY_DELAYS_MS.length);
  });

  it("plant nach dem Unmount keinen weiteren Versuch", () => {
    const { result, unmount } = renderHook(() => useImageRetry(URL_A));
    act(() => result.current.onError());
    expect(vi.getTimerCount()).toBe(1);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("beginnt bei einer neuen Ausgangs-URL von vorn", () => {
    const { result, rerender } = renderHook(({ url }) => useImageRetry(url, { random: () => 0.5 }), { initialProps: { url: URL_A } });
    act(() => result.current.onError());
    act(() => vi.advanceTimersByTime(IMAGE_RETRY_DELAYS_MS[0]));
    expect(result.current.attempt).toBe(1);
    rerender({ url: "/x.jpg?v=2" });
    expect(result.current).toMatchObject({ attempt: 0, src: "/x.jpg?v=2", waiting: false, failed: false });
    expect(vi.getTimerCount()).toBe(0);
  });

  it("ohne URL: weder Request noch Platzhalter-Zustand", () => {
    const { result } = renderHook(() => useImageRetry(null));
    expect(result.current).toMatchObject({ src: null, failed: false, waiting: false });
  });
});

describe("Hilfen", () => {
  it("Jitter bleibt innerhalb ±25 %", () => {
    expect(jitteredDelay(4000, () => 0)).toBe(3000);
    expect(jitteredDelay(4000, () => 1)).toBe(5000);
    expect(jitteredDelay(4000, () => 0.5)).toBe(4000);
  });

  it("hängt den Versuchszähler an bestehende Query-Parameter an", () => {
    expect(withRetryParam("/a", 0)).toBe("/a");
    expect(withRetryParam("/a", 2)).toBe("/a?retry=2");
    expect(withRetryParam("/a?x=1", 1)).toBe("/a?x=1&retry=1");
  });
});
