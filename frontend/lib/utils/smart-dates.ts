// Smarte Datumsvorschläge für die Fälligkeits-Menüs: nichts wird von sich aus angeboten, erst
// wenn das Getippte passt ("mor" → Morgen, "fr" → Freitag diese/nächste Woche, "in 3" → in
// 3 Tagen/Wochen/Monaten, "24.12" → 24.12.). Die Kandidaten rechnet diese Datei aus, die
// Beschriftung kommt aus den Übersetzungen (todos.smartDate.*), damit jede Sprache passt.
// Woche = Montag bis Sonntag (wie TODO_DUE_PRESETS "endOfWeek").

export const SMART_DATE_KINDS = [
  "today",
  "tomorrow",
  "dayAfterTomorrow",
  "weekdayThisWeek",
  "weekdayNextWeek",
  "weekdayNext",
  "endOfWeek",
  "startOfNextWeek",
  "endOfNextWeek",
  "inTwoWeeks",
  "endOfMonth",
  "startOfNextMonth",
  "endOfNextMonth",
  "endOfYear",
  "inDays",
  "inWeeks",
  "inMonths",
  "exactDate",
] as const;

export type SmartDateKind = (typeof SMART_DATE_KINDS)[number];

export type SmartDateCandidate = {
  kind: SmartDateKind;
  /** ISO-Datum JJJJ-MM-TT */
  date: string;
  /** 1 = Montag … 7 = Sonntag (nur weekday*) */
  weekday?: number;
  /** Anzahl (nur in*) */
  count?: number;
};

const MAX_COUNT = 999;

