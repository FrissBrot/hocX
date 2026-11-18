import { FileOverviewItem } from "@/types/api";

/**
 * Geladene Tage der Zeitleiste in die Liste übernehmen: die Fotos dieser Tage ersetzen, was bisher
 * zu ihnen geladen war (in Serverreihenfolge), alles bleibt nach Tag sortiert - in derselben
 * Richtung wie die Zeitleiste, damit die Bildansicht in derselben Reihenfolge blättert.
 */
export function mergeTimelineDays(
  current: FileOverviewItem[],
  days: string[],
  loaded: FileOverviewItem[],
  sortDir: "asc" | "desc",
): FileOverviewItem[] {
  const replaced = new Set(days);
  const dayOf = (item: FileOverviewItem) => item.group_date ?? item.created_at.slice(0, 10);
  const loadedIds = new Set(loaded.map((item) => item.id));
  const kept = current.filter((item) => !replaced.has(dayOf(item)) && !loadedIds.has(item.id));
  const merged = [...kept, ...loaded];
  // Array.prototype.sort ist stabil: innerhalb eines Tages bleibt die Serverreihenfolge
  return merged.sort((a, b) => (sortDir === "asc" ? dayOf(a).localeCompare(dayOf(b)) : dayOf(b).localeCompare(dayOf(a))));
}
