import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ActivityEntry, ActivityPage } from "@/types/api";
import { ActivityLog, LIVE_REFRESH_MS } from "./activity-log";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ browserApiFetch: api }));

const entry = (created_at: string, actor_name: string): ActivityEntry => ({
  created_at, action: "auth.login", category: "auth", outcome: "success", actor_kind: "user", actor_name, entity_type: null,
});
const pageWith = (items: ActivityEntry[]): ActivityPage => ({ items, total: items.length, categories: [], actions: [], actors: [] });

beforeEach(() => {
  vi.useFakeTimers();
  api.mockReset();
});
afterEach(() => vi.useRealTimers());

it("lädt die erste Seite live nach und hebt neue Einträge hervor", async () => {
  const first = pageWith([entry("2026-11-20T08:00:00Z", "Anna")]);
  const next = pageWith([entry("2026-11-20T08:05:00Z", "Ben"), entry("2026-11-20T08:00:00Z", "Anna")]);
  api.mockResolvedValueOnce(first).mockResolvedValue(next);
  render(<ActivityLog initialPage={first} />);
  await act(async () => { await Promise.resolve(); });
  expect(screen.getByRole("status")).toHaveTextContent("Live");

  await act(async () => { await vi.advanceTimersByTimeAsync(LIVE_REFRESH_MS); });
  expect(api).toHaveBeenLastCalledWith(expect.stringContaining("with_options=false"));
  const ben = screen.getByText("Ben").closest("tr");
  expect(ben).toHaveClass("activity-row-fresh");
  expect(screen.getByText("Anna").closest("tr")).not.toHaveClass("activity-row-fresh");
});

it("lädt bei verstecktem Tab nicht nach", async () => {
  const first = pageWith([entry("2026-11-20T08:00:00Z", "Anna")]);
  api.mockResolvedValue(first);
  render(<ActivityLog initialPage={first} />);
  await act(async () => { await Promise.resolve(); });
  const calls = api.mock.calls.length;
  const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  await act(async () => { await vi.advanceTimersByTimeAsync(LIVE_REFRESH_MS * 2); });
  expect(api.mock.calls.length).toBe(calls);
  visibility.mockRestore();
});
