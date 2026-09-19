import { FileOverviewItem } from "@/types/api";

// Adds the items of `latest` (a freshly fetched first page, in server order) that `current`
// doesn't know yet, and leaves every already-shown item exactly where it is - so a background
// sync never reshuffles, drops or re-renders what the user is looking at. Each new item is
// placed right after its nearest predecessor in `latest` that is already in the list, or at
// the very top if it has none. Returns `current` itself (same reference) when nothing is new,
// so setState bails out without a render.
export function mergeNewItems(current: FileOverviewItem[], latest: FileOverviewItem[]): FileOverviewItem[] {
  const known = new Set(current.map((item) => item.id));
  if (latest.every((item) => known.has(item.id))) return current;

  const merged = [...current];
  let anchorId: string | null = null;
  for (const item of latest) {
    if (known.has(item.id)) {
      anchorId = item.id;
      continue;
    }
    const anchorIndex = anchorId === null ? -1 : merged.findIndex((existing) => existing.id === anchorId);
    merged.splice(anchorIndex + 1, 0, item);
    known.add(item.id);
    anchorId = item.id;
  }
  return merged;
}
