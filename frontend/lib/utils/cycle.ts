/**
 * Returns the start year of the cycle that contains the given ISO date string.
 *
 * A cycle runs from the day after (resetMonth, resetDay) to that same date in
 * the following year.  Example: resetMonth=7, resetDay=31 → cycle runs Aug 1 – Jul 31.
 *
 *   "2025-08-01", 7, 31  → 2025  (new cycle started Aug 1)
 *   "2025-07-31", 7, 31  → 2024  (still in the previous cycle)
 */
export function getCycleYear(isoDate: string, resetMonth: number, resetDay: number): number {
  if (!isoDate) return new Date().getFullYear();
  const d = new Date(isoDate + "T00:00:00");
  const year = d.getFullYear();
  const boundary = new Date(year, resetMonth - 1, resetDay);
  return d > boundary ? year : year - 1;
}

export function formatCycleName(pattern: string | null | undefined, cycleYear: number): string {
  if (!pattern) return `${cycleYear}/${cycleYear + 1}`;
  return pattern
    .replace(/\[cy_end\]|\{cy_end\}/g, String(cycleYear + 1))
    .replace(/\[cy\]|\{cy\}/g, String(cycleYear));
}
