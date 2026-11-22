import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
const showToastMock = vi.fn();
const confirmMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  LONG_RUNNING_TIMEOUT_MS: 1000,
  browserApiBaseUrl: "",
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
  browserApiUpload: vi.fn(),
}));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => showToastMock }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => confirmMock }));

import type { ImportJob, ImportPreview } from "@/lib/files/file-import";

import { ImportRulesStep } from "./import-rules-step";

const job: ImportJob = {
  id: "job-1", source: "zip", status: "ready", type_filter: "all", include_gps: true, folder_tags: false, takeout: false,
  rules: [], total_items: 3, total_bytes: 3000, archives: 1, error: null, is_owner: true, requested_by_name: "Anna",
  created_at: "2026-11-22T10:00:00Z", started_at: null, finished_at: null, last_progress_at: null, counts: {}, codes: {}, processed_bytes: 0,
};

function preview(overrides: Partial<ImportPreview> = {}): ImportPreview {
  return {
    summary: { total: 3, importable: 2, images: 1, documents: 1, planned_bytes: 2000, conflicts: 0, skipped: { excluded_by_rule: 1 }, per_rule: {} },
    quota: { limit_bytes: null, used_bytes: 0, planned_bytes: 2000, fits: true },
    errors: [],
    items: [
      { path: "Lager/a.jpg", kind: "image", size: 1000, import: true, reason: null, tags: ["Lager"], date: "2019-07-01", albums: ["Lager"], rules: [], conflict: false },
      { path: "tmp/b.jpg", kind: "image", size: 1000, import: false, reason: "excluded_by_rule", tags: [], date: null, albums: [], rules: [], conflict: false },
    ],
    filtered_total: 2,
    folders: ["Lager", "tmp"],
    saved: true,
    ...overrides,
  };
}

describe("ImportRulesStep", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
    confirmMock.mockReset();
  });

  function mockApi(result: ImportPreview) {
    browserApiFetchMock.mockImplementation((url: string) => {
      if (url === "/api/files/albums") return Promise.resolve([{ id: "a1", name: "Lager", kind: "manual" }, { id: "a2", name: "Auto", kind: "cycle" }]);
      if (url === "/api/files/tags") return Promise.resolve(["Lager"]);
      if (url.endsWith("/preview")) return Promise.resolve(result);
      if (url.endsWith("/start")) return Promise.resolve({ ...job, status: "queued" });
      return Promise.resolve(null);
    });
  }

  it("shows the preview with translated reasons and starts after confirmation", async () => {
    mockApi(preview());
    confirmMock.mockResolvedValue(true);
    const onJob = vi.fn();
    render(<ImportRulesStep job={job} readOnly={false} onJob={onJob} onCancelled={() => {}} />);
    expect(await screen.findByText("Lager/a.jpg", {}, { timeout: 3000 })).toBeTruthy();
    expect(screen.getByText("Durch Regel ausgeschlossen")).toBeTruthy();
    const start = screen.getByRole("button", { name: "Import starten" });
    await waitFor(() => expect((start as HTMLButtonElement).disabled).toBe(false), { timeout: 3000 });
    fireEvent.click(start);
    await waitFor(() => expect(confirmMock).toHaveBeenCalled());
    await waitFor(() => expect(onJob).toHaveBeenCalledWith(expect.objectContaining({ status: "queued" })));
  });

  it("blocks the start while a rule is invalid and shows the reason at the rule", async () => {
    mockApi(preview({ errors: [{ rule_id: "r", field: "name_regex", code: "regex_unsupported" }], saved: false }));
    render(<ImportRulesStep job={{ ...job, rules: [{ id: "r", enabled: true, match: { kind: "all", case_sensitive: false, name_regex: "(a)\\1" }, action: { type: "skip" } }] }} readOnly={false} onJob={() => {}} onCancelled={() => {}} />);
    expect(await screen.findByText("Dieser Ausdruck wird nicht unterstützt (keine Rückverweise oder Lookarounds).", {}, { timeout: 3000 })).toBeTruthy();
    expect((screen.getByRole("button", { name: "Import starten" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("adds a rule with keyboard-reachable reorder and remove controls", async () => {
    mockApi(preview());
    render(<ImportRulesStep job={job} readOnly={false} onJob={() => {}} onCancelled={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Regel hinzufügen" }));
    expect(screen.getByRole("group", { name: /Regel 1/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Regel 1 entfernen" })).toBeTruthy();
    await waitFor(() => expect(browserApiFetchMock.mock.calls.some(([url, init]) => String(url).endsWith("/preview") && JSON.parse(String(init?.body)).rules.length === 1)).toBe(true), { timeout: 3000 });
    const lastCall = browserApiFetchMock.mock.calls.filter(([url]) => String(url).endsWith("/preview")).at(-1);
    expect(JSON.parse(String(lastCall?.[1]?.body)).rules).toHaveLength(1);
  });
});
