/**
 * Rechenlogik der Statistik (Dashboard v2) für Desktop und Mobile: aus GET /statistics/overview
 * die Werte der Kennzahlen und Diagramme bilden. Ohne React, damit beide Ansichten dieselben
 * Zahlen zeigen und die Regeln getestet werden können (statistics-model.test.ts).
 */
import type { StatisticsAttendanceMonth, StatisticsFineByPerson, StatisticsOverview } from "@/types/api";
import { fineTotalsByCurrency, type CurrencyTotal } from "@/lib/utils/fine-stats";
import { toIntlLocale } from "@/lib/utils/format";

export type AttendanceCounts = { present: number; late: number; excused: number; absent: number; total: number };

const EMPTY: AttendanceCounts = { present: 0, late: 0, excused: 0, absent: 0, total: 0 };

export function countsOf(row: Partial<StatisticsAttendanceMonth> | null | undefined): AttendanceCounts {
  if (!row) return { ...EMPTY };
  return { present: row.present ?? 0, late: row.late ?? 0, excused: row.excused ?? 0, absent: row.absent ?? 0, total: row.total ?? 0 };
}

export function sumAttendance(rows: Partial<StatisticsAttendanceMonth>[]): AttendanceCounts {
  return rows.reduce<AttendanceCounts>((sum, row) => {
    const c = countsOf(row);
    return { present: sum.present + c.present, late: sum.late + c.late, excused: sum.excused + c.excused, absent: sum.absent + c.absent, total: sum.total + c.total };
  }, { ...EMPTY });
}

/** Anwesenheitsquote: anwesend oder verspätet im Verhältnis zu allen Einträgen; null ohne Daten. */
export function attendanceRate(c: AttendanceCounts): number | null {
  return c.total > 0 ? (c.present + c.late) / c.total : null;
}

/** Monate des gewählten Jahres als «JJJJ-MM»: im laufenden Jahr bis zum aktuellen Monat. */
export function yearMonths(year: number, todayIso: string): string[] {
  const [todayYear, todayMonth] = todayIso.split("-").map(Number);
  const last = year === todayYear ? todayMonth : 12;
  return Array.from({ length: last }, (_, index) => `${year}-${String(index + 1).padStart(2, "0")}`);
}

export type AttendanceBar = {
  month: string;
  /** Anteile 0–1 je Status (zusammen 1, ohne Daten 0) */
  present: number;
  late: number;
  excused: number;
  absent: number;
  rate: number | null;
  /** Quote im selben Monat des Vorjahres, wenn verglichen wird */
  previousRate: number | null;
};

export function attendanceBars(
  current: StatisticsAttendanceMonth[],
  previous: StatisticsAttendanceMonth[] | null,
  months: string[],
): AttendanceBar[] {
  const byMonth = new Map(current.map((row) => [row.month, countsOf(row)]));
  const previousByMonth = new Map((previous ?? []).map((row) => [row.month.slice(5), countsOf(row)]));
  return months.map((month) => {
    const c = byMonth.get(month) ?? { ...EMPTY };
    const share = (value: number) => (c.total > 0 ? value / c.total : 0);
    const prev = previous ? previousByMonth.get(month.slice(5)) : undefined;
    return {
      month,
      present: share(c.present),
      late: share(c.late),
      excused: share(c.excused),
      absent: share(c.absent),
      rate: attendanceRate(c),
      previousRate: prev ? attendanceRate(prev) : null,
    };
  });
}

export type MemberRow = { name: string; present: number; late: number; excused: number; absent: number; rate: number };

export function memberRows(rows: StatisticsOverview["attendance_by_participant"], sort: "low" | "high"): MemberRow[] {
  return rows
    .map((row) => {
      const c = countsOf(row);
      const share = (value: number) => (c.total > 0 ? value / c.total : 0);
      return { name: row.name, present: share(c.present), late: share(c.late), excused: share(c.excused), absent: share(c.absent), rate: attendanceRate(c) ?? 0 };
    })
    .filter((row) => row.present + row.late + row.excused + row.absent > 0)
    .sort((a, b) => (sort === "low" ? a.rate - b.rate : b.rate - a.rate) || a.name.localeCompare(b.name));
}

/** Schwelle, unter der eine Quote als tief gilt (Hinweis unter «Mitglieder nach Quote»). */
export const LOW_ATTENDANCE_RATE = 0.7;

