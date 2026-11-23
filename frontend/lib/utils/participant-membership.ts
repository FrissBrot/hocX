import { appCalendarDate } from "@/lib/utils/format";

/** Ein- und Austrittsdatum gehören beide noch zur Mitgliedschaft. */
export function participantEligibleOn(
  participant: { joined_at?: string | null; left_at?: string | null },
  asOf: string,
): boolean {
  return (!participant.joined_at || participant.joined_at <= asOf)
    && (!participant.left_at || participant.left_at >= asOf);
}

export function localDateToday(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

/** «Heute» für Ein-/Austrittsdaten wie im Backend (Participant.has_left): Kalendertag in
 * Schweizer Zeit. Nicht `toISOString()` - das ist der UTC-Tag und hinkt zwischen Mitternacht und
 * 01:00/02:00 einen Tag hinterher (Ausgetretene erschienen dann noch als Mitglied). */
export function swissDateToday(now: Date = new Date()): string {
  return appCalendarDate(now);
}