function iso(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

/** Kalendertage lokal rechnen (Sommerzeit verschiebt so nichts). */
function addDays(base: Date, days: number): Date {
  return new Date(base.getFullYear(), base.getMonth(), base.getDate() + days);
}

/** Monate addieren, Monatsende statt Überlauf (31.01. + 1 Monat = 28./29.02.). */
function addMonths(base: Date, months: number): Date {
  const target = new Date(base.getFullYear(), base.getMonth() + months, 1);
  const lastDay = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
  return new Date(target.getFullYear(), target.getMonth(), Math.min(base.getDate(), lastDay));
}

/** 1 = Montag … 7 = Sonntag */
function isoWeekday(date: Date): number {
  return ((date.getDay() + 6) % 7) + 1;
}

function parseExactDate(query: string, today: Date): string | null {
  const match = query.trim().match(/^(\d{1,2})\.(\d{1,2})\.?(\d{2}|\d{4})?$/);
  if (!match) return null;
  const day = Number(match[1]);
  const month = Number(match[2]);
  let year = match[3] ? Number(match[3]) : today.getFullYear();
  if (match[3] && match[3].length === 2) year += 2000;
  const candidate = new Date(year, month - 1, day);
  if (candidate.getMonth() !== month - 1 || candidate.getDate() !== day) return null;
  // Ohne Jahr: das nächste Vorkommen (heute zählt mit)
  if (!match[3] && candidate < new Date(today.getFullYear(), today.getMonth(), today.getDate())) {
    return iso(new Date(year + 1, month - 1, day));
  }
  return iso(candidate);
}

/** Alle Kandidaten für die Eingabe, in der Reihenfolge, in der sie angeboten werden. */
export function smartDateCandidates(query: string, now = new Date()): SmartDateCandidate[] {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const weekday = isoWeekday(today);
  const startOfThisWeek = addDays(today, 1 - weekday);
  const result: SmartDateCandidate[] = [
    { kind: "today", date: iso(today) },
    { kind: "tomorrow", date: iso(addDays(today, 1)) },
    { kind: "dayAfterTomorrow", date: iso(addDays(today, 2)) },
  ];
  for (let day = 1; day <= 7; day += 1) {
    if (day >= weekday) result.push({ kind: "weekdayThisWeek", weekday: day, date: iso(addDays(startOfThisWeek, day - 1)) });
  }
  for (let day = 1; day <= 7; day += 1) {
    result.push({ kind: "weekdayNextWeek", weekday: day, date: iso(addDays(startOfThisWeek, day + 6)) });
  }
  for (let day = 1; day <= 7; day += 1) {
    const ahead = (day - weekday + 7) % 7 || 7;
    result.push({ kind: "weekdayNext", weekday: day, date: iso(addDays(today, ahead)) });
  }
  result.push(
    { kind: "endOfWeek", date: iso(addDays(startOfThisWeek, 6)) },
    { kind: "startOfNextWeek", date: iso(addDays(startOfThisWeek, 7)) },
    { kind: "endOfNextWeek", date: iso(addDays(startOfThisWeek, 13)) },
    { kind: "inTwoWeeks", date: iso(addDays(today, 14)) },
    { kind: "endOfMonth", date: iso(new Date(today.getFullYear(), today.getMonth() + 1, 0)) },
    { kind: "startOfNextMonth", date: iso(new Date(today.getFullYear(), today.getMonth() + 1, 1)) },
    { kind: "endOfNextMonth", date: iso(new Date(today.getFullYear(), today.getMonth() + 2, 0)) },
    { kind: "endOfYear", date: iso(new Date(today.getFullYear(), 11, 31)) },
  );
  const number = query.match(/\d+/);
  const count = number ? Number(number[0]) : 0;
  if (count > 0 && count <= MAX_COUNT && !/\d+\.\d/.test(query)) {
    result.push(
      { kind: "inDays", count, date: iso(addDays(today, count)) },
      { kind: "inWeeks", count, date: iso(addDays(today, count * 7)) },
      { kind: "inMonths", count, date: iso(addMonths(today, count)) },
    );
  }
  const exact = parseExactDate(query, today);
  if (exact) result.unshift({ kind: "exactDate", date: exact });
  return result;
}

/** Kleinbuchstaben ohne Akzente/Umlaute ("Übermorgen" → "ubermorgen", "ß" → "ss"). */
export function normalizeSearchText(value: string): string {
  return value.toLowerCase().replace(/ß/g, "ss").normalize("NFD").replace(/[̀-ͯ]/g, "");
}

function words(value: string): string[] {
  return normalizeSearchText(value).split(/[^a-z0-9]+/).filter(Boolean);
}

/** Jedes getippte Wort ist der Anfang eines Wortes im Text ("fr di" passt auf "Freitag diese Woche"). */
export function matchesSmartQuery(text: string, query: string): boolean {
  const queryWords = words(query);
  if (!queryWords.length) return false;
  const textWords = words(text);
  return queryWords.every((queryWord) => textWords.some((word) => word.startsWith(queryWord)));
}

export type SmartDateText = { label: string; /** zusätzliche Suchbegriffe, z. B. "Wochenende" */ keywords?: string };

/**
 * Passende Vorschläge: Kandidaten, deren Beschriftung (plus Suchbegriffe) zum Getippten passt,
 * je Datum nur der erste, höchstens ``limit``. Leere Eingabe → keine Vorschläge.
 */
export function smartDateSuggestions(
  query: string,
  describe: (candidate: SmartDateCandidate) => SmartDateText,
  { now = new Date(), limit = 6 }: { now?: Date; limit?: number } = {}
): Array<SmartDateCandidate & { label: string }> {
  if (!query.trim()) return [];
  const seen = new Set<string>();
  const result: Array<SmartDateCandidate & { label: string }> = [];
  for (const candidate of smartDateCandidates(query, now)) {
    const { label, keywords = "" } = describe(candidate);
    if (candidate.kind !== "exactDate" && !matchesSmartQuery(`${label} ${keywords}`, query)) continue;
    if (seen.has(candidate.date)) continue;
    seen.add(candidate.date);
    result.push({ ...candidate, label });
    if (result.length >= limit) break;
  }
  return result;
}
