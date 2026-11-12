import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
const showToastMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

vi.mock("@/contexts/toast-context", () => ({
  useToast: () => showToastMock,
}));

const confirmMock = vi.fn();
vi.mock("@/contexts/confirm-context", () => ({
  useConfirm: () => confirmMock,
}));

// Antwort auf die Zähl-Anfrage (dry_run) vor dem eigentlichen Umbenennen.
const DRY_RUN = { updated: 0, events: 3, submission_assignments: 0, target_events: 0 };

// Imported after the mocks are registered so useTagConfig picks up the mocked browserApiFetch/useToast.
import { useTagConfig } from "./use-tag-config";

describe("useTagConfig.renameTag", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
    // Initial mount effect always calls GET /api/tag-config - resolve with a starting config
    // for every test unless a test overrides this first call itself.
    browserApiFetchMock.mockResolvedValue({ urgent: { color: "#ff0000" } });
    confirmMock.mockReset();
    confirmMock.mockResolvedValue(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renames the tag locally after the backend accepts the rename", async () => {
    const { result } = renderHook(() => useTagConfig());
    await waitFor(() => expect(result.current.tagConfig).toEqual({ urgent: { color: "#ff0000" } }));

    // rename-tag POST succeeds, tag-config PATCH succeeds too.
    browserApiFetchMock.mockResolvedValueOnce(DRY_RUN); // POST rename-tag (dry_run)
    browserApiFetchMock.mockResolvedValueOnce(undefined); // POST /api/events/rename-tag
    browserApiFetchMock.mockResolvedValueOnce(undefined); // PATCH /api/tag-config

    await act(async () => {
      await result.current.renameTag("urgent", "dringend");
    });

    expect(result.current.tagConfig).toEqual({ dringend: { color: "#ff0000" } });
    expect(result.current.tagConfig.urgent).toBeUndefined();
  });

  it("does NOT rename locally when the backend rejects the rename (regression: silent-desync bug)", async () => {
    const { result } = renderHook(() => useTagConfig());
    await waitFor(() => expect(result.current.tagConfig).toEqual({ urgent: { color: "#ff0000" } }));

    // The backend rejects the rename POST (e.g. duplicate tag name / validation error).
    browserApiFetchMock.mockReset();
    browserApiFetchMock.mockResolvedValueOnce(DRY_RUN);
    browserApiFetchMock.mockRejectedValueOnce(new Error("Tag already exists"));

    let thrown: unknown = null;
    await act(async () => {
      try {
        await result.current.renameTag("urgent", "dringend");
      } catch (err) {
        thrown = err;
      }
    });

    // The error must propagate to the caller...
    expect(thrown).toBeInstanceOf(Error);
    // ...and the local tagConfig must be completely unchanged: no local-only rename that
    // desyncs from what the backend actually has.
    expect(result.current.tagConfig).toEqual({ urgent: { color: "#ff0000" } });
    expect(result.current.tagConfig.dringend).toBeUndefined();
  });

  it("is a no-op when the new tag name is blank or unchanged", async () => {
    const { result } = renderHook(() => useTagConfig());
    await waitFor(() => expect(result.current.tagConfig).toEqual({ urgent: { color: "#ff0000" } }));

    browserApiFetchMock.mockClear();

    await act(async () => {
      await result.current.renameTag("urgent", "   ");
    });
    await act(async () => {
      await result.current.renameTag("urgent", "urgent");
    });

    expect(browserApiFetchMock).not.toHaveBeenCalled();
    expect(result.current.tagConfig).toEqual({ urgent: { color: "#ff0000" } });
  });

  it("shows an error toast when the rename succeeds but the color carry-over PATCH fails (regression: silently swallowed error)", async () => {
    const { result } = renderHook(() => useTagConfig());
    await waitFor(() => expect(result.current.tagConfig).toEqual({ urgent: { color: "#ff0000" } }));

    browserApiFetchMock.mockReset();
    browserApiFetchMock.mockResolvedValueOnce(DRY_RUN);
    browserApiFetchMock.mockResolvedValueOnce(undefined); // POST /api/events/rename-tag succeeds
    browserApiFetchMock.mockRejectedValueOnce(new Error("Speichern fehlgeschlagen")); // PATCH /api/tag-config fails

    await act(async () => {
      await result.current.renameTag("urgent", "dringend");
    });

    // The rename itself must not be undone just because the secondary color carry-over failed.
    expect(result.current.tagConfig).toEqual({ dringend: { color: "#ff0000" } });
    expect(showToastMock).toHaveBeenCalledWith("Tag umbenannt, Farbe konnte aber nicht übertragen werden", "error");
  });

  it("trims whitespace around the new tag name before renaming", async () => {
    const { result } = renderHook(() => useTagConfig());
    await waitFor(() => expect(result.current.tagConfig).toEqual({ urgent: { color: "#ff0000" } }));

    browserApiFetchMock.mockReset();
    browserApiFetchMock.mockResolvedValueOnce(DRY_RUN);
    browserApiFetchMock.mockResolvedValueOnce(undefined); // POST rename-tag
    browserApiFetchMock.mockResolvedValueOnce(undefined); // PATCH tag-config

    await act(async () => {
      await result.current.renameTag("urgent", "  dringend  ");
    });

    expect(result.current.tagConfig).toEqual({ dringend: { color: "#ff0000" } });
    const renameCall = browserApiFetchMock.mock.calls.find(
      ([path, init]) => path === "/api/events/rename-tag" && !JSON.parse((init as RequestInit).body as string).dry_run
    );
    expect(renameCall).toBeDefined();
    expect(JSON.parse((renameCall![1] as RequestInit).body as string)).toEqual({
      old_tag: "urgent",
      new_tag: "dringend",
    });
  });

  it("asks before merging into an existing tag and renames nothing when declined", async () => {
    const { result } = renderHook(() => useTagConfig());
    await waitFor(() => expect(result.current.tagConfig).toEqual({ urgent: { color: "#ff0000" } }));

    browserApiFetchMock.mockReset();
    browserApiFetchMock.mockResolvedValueOnce({ updated: 0, events: 2, submission_assignments: 1, target_events: 4 });
    confirmMock.mockResolvedValueOnce(false);

    let outcome: boolean | undefined;
    await act(async () => {
      outcome = await result.current.renameTag("urgent", "dringend");
    });

    expect(outcome).toBe(false);
    expect(browserApiFetchMock).toHaveBeenCalledTimes(1);
    expect(confirmMock).toHaveBeenCalledTimes(1);
    expect(confirmMock.mock.calls[0][0].title).toBe("Tags zusammenführen?");
    expect(confirmMock.mock.calls[0][0].message).toContain("dauerhaft");
    expect(result.current.tagConfig).toEqual({ urgent: { color: "#ff0000" } });
  });
});

