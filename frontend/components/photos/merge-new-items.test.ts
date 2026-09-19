import { describe, expect, it } from "vitest";

import { mergeNewItems } from "./merge-new-items";
import { FileOverviewItem } from "@/types/api";

const item = (id: string) => ({ id }) as FileOverviewItem;
const ids = (items: FileOverviewItem[]) => items.map((entry) => entry.id);

describe("mergeNewItems", () => {
  it("returns the same reference when nothing is new", () => {
    const current = [item("a"), item("b")];
    expect(mergeNewItems(current, [item("a"), item("b")])).toBe(current);
  });

  it("puts new items at the top when they lead the fetched page", () => {
    const merged = mergeNewItems([item("a"), item("b")], [item("n2"), item("n1"), item("a"), item("b")]);
    expect(ids(merged)).toEqual(["n2", "n1", "a", "b"]);
  });

  it("inserts a new item after its predecessor in the fetched order", () => {
    const merged = mergeNewItems([item("a"), item("b"), item("c")], [item("a"), item("n"), item("b")]);
    expect(ids(merged)).toEqual(["a", "n", "b", "c"]);
  });

  it("keeps already-loaded items untouched, including ones beyond the first page", () => {
    const current = [item("a"), item("b"), item("far")];
    const merged = mergeNewItems(current, [item("n"), item("a")]);
    expect(ids(merged)).toEqual(["n", "a", "b", "far"]);
    expect(merged[1]).toBe(current[0]);
  });
});
