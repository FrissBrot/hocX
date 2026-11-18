import { describe, expect, it } from "vitest";

import { mergeTimelineDays } from "./timeline-merge";
import type { FileOverviewItem } from "@/types/api";

const item = (id: string, day: string) => ({ id, group_date: day, created_at: `${day}T10:00:00Z` }) as FileOverviewItem;

describe("mergeTimelineDays", () => {
  it("ersetzt geladene Tage und hält die Liste nach Tag sortiert", () => {
    const current = [item("a", "2026-06-03"), item("b", "2025-01-01"), item("old", "2024-05-01")];
    const merged = mergeTimelineDays(current, ["2024-05-01"], [item("c2", "2024-05-01"), item("c1", "2024-05-01")], "desc");
    expect(merged.map((entry) => entry.id)).toEqual(["a", "b", "c2", "c1"]);
  });

  it("verschiebt ein Foto mit geändertem Datum ohne Doppel", () => {
    const current = [item("x", "2026-06-03"), item("y", "2026-06-03")];
    const merged = mergeTimelineDays(current, ["2026-06-02"], [item("y", "2026-06-02")], "asc");
    expect(merged.map((entry) => `${entry.id}:${entry.group_date}`)).toEqual(["y:2026-06-02", "x:2026-06-03"]);
  });
});