describe("useTagConfig.updateTagColor", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
    browserApiFetchMock.mockResolvedValue({ urgent: { color: "#ff0000" } });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("keeps the optimistic color when the PATCH succeeds", async () => {
    const { result } = renderHook(() => useTagConfig());
    await waitFor(() => expect(result.current.tagConfig).toEqual({ urgent: { color: "#ff0000" } }));

    browserApiFetchMock.mockResolvedValueOnce(undefined); // PATCH /api/tag-config

    await act(async () => {
      await result.current.updateTagColor("urgent", "#00ff00");
    });

    expect(result.current.tagConfig).toEqual({ urgent: { color: "#00ff00" } });
    expect(showToastMock).not.toHaveBeenCalled();
  });

  it("rolls back the color and shows an error toast when the PATCH fails (regression: silently swallowed save error)", async () => {
    const { result } = renderHook(() => useTagConfig());
    await waitFor(() => expect(result.current.tagConfig).toEqual({ urgent: { color: "#ff0000" } }));

    browserApiFetchMock.mockRejectedValueOnce(new Error("Speichern fehlgeschlagen"));

    await act(async () => {
      await result.current.updateTagColor("urgent", "#00ff00");
    });

    // The color must revert to what it was before the failed save - no silent
    // desync where the UI shows a color the backend never persisted.
    expect(result.current.tagConfig).toEqual({ urgent: { color: "#ff0000" } });
    expect(showToastMock).toHaveBeenCalledWith("Speichern fehlgeschlagen", "error");
  });

  it("rolls back to no color entry when a new tag's PATCH fails, without touching other tags", async () => {
    const { result } = renderHook(() => useTagConfig());
    await waitFor(() => expect(result.current.tagConfig).toEqual({ urgent: { color: "#ff0000" } }));

    browserApiFetchMock.mockRejectedValueOnce(new Error("Netzwerkfehler"));

    await act(async () => {
      await result.current.updateTagColor("neu", "#0000ff");
    });

    expect(result.current.tagConfig).toEqual({ urgent: { color: "#ff0000" } });
    expect(result.current.tagConfig.neu).toBeUndefined();
    expect(showToastMock).toHaveBeenCalledWith("Netzwerkfehler", "error");
  });
});
