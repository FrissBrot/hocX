import { afterEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args) }));

import { dismissUploadHint, isUploadHintDismissed, openUploadJob, reportClientRejections, runInChunks, targetFromForm } from "./upload-jobs";

describe("upload-jobs", () => {
  afterEach(() => {
    browserApiFetchMock.mockReset();
    window.localStorage.clear();
  });

  it("stückelt sequenziell, zählt Fehler und bricht auf Wunsch ab", async () => {
    const seen: number[][] = [];
    const progress: number[] = [];
    const outcome = await runInChunks([1, 2, 3, 4, 5], 2, async (chunk) => {
      seen.push(chunk);
      if (chunk[0] === 3) throw new Error("x");
      return chunk.length;
    }, { onProgress: (value) => progress.push(value.done) });
    expect(seen).toEqual([[1, 2], [3, 4], [5]]);
    expect(outcome.results).toEqual([2, 1]);
    expect(outcome.failedChunks).toBe(1);
    expect((outcome.firstError as Error).message).toBe("x");
    expect(progress).toEqual([0, 2, 4, 5]);

    let calls = 0;
    const cancelled = await runInChunks([1, 2, 3], 1, async () => ++calls, { shouldCancel: () => calls >= 1 });
    expect(cancelled.cancelled).toBe(true);
    expect(calls).toBe(1);
  });

  it("öffnet Vorgänge fehlertolerant und meldet Browser-Ablehnungen in Stücken", async () => {
    browserApiFetchMock.mockRejectedValueOnce(new Error("alt"));
    expect(await openUploadJob("gallery")).toBeNull();
    browserApiFetchMock.mockResolvedValueOnce({ id: "uj" });
    expect(await openUploadJob("document", { event_id: "e" })).toBe("uj");
    browserApiFetchMock.mockResolvedValue(null);
    await reportClientRejections("uj", Array.from({ length: 600 }, (_, index) => ({ name: `f${index}.txt`, size: 1 })));
    const posts = browserApiFetchMock.mock.calls.filter(([url]) => url === "/api/upload-jobs/uj/client-results");
    expect(posts.map(([, init]) => JSON.parse(init.body).items.length)).toEqual([500, 100]);
    expect(JSON.parse(posts[0][1].body).items[0]).toEqual({ name: "f0.txt", size: 1, code: "client_rejected" });
  });

  it("liest den Bezug aus den Formularfeldern und merkt ausgeblendete Hinweise", () => {
    expect(targetFromForm((form) => form.append("event_id", "ev"))).toEqual({
      event_id: "ev", submission_assignment_id: null, submission_element_ref: null, cycle_config_id: null,
    });
    expect(isUploadHintDismissed("a")).toBe(false);
    dismissUploadHint("a");
    expect(isUploadHintDismissed("a")).toBe(true);
  });
});
