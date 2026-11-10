import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useHistory } from "./history";

describe("useHistory", () => {
  afterEach(() => vi.useRealTimers());

  it("undoes and redoes snapshots and clears redo on a new change", () => {
    const { result } = renderHook(() => useHistory({ n: 0 }));
    act(() => result.current.set({ n: 1 }));
    act(() => result.current.set({ n: 2 }));
    act(() => result.current.undo());
    expect(result.current.value).toEqual({ n: 1 });
    expect(result.current.canRedo).toBe(true);
    act(() => result.current.redo());
    expect(result.current.value).toEqual({ n: 2 });
    act(() => result.current.undo());
    act(() => result.current.set({ n: 5 }));
    expect(result.current.canRedo).toBe(false);
    act(() => result.current.undo());
    expect(result.current.value).toEqual({ n: 1 });
  });

  it("merges rapid changes with the same key into one step", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useHistory("a"));
    act(() => result.current.set("ab", "name"));
    act(() => result.current.set("abc", "name"));
    act(() => result.current.undo());
    expect(result.current.value).toBe("a");

    act(() => result.current.set("x", "name"));
    vi.advanceTimersByTime(1000);
    act(() => result.current.set("xy", "name"));
    act(() => result.current.undo());
    expect(result.current.value).toBe("x");
  });

  it("ignores identical snapshots and resets the stacks", () => {
    const value = { n: 1 };
    const { result } = renderHook(() => useHistory(value));
    act(() => result.current.set(value));
    expect(result.current.canUndo).toBe(false);
    act(() => result.current.set({ n: 2 }));
    act(() => result.current.reset({ n: 9 }));
    expect(result.current).toMatchObject({ value: { n: 9 }, canUndo: false, canRedo: false });
  });
});
