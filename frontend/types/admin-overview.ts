// Typen der Admin-Übersicht (GET /api/admin/overview, /overview/series, /nav-counts, POST /search).
// Backend: app/services/admin_overview_service.py

export type ProblemSeverity = "critical" | "warning" | "info";

export type OverviewProblem = {
  key: string;
  source: string;
  subject: string;
  reason: string;
  severity: ProblemSeverity;
};

/** Eingaben der Statusregel (Plan §3.2); abgeleitet wird im Frontend (derivePlatformStatus). */
export type OverviewSystemStatus = {
  snapshot_at: string | null;
  stale: boolean;
  docker_unavailable: boolean;
  critical: number;
  warning: number;
  maintenance_active: boolean;
  maintenance_started_at: string | null;
  runtime_warning: boolean;
  overload_recent: number;
  problems: OverviewProblem[];
};

export type CountWithPrevious = { value: number; previous: number };

export type OverviewTodoKey =
  | "verifications"
  | "rebooking"
  | "overdueCharges"
  | "unhealthyDomains"
  | "storageHot"
  | "jobs"
  | "backups";

export type OverviewTodo = {
  key: OverviewTodoKey;
  count: number;
  href: string;
  severity: "info" | "warning" | "critical";
  params: Record<string, string | number>;
};

export type OverviewFeedItem = {
  id: string;
  kind: "admin" | "system";
  at: string;
  action: string;
  outcome: string | null;
  severity: string;
  tenant: string | null;
  actor: string | null;
  subject: string | null;
  href: string;
};

export type AdminOverview = {
  generated_at: string;
  role: "owner" | "support";
  /** null für support (Quelle nur owner) */
  status: OverviewSystemStatus | null;
  kpis: {
    tenants: { value: number; new_30d: number };
    active_users_30d: CountWithPrevious;
    mrr: { value_rp: number; paying_tenants: number; previous_month_income_rp: number | null; overdue_count: number };
    errors_24h: CountWithPrevious | null;
    login_failures_24h: CountWithPrevious | null;
  };
  todos: OverviewTodo[];
  feed: OverviewFeedItem[] | null;
};

export type OverviewRange = "24h" | "7d" | "30d" | "90d";

export type OverviewSeriesPoint = { bucket: string; success?: number; failure?: number; errors?: number };

export type OverviewSeries = {
  kind: "logins" | "errors";
  range: OverviewRange;
  bucket_hours: number;
  points: OverviewSeriesPoint[];
  top_types: { error_type: string; count: number }[];
};

export type AdminNavCounts = {
  tenants: number;
  verifications_open: number;
  security_alerts: number | null;
  operations_problems: number | null;
};

export type AdminSearchGroupKey = "tenants" | "users" | "domains" | "jobs" | "checks" | "audit";

export type AdminSearchItem = { id: string; label: string; sublabel: string | null; href: string };

export type AdminSearchResponse = { groups: { group: AdminSearchGroupKey; items: AdminSearchItem[] }[] };
