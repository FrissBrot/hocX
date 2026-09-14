import { FileOverviewItem } from "@/types/api";

export type PhotoDateGroup = {
  key: string;
  date: string;
  contextLabel: string | undefined;
  items: FileOverviewItem[];
};

function mostFrequent(values: string[]): string | undefined {
  if (values.length === 0) return undefined;
  const counts = new Map<string, number>();
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1);
  let best: string | undefined;
  let bestCount = 0;
  for (const value of values) {
    const count = counts.get(value)!;
    if (count > bestCount) {
      best = value;
      bestCount = count;
    }
  }
  return best;
}

// Combines the group's auto-album name (Zyklus album only - a manual/submission album
// isn't "the" context for a date the way a Zyklus period is) with the per-item context
// label (protocol+block, word-import name, submission assignment, or event title) into
// one header string, e.g. "Sommerlager 2026 · Tag 1" or, for a protocol block with no
// album at all, just "Vorstandssitzung · Bilder im Protokoll".
function groupContextLabel(items: FileOverviewItem[]): string | undefined {
  const cycleAlbumNames = items.flatMap((item) => item.albums.filter((album) => album.kind === "cycle").map((album) => album.name));
  const albumName = mostFrequent(cycleAlbumNames);
  const contextLabels = items.map((item) => item.context_label).filter((label): label is string => Boolean(label));
  const contextLabel = mostFrequent(contextLabels);
  if (albumName && contextLabel && contextLabel !== albumName) return `${albumName} · ${contextLabel}`;
  return albumName ?? contextLabel ?? undefined;
}

// Groups a page of photos (already sorted by group_date, newest first) into contiguous
// date sections - only meaningful while sorted that way, since grouping doesn't itself
// re-sort. Each item's own group_date/context_label/albums come from the backend (see
// FileOverviewItem) rather than being re-derived here.
export function groupPhotosByDate(items: FileOverviewItem[]): PhotoDateGroup[] {
  const order: string[] = [];
  const byDate = new Map<string, FileOverviewItem[]>();
  for (const item of items) {
    const key = item.group_date ?? item.created_at.slice(0, 10);
    if (!byDate.has(key)) {
      byDate.set(key, []);
      order.push(key);
    }
    byDate.get(key)!.push(item);
  }
  return order.map((key) => {
    const groupItems = byDate.get(key)!;
    return { key, date: key, contextLabel: groupContextLabel(groupItems), items: groupItems };
  });
}