export type FinePersonRow = { key: string; name: string; absent: number; late: number; count: number; totals: CurrencyTotal[] };

/** Bussen je Person über alle Währungen zusammengeführt (Anzahlen addiert, Beträge je Währung). */
export function finesByPerson(rows: StatisticsFineByPerson[]): FinePersonRow[] {
  const merged = new Map<string, { key: string; name: string; absent: number; late: number; count: number; rows: StatisticsFineByPerson[] }>();
  for (const row of rows) {
    const key = row.participant_key || `name:${row.name}`;
    const entry = merged.get(key) ?? { key, name: row.name, absent: 0, late: 0, count: 0, rows: [] };
    entry.absent += row.absent_count ?? 0;
    entry.late += row.late_count ?? 0;
    entry.count += row.count;
    entry.rows.push(row);
    merged.set(key, entry);
  }
  return [...merged.values()]
    .map(({ rows: personRows, ...entry }) => ({ ...entry, totals: fineTotalsByCurrency(personRows) }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

export type FineTypeRow = { fineType: "absent" | "late" | string; count: number; totals: CurrencyTotal[] };

/** Bussen nach Art (je Art eine Zeile, Beträge je Währung). Für die eigene Sicht aus den eigenen Zeilen. */
export function fineTypeRows(data: Pick<StatisticsOverview, "fines_by_type" | "fines_by_participant" | "per_person_scope">): FineTypeRow[] {
  if (data.per_person_scope === "own") {
    const own = data.fines_by_participant;
    const rows: FineTypeRow[] = [
      { fineType: "absent", count: own.reduce((s, r) => s + (r.absent_count ?? 0), 0), totals: fineTotalsByCurrency(own.map((r) => ({ count: r.absent_count ?? 0, amount: r.absent_amount ?? 0, currency: r.currency }))) },
      { fineType: "late", count: own.reduce((s, r) => s + (r.late_count ?? 0), 0), totals: fineTotalsByCurrency(own.map((r) => ({ count: r.late_count ?? 0, amount: r.late_amount ?? 0, currency: r.currency }))) },
    ];
    return rows.filter((row) => row.count > 0);
  }
  const byType = new Map<string, StatisticsOverview["fines_by_type"]>();
  for (const row of data.fines_by_type) byType.set(row.fine_type, [...(byType.get(row.fine_type) ?? []), row]);
  return [...byType.entries()]
    .map(([fineType, rows]) => ({ fineType, count: rows.reduce((s, r) => s + r.count, 0), totals: fineTotalsByCurrency(rows) }))
    .sort((a, b) => b.count - a.count);
}

/** Summe der Bussen (eigene Sicht: nur die eigenen) je Währung. */
export function fineSum(data: Pick<StatisticsOverview, "fines_by_type" | "fines_by_participant" | "per_person_scope">): CurrencyTotal[] {
  return fineTotalsByCurrency(data.per_person_scope === "own" ? data.fines_by_participant : data.fines_by_type);
}

/** Hauptwährung (die mit den meisten Bussen) - Balkenlängen vergleichen nur Beträge einer Währung. */
export function mainAmount(totals: CurrencyTotal[]): number {
  return totals[0]?.amount ?? 0;
}

export type FinanceMonth = { month: string; income: number; expenses: number; net: number };
export type FinanceView = {
  accounts: { id: string; name: string }[];
  months: FinanceMonth[];
  income: number;
  expenses: number;
  net: number;
  /** Währung, wenn alle gezeigten Konten dieselbe haben, sonst null (nie falsch «CHF») */
  currency: string | null;
  /** Grösster Betrag |Ergebnis| eines Monats, aufgerundet - Skala des Diagramms */
  scale: number;
  previous: { income: number; expenses: number; net: number } | null;
};

function niceScale(max: number): number {
  if (max <= 0) return 0;
  const magnitude = 10 ** Math.floor(Math.log10(max));
  const step = magnitude / 2;
  return Math.ceil(max / step) * step;
}

export function financeView(data: Pick<StatisticsOverview, "finance_by_month" | "comparison">, account: string, months: string[]): FinanceView {
  const accounts = new Map<string, string>();
  for (const row of data.finance_by_month) accounts.set(row.account_id, row.account_name);
  const rows = data.finance_by_month.filter((row) => account === "all" || row.account_id === account);
  const byMonth = new Map<string, FinanceMonth>();
  for (const row of rows) {
    const entry = byMonth.get(row.month) ?? { month: row.month, income: 0, expenses: 0, net: 0 };
    entry.income += row.income;
    entry.expenses += row.expenses;
    entry.net = entry.income - entry.expenses;
    byMonth.set(row.month, entry);
  }
  const monthRows = months.map((month) => byMonth.get(month) ?? { month, income: 0, expenses: 0, net: 0 });
  const income = rows.reduce((s, r) => s + r.income, 0);
  const expenses = rows.reduce((s, r) => s + r.expenses, 0);
  const currencies = [...new Set(rows.map((row) => row.currency ?? ""))];
  const previousRows = (data.comparison?.finance_by_account ?? []).filter((row) => account === "all" || row.account_id === account);
  const previous = data.comparison
    ? { income: previousRows.reduce((s, r) => s + r.income, 0), expenses: previousRows.reduce((s, r) => s + r.expenses, 0), net: 0 }
    : null;
  if (previous) previous.net = previous.income - previous.expenses;
  return {
    accounts: [...accounts.entries()].map(([id, name]) => ({ id, name })),
    months: monthRows,
    income,
    expenses,
    net: income - expenses,
    currency: currencies.length === 1 ? currencies[0] || null : null,
    scale: niceScale(Math.max(0, ...monthRows.map((row) => Math.abs(row.net)))),
    previous,
  };
}

export type GroupRow = { name: string; sessions: number; withParticipants: number; avgParticipants: number };

/**
 * Gruppen über alle Zyklen des Zeitraums zusammengeführt, Ø Teilnehmende gewichtet mit der Zahl
 * der Termine mit erfasster Teilnehmerzahl. KEEP IN SYNC BY HAND mit aggregate_group_rows in
 * backend/app/services/statistics_common.py (2026-08-13 audit, M11).
 */
export function groupRows(stats: StatisticsOverview["groups_stats"]): GroupRow[] {
  const merged = new Map<string, { sessions: number; withParticipants: number; weighted: number }>();
  for (const g of stats) {
    const entry = merged.get(g.group_name) ?? { sessions: 0, withParticipants: 0, weighted: 0 };
    entry.sessions += g.session_count;
    entry.withParticipants += g.session_count_with_participants;
    entry.weighted += g.avg_participants * g.session_count_with_participants;
    merged.set(g.group_name, entry);
  }
  return [...merged.entries()]
    .map(([name, v]) => ({
      name,
      sessions: v.sessions,
      withParticipants: v.withParticipants,
      avgParticipants: v.withParticipants > 0 ? Math.round((v.weighted / v.withParticipants) * 10) / 10 : 0,
    }))
    .sort((a, b) => b.sessions - a.sessions || a.name.localeCompare(b.name));
}

export type Trend = "up" | "down" | "flat";

/** Richtung einer Veränderung; «good» sagt, ob sie für den Verein gut ist (Bussen: weniger ist gut). */
export function trendOf(current: number, previous: number, higherIsBetter = true): { trend: Trend; good: boolean } {
  const diff = current - previous;
  if (Math.abs(diff) < 1e-9) return { trend: "flat", good: true };
  return { trend: diff > 0 ? "up" : "down", good: diff > 0 === higherIsBetter };
}

/** Pfad der Statistik eines Kalenderjahres (Dashboard v2), optional mit Vorjahresvergleich. */
export function statisticsPath(year: number, compare: boolean, cached = false): string {
  const params = new URLSearchParams({ year: String(year) });
  if (compare) params.set("compare", "true");
  if (cached) params.set("cached", "true");
  return `/api/statistics/overview?${params.toString()}`;
}

/** Erster und letzter Monat eines Zeitraums als ISO-Monat (für «Jan – Nov 2025»). */
export function periodMonths(start: string | null | undefined, end: string | null | undefined): { start: string; end: string } | null {
  if (!start || !end) return null;
  return { start: start.slice(0, 7), end: end.slice(0, 7) };
}

export function monthLabel(month: string, locale: string, style: "short" | "narrow" = "short"): string {
  return new Intl.DateTimeFormat(toIntlLocale(locale), { month: style }).format(new Date(`${month}-01T12:00:00`)).replace(".", "");
}

export function percentLabel(value: number | null, locale: string): string {
  if (value === null) return "–";
  return new Intl.NumberFormat(toIntlLocale(locale), { style: "percent", maximumFractionDigits: 0 }).format(value);
}
