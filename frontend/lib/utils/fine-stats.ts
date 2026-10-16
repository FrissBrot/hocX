/**
 * Bussen-Statistik nach Währung (MAIN-BE-019): Das Backend liefert pro Person bzw. Typ und
 * Währung eine Zeile. Beträge verschiedener Währungen werden nie addiert, Anzahlen schon.
 */

type CurrencyRow = { count: number; amount: number; currency?: string };
export type CurrencyTotal = { currency: string; count: number; amount: number };

/** Summen je Währung, die Währung mit den meisten Bussen zuerst. */
export function fineTotalsByCurrency(rows: CurrencyRow[]): CurrencyTotal[] {
  const totals = new Map<string, CurrencyTotal>();
  for (const row of rows) {
    const currency = row.currency ?? "";
    const total = totals.get(currency) ?? { currency, count: 0, amount: 0 };
    total.count += row.count;
    total.amount += row.amount;
    totals.set(currency, total);
  }
  return [...totals.values()].sort((a, b) => b.count - a.count || a.currency.localeCompare(b.currency));
}

/** «120.00 CHF · 30.00 EUR»; ohne Bussen nur der formatierte Nullbetrag. */
export function formatFineTotals(totals: CurrencyTotal[], formatAmount: (amount: number) => string): string {
  if (totals.length === 0) return formatAmount(0);
  return totals.map((total) => [formatAmount(total.amount), total.currency].filter(Boolean).join(" ")).join(" · ");
}

/** Anzahl Bussen je Person über alle Währungen, absteigend. */
export function fineCountsByParticipant<T extends { name: string; count: number; participant_key?: string }>(rows: T[]): { name: string; count: number }[] {
  const merged = new Map<string, { name: string; count: number }>();
  for (const row of rows) {
    const key = row.participant_key || `name:${row.name}`;
    const entry = merged.get(key) ?? { name: row.name, count: 0 };
    entry.count += row.count;
    merged.set(key, entry);
  }
  return [...merged.values()].sort((a, b) => b.count - a.count);
}

/** Anzahl je Bussentyp über alle Währungen (Beträge entfallen, siehe oben). */
export function fineCountsByType<T extends { fine_type: string; label: string; count: number }>(rows: T[]): { fine_type: string; label: string; count: number }[] {
  const merged = new Map<string, { fine_type: string; label: string; count: number }>();
  for (const row of rows) {
    const entry = merged.get(row.fine_type) ?? { fine_type: row.fine_type, label: row.label, count: 0 };
    entry.count += row.count;
    merged.set(row.fine_type, entry);
  }
  return [...merged.values()];
}
