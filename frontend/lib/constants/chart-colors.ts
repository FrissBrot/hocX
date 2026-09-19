/**
 * Gemeinsame Diagrammfarben fuer Statistik-Seite und Protokoll-Diagramme.
 * Bedeutungsfarben folgen den Status-Tokens (wechseln mit Light/Dark), kategoriale
 * Farben den --chart-*-Tokens aus design/tokens.css.
 */
export const CHART_COLORS = {
  present: "var(--success)",
  absent: "var(--danger)",
  excused: "var(--warning)",
  income: "var(--success)",
  expenses: "var(--danger)",
  done: "var(--success)",
  open: "var(--border-strong)",
  fines: "var(--warning)",
  sessions: "var(--chart-1)",
  participants: "var(--chart-2)",
} as const;

export const CHART_PIE_PALETTE = [
  "var(--chart-1)",
  "var(--success)",
  "var(--warning)",
  "var(--danger)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
] as const;
