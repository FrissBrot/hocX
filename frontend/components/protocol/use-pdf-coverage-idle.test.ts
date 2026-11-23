import { renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const fetchMock = vi.fn().mockResolvedValue({ elements: [], blocks: [] });
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (...args: unknown[]) => fetchMock(...args) }));

import { usePdfCoverage } from "./use-pdf-coverage";

afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockClear();
});

it("fragt die PDF-Abdeckung erst im Leerlauf nach dem Laden ab (B1)", () => {
  const idle: Array<() => void> = [];
  vi.stubGlobal("requestIdleCallback", (callback: () => void, options?: { timeout: number }) => {
    expect(options?.timeout).toBeGreaterThan(0);
    idle.push(callback);
    return idle.length;
  });
  vi.stubGlobal("cancelIdleCallback", vi.fn());
  renderHook(() => usePdfCoverage("p1", "sig"));
  expect(fetchMock).not.toHaveBeenCalled();
  idle.forEach((callback) => callback());
  expect(fetchMock).toHaveBeenCalledWith("/api/protocols/p1/pdf-coverage");
});
