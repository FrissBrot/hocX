// Reine Berechnungen der Foto-Zeitleiste (photo-timeline.tsx): Höhen je Tag aus der Anzahl Fotos,
// Blöcke für das Nachladen und die Markierungen des Zeitstrahls. Ohne DOM, damit testbar.

export type TimelineDay = { date: string; count: number };

export const TILE_MIN = 180;
export const TILE_MIN_NARROW = 104;
export const NARROW_WIDTH = 640;
export const GAP = 8;
export const HEADING_HEIGHT = 52;
export const DAY_GAP = 24;
export const LOAD_LIMIT = 200;

export type TimelineLayout = {
  days: TimelineDay[];
  columns: number;
  tile: number;
  offsets: number[];
  heights: number[];
  total: number;
};

/** Spalten und Kachelgrösse wie ein auto-fill-Raster mit Mindestbreite, Höhen exakt aus der Anzahl. */
export function buildTimelineLayout(days: TimelineDay[], width: number): TimelineLayout {
  const minTile = width < NARROW_WIDTH ? TILE_MIN_NARROW : TILE_MIN;
  const columns = Math.max(1, Math.floor((width + GAP) / (minTile + GAP)));
  const tile = Math.max(1, (width - GAP * (columns - 1)) / columns);
  const offsets: number[] = [];
  const heights: number[] = [];
  let top = 0;
  for (const day of days) {
    const rows = Math.max(1, Math.ceil(day.count / columns));
    const height = HEADING_HEIGHT + rows * tile + (rows - 1) * GAP;
    offsets.push(top);
    heights.push(height);
    top += height + DAY_GAP;
  }
  return { days, columns, tile, offsets, heights, total: Math.max(0, top - DAY_GAP) };
}

/** Index des Tages, der an Position `y` steht (letzter Tag mit offset <= y); -1 vor dem ersten. */
export function dayIndexAt(offsets: number[], y: number): number {
  let low = 0;
  let high = offsets.length - 1;
  let found = -1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (offsets[middle] <= y) {
      found = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return found;
}

export type LoadChunk = { days: TimelineDay[]; from: string; to: string; total: number };

/**
 * Fehlende Tage in Abfragen von höchstens LOAD_LIMIT Fotos bündeln. Ein Block umfasst nur in der
 * Zeitleiste direkt aufeinanderfolgende Tage, damit date_from/date_to keine anderen Tage miterfasst.
 * Ein einzelner Tag mit mehr Fotos bleibt ein Block (der Aufrufer blättert mit skip).
 */
export function chunkDaysForLoading(missing: TimelineDay[], allDays: TimelineDay[]): LoadChunk[] {
  const position = new Map(allDays.map((day, index) => [day.date, index]));
  const chunks: LoadChunk[] = [];
  let current: TimelineDay[] = [];
  let total = 0;
  const flush = () => {
    if (current.length === 0) return;
    const dates = current.map((day) => day.date).sort();
    chunks.push({ days: current, from: dates[0], to: dates[dates.length - 1], total });
    current = [];
    total = 0;
  };
  for (const day of missing) {
    const previous = current[current.length - 1];
    const adjacent = previous !== undefined && position.get(day.date) === (position.get(previous.date) ?? -2) + 1;
    if (current.length > 0 && (!adjacent || total + day.count > LOAD_LIMIT)) flush();
    current.push(day);
    total += day.count;
  }
  flush();
  return chunks;
}

export type ScrubberMark = { key: string; y: number; offset: number; label?: string };

/**
 * Jahresbeschriftungen und Monatspunkte auf dem Zeitstrahl, proportional zur Scrollhöhe. Zu dicht
 * liegende Marken werden ausgelassen, damit sich Beschriftungen nicht überlagern.
 */
/** `total` ist die Scrollhöhe (Inhalt minus Fensterhöhe), wie beim Cursor des Zeitstrahls. */
export function scrubberMarks(days: TimelineDay[], offsets: number[], total: number, railHeight: number) {
  const years: ScrubberMark[] = [];
  const months: ScrubberMark[] = [];
  if (railHeight <= 0 || total <= 0) return { years, months };
  const yFor = (offset: number) => Math.min(railHeight, (offset / total) * railHeight);
  let lastYear = "";
  let lastMonth = "";
  let lastYearY = -Infinity;
  let lastMonthY = -Infinity;
  days.forEach((day, index) => {
    const year = day.date.slice(0, 4);
    const month = day.date.slice(0, 7);
    const y = yFor(offsets[index]);
    if (year !== lastYear) {
      lastYear = year;
      if (y - lastYearY >= 18) {
        years.push({ key: year, y, offset: offsets[index], label: year });
        lastYearY = y;
      }
    }
    if (month !== lastMonth) {
      lastMonth = month;
      if (y - lastMonthY >= 6) {
        months.push({ key: month, y, offset: offsets[index] });
        lastMonthY = y;
      }
    }
  });
  return { years, months };
}
