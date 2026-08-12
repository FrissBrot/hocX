import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

// Imported after the mock is registered so useTagConfig picks up the mocked browserApiFetch.
import { useTagConfig } from "./use-tag-config";

describe("useTagConfig.renameTag", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    // Initial mount effect always calls GET /api/tag-config - resolve with a starting config
    // for every test unless a test overrides this first call itself.
    browserApiFetchMock.mockResolvedValue({ urgent: { color: "#ff0000" } });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renames the tag locally after the backend accepts the rename", async () => {
    const { result } = renderHook(() => useTagConfig());
    await waitFor(() => expect(result.current.tagConfig).toEqual({ urgent: { color: "#ff0000" } }));

    // rename-tag POST succeeds, tag-config PATCH succeeds too.
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

  it("trims whitespace around the new tag name before renaming", async () => {
    const { result } = renderHook(() => useTagConfig());
    await waitFor(() => expect(result.current.tagConfig).toEqual({ urgent: { color: "#ff0000" } }));

    browserApiFetchMock.mockReset();
    browserApiFetchMock.mockResolvedValueOnce(undefined); // POST rename-tag
    browserApiFetchMock.mockResolvedValueOnce(undefined); // PATCH tag-config

    await act(async () => {
      await result.current.renameTag("urgent", "  dringend  ");
    });

    expect(result.current.tagConfig).toEqual({ dringend: { color: "#ff0000" } });
    const renameCall = browserApiFetchMock.mock.calls.find(([path]) => path === "/api/events/rename-tag");
    expect(renameCall).toBeDefined();
    expect(JSON.parse((renameCall![1] as RequestInit).body as string)).toEqual({
      old_tag: "urgent",
      new_tag: "dringend",
    });
  });
});
