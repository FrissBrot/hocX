// Antworten von GET /api/admin/analytics/{series} (backend/app/api/routes/admin_analytics.py).

export type AnalyticsRange = "30d" | "90d" | "12m";
export type AnalyticsSeriesKey = "growth" | "usage" | "features" | "revenue" | "load" | "storage" | "errors";

export type AnalyticsPoint = { bucket: string; values: Record<string, number> };

export type AnalyticsSeries = {
  series: AnalyticsSeriesKey;
  range: AnalyticsRange;
  bucket: "day" | "month";
  metrics: string[];
  collecting_since: string | null;
  points: AnalyticsPoint[];
  top_tenants?: { tenant_id: string; name: string; bytes: number }[];
};

export type AnalyticsFeatures = {
  series: "features";
  range: AnalyticsRange;
  collecting_since: string | null;
  as_of: string | null;
  tenants_total: number;
  items: { code: string; tenants: number; share: number | null }[];
};
