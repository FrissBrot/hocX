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

// "2026-07-03" -> whole days between two ISO date strings (UTC midnight, so DST never
// throws the count off by one) - used to turn a multi-day Termin's [ref_date, ref_end_date]
// range plus this section's own groupDate into a 1-based "Tag N".
function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000);
}

// The group's "Tag N" within its linked Termin's range, when that Termin spans more than
// one day - undefined for a single-day Termin or a group with no linked Termin at all.
// Most-frequent (ref_date, ref_end_date) pair among the group's items, the same
// vote-by-majority approach groupContextLabel uses for context_label/album name, in case a
// date section ever mixes linked and unlinked photos.
function multiDayTagLabel(items: FileOverviewItem[], groupDate: string): string | undefined {
  const ranges = items
    .filter((item) => item.ref_date && item.ref_end_date && item.ref_end_date > item.ref_date)
    .map((item) => `${item.ref_date}|${item.ref_end_date}`);
  const chosen = mostFrequent(ranges);
  if (!chosen) return undefined;
  const [refDate] = chosen.split("|");
  const dayIndex = daysBetween(refDate, groupDate) + 1;
  return dayIndex >= 1 ? `Tag ${dayIndex}` : undefined;
}

// Combines the group's auto-album name (Zyklus album only - a manual/submission album
// isn't "the" context for a date the way a Zyklus period is) with the per-item context
// label (protocol+block, word-import name, submission assignment, or event title) into
// one header string, e.g. "Vorstandssitzung · Bilder im Protokoll". When the group's photos
// are linked to a multi-day Termin, appends that day's index within it, e.g.
// "Sommerlager 2026, Tag 2".
function groupContextLabel(items: FileOverviewItem[], groupDate: string): string | undefined {
  const cycleAlbumNames = items.flatMap((item) => item.albums.filter((album) => album.kind === "cycle").map((album) => album.name));
  const albumName = mostFrequent(cycleAlbumNames);
  const contextLabels = items.map((item) => item.context_label).filter((label): label is string => Boolean(label));
  const contextLabel = mostFrequent(contextLabels);
  const base = albumName && contextLabel && contextLabel !== albumName ? `${albumName} · ${contextLabel}` : albumName ?? contextLabel ?? undefined;
  if (!base) return undefined;
  const dayLabel = multiDayTagLabel(items, groupDate);
  return dayLabel ? `${base}, ${dayLabel}` : base;
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
    return { key, date: key, contextLabel: groupContextLabel(groupItems, key), items: groupItems };
  });
}
