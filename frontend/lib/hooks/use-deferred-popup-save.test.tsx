import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useDeferredPopupSave } from "@/lib/hooks/use-deferred-popup-save";

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

describe("useDeferredPopupSave", () => {
  it("speichert eine wartende Änderung beim Unmount sofort (1.6.1)", async () => {
    const save = vi.fn(async () => {});
    const { result, unmount } = renderHook(() => useDeferredPopupSave());
    act(() => result.current.schedule(save));
    expect(save).not.toHaveBeenCalled();
    // Panel verschwindet vor Ablauf der 500 ms, ohne «Schliessen» (Seiten- oder Ansichtswechsel)
    unmount();
    await vi.waitFor(() => expect(save).toHaveBeenCalledTimes(1), { timeout: 300 });
  });

  it("speichert beim Unmount nichts, wenn nichts mehr wartet", async () => {
    const save = vi.fn(async () => {});
    const { result, unmount } = renderHook(() => useDeferredPopupSave());
    act(() => result.current.schedule(save));
    await act(async () => {
      await result.current.flush();
    });
    expect(save).toHaveBeenCalledTimes(1);
    unmount();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(save).toHaveBeenCalledTimes(1);
  });
});
