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
  // Dashboard v2 (Statistik-Balken in app/styles/statistics.css, Klassen stats-fill-<reihe>):
  late: "var(--chart-5)",
  onTrack: "var(--chart-1)",
  paid: "var(--success)",
  finesOpen: "var(--warning)",
  surplus: "var(--success)",
  deficit: "var(--danger)",
  previous: "var(--text)",
  // Admin-Übersicht (Dashboard-Diagramme Anmeldungen/Fehler, Plan §3.4)
  loginSuccess: "var(--success)",
  loginFailure: "var(--danger)",
  errors: "var(--danger)",
  // Sicherheitsbereich des Plattform-Admins (Anmeldungen: Fehlversuch/gesperrt/erfolgreich)
  securityFailures: "var(--danger)",
  securityBlocked: "var(--warning)",
  securitySuccesses: "var(--success)",
  // Admin-Analysen (Plattform-Admin, Seite Analysen)
  analyticsTenants: "var(--chart-1)",
  analyticsUsers: "var(--chart-2)",
  analyticsNew: "var(--chart-3)",
  analyticsRevenue: "var(--success)",
  analyticsStorage: "var(--chart-4)",
  analyticsLoad: "var(--chart-5)",
  analyticsErrors: "var(--danger)",
  analyticsLoginFailure: "var(--danger)",
  analyticsLoginSuccess: "var(--success)",
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
