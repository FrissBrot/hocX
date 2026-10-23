import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock("@/lib/api/client", async (original) => ({ ...(await original<object>()), browserApiFetch: apiFetch }));

import { renderDocument } from "./api";

const exported = { id: "e1", content_url: "/x.pdf", version_label: "v1.0" };
const job = (status: string, extra: object = {}) => ({ id: "j1", status, export: null, error_status: null, error: null, created_at: "", ...extra });

describe("renderDocument (PDF-Auftrag)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    apiFetch.mockReset();
  });

  it("fragt den Auftrag ab, bis das PDF fertig ist", async () => {
    apiFetch
      .mockResolvedValueOnce(job("queued"))
      .mockResolvedValueOnce(job("running"))
      .mockResolvedValueOnce(job("done", { export: exported }));
    const pending = renderDocument({ document_type: "todos" });
    await vi.runAllTimersAsync();
    await expect(pending).resolves.toEqual(exported);
    expect(apiFetch).toHaveBeenNthCalledWith(2, "/api/documents/render-jobs/j1");
  });

  it("meldet die Fehlermeldung des Servers bei gescheitertem Auftrag", async () => {
    apiFetch.mockResolvedValueOnce(job("queued")).mockResolvedValueOnce(job("failed", { error_status: 422, error: { message: "Block X fehlerhaft" } }));
    const pending = renderDocument({ document_type: "todos" });
    const assertion = expect(pending).rejects.toMatchObject({ message: "Block X fehlerhaft", status: 422 });
    await vi.runAllTimersAsync();
    await assertion;
  });
});
