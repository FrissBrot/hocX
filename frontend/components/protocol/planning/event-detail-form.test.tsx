import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EVENT_TEXT_SAVE_DELAY_MS, useEventAutosave } from "./event-detail-form";
import { eventDeleteMessage } from "@/components/events/use-confirm-event-delete";

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("useEventAutosave", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("schickt beim Tippen nur ein PATCH nach der Pause, mit dem letzten Stand", async () => {
    const onUpdate = vi.fn().mockResolvedValue(true);
    const { result } = renderHook(() => useEventAutosave("e1", onUpdate));

    for (const value of ["T", "Tr", "Training"]) {
      act(() => result.current.queue({ title: value }));
    }
    expect(onUpdate).not.toHaveBeenCalled();
    expect(result.current.draft.title).toBe("Training");

    await act(async () => {
      vi.advanceTimersByTime(EVENT_TEXT_SAVE_DELAY_MS);
    });
    expect(onUpdate).toHaveBeenCalledTimes(1);
    expect(onUpdate).toHaveBeenCalledWith({ title: "Training" });
  });

  it("führt Anfragen nacheinander aus, nie zwei gleichzeitig", async () => {
    const first = deferred();
    const calls: string[] = [];
    const onUpdate = vi.fn(async (patch: { title?: string }) => {
      calls.push(`start:${patch.title}`);
      if (patch.title === "A") await first.promise;
      calls.push(`end:${patch.title}`);
    });
    const { result } = renderHook(() => useEventAutosave("e1", onUpdate));

    act(() => result.current.queue({ title: "A" }));
    act(() => result.current.flush());
    act(() => result.current.queue({ title: "B" }));
    act(() => result.current.flush());
    await act(async () => {
      await Promise.resolve();
    });
    expect(calls).toEqual(["start:A"]);

    await act(async () => {
      first.resolve();
      await vi.runAllTimersAsync();
    });
    expect(calls).toEqual(["start:A", "end:A", "start:B", "end:B"]);
  });

  it("speichert offene Eingaben beim Schliessen (Unmount) sofort", async () => {
    const onUpdate = vi.fn().mockResolvedValue(true);
    const { result, unmount } = renderHook(() => useEventAutosave("e1", onUpdate));
    act(() => result.current.queue({ description: "Noch nicht gespeichert" }));
    unmount();
    await vi.runAllTimersAsync();
    expect(onUpdate).toHaveBeenCalledWith({ description: "Noch nicht gespeichert" });
  });

  it("sendet beim Wechsel des Termins an den bisherigen Termin", async () => {
    const forE1 = vi.fn().mockResolvedValue(true);
    const forE2 = vi.fn().mockResolvedValue(true);
    const { result, rerender } = renderHook(({ id, cb }) => useEventAutosave(id, cb), {
      initialProps: { id: "e1", cb: forE1 },
    });
    act(() => result.current.queue({ title: "Für e1" }));
    rerender({ id: "e2", cb: forE2 });
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(forE1).toHaveBeenCalledWith({ title: "Für e1" });
    expect(forE2).not.toHaveBeenCalled();
  });

  it("Klick-Felder senden offene Texte zuerst", async () => {
    const onUpdate = vi.fn().mockResolvedValue(true);
    const { result } = renderHook(() => useEventAutosave("e1", onUpdate));
    act(() => result.current.queue({ title: "Neu" }));
    await act(async () => {
      result.current.commit({ is_cancelled: true });
      await vi.runAllTimersAsync();
    });
    expect(onUpdate.mock.calls.map((call) => call[0])).toEqual([{ title: "Neu" }, { is_cancelled: true }]);
  });

  it("meldet einen Fehler, wenn onUpdate false liefert", async () => {
    const onUpdate = vi.fn().mockResolvedValue(false);
    const { result } = renderHook(() => useEventAutosave("e1", onUpdate));
    await act(async () => {
      result.current.commit({ is_cancelled: true });
      await vi.runAllTimersAsync();
    });
    expect(result.current.saveState).toBe("error");
  });
});

describe("eventDeleteMessage", () => {
  const t = (key: string, values?: Record<string, string | number | Date>) => `${key}${values ? JSON.stringify(values) : ""}`;

  it("nennt die Anzahl mitgelöschter Einreichungen und Dateien", () => {
    const message = eventDeleteMessage(t, { submission_count: 2, file_count: 5 }, "Lager");
    expect(message).toContain('deleteDialog.messageWithTitle{"title":"Lager"}');
    expect(message).toContain('deleteDialog.submissions{"count":2,"files":5}');
    expect(message).toContain("deleteDialog.cancelInstead");
  });

  it("warnt allgemein, wenn die Anzahl nicht geladen werden konnte", () => {
    expect(eventDeleteMessage(t, null)).toContain("deleteDialog.submissionsUnknown");
  });

  it("ohne Einreichungen keine Warnung zu Dateien", () => {
    expect(eventDeleteMessage(t, { submission_count: 0, file_count: 0 })).not.toContain("deleteDialog.submissions");
  });
});
