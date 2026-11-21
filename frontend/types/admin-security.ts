// Antworten der Sicherheits-Endpunkte (backend app/api/routes/admin_auth_security.py und
// auth_security.py, Admin-Redesign Phase E). Pseudonyme sind immer gekürzt, IP-Adressen gibt es nie.

export type AuthOutcome = "success" | "failure" | "blocked" | "challenged" | "info";

export type AuthTimeseriesPoint = { bucket: string; failures: number; successes: number; blocked: number; challenged: number };

export type AuthTopNetwork = { src_net_hash: string | null; failures: number; accounts: number; tenants: number; last_seen: string };

export type AuthTopAccount = { subject_hash: string | null; user_id: number | null; tenant_id: number | null; failures: number; networks: number; last_seen: string };

export type AuthBlock = { subject: string; scope: "source" | "net"; until: number; reason: string; manual: boolean; stage: number; remaining_seconds: number };

export type AuthSecuritySummary = {
  timeseries: AuthTimeseriesPoint[];
  top_networks: AuthTopNetwork[];
  top_accounts: AuthTopAccount[];
  active_blocks: AuthBlock[];
};

export type AuthSecurityOverview = {
  failures_24h: number;
  failures_prev_24h: number;
  admin_logins_24h: number;
  blocked_24h: number;
  open_alerts: number;
  critical_alerts: number;
  active_blocks: number;
};

export type AuthAlert = { key: string; rule: string; subject: string | null; severity: "critical" | "warning"; title: string; message: string };

export type AuthEventRow = {
  event_id: string;
  ts: string;
  event_type: string;
  outcome: AuthOutcome;
  actor_kind: string;
  actor_user_id: number | null;
  platform_admin_id: number | null;
  tenant_id: number | null;
  subject_hash: string | null;
  src_net_hash: string | null;
  device_hash: string | null;
  risk_score: number | null;
  risk_reasons: string[];
  user_agent_family: string | null;
};

export type AuthPolicy = Record<string, Record<string, number | string | boolean>>;

// ── Mandanten-Ansicht «Sicherheit & Anmeldungen» (security.read) ──

export type TenantSecurityWarningKind = "account_attack" | "privileged_new_device" | "mfa_removed" | "account_locked";

export type TenantSecurityWarning = { kind: TenantSecurityWarningKind; user_id: string; display_name: string; count: number; last_at: string };

export type TenantSecurityAccount = { user_id: string; display_name: string; last_login: string | null; failures_7d: number; active_sessions: number };

export type TenantSecurityEvent = {
  ts: string;
  event_type: string;
  outcome: AuthOutcome;
  user_id: string | null;
  display_name: string | null;
  user_agent_family: string | null;
  risk_level: "normal" | "moderate" | "high" | "critical" | null;
};

export type TenantSecuritySummary = { failures_24h: number; accounts_with_failures_24h: number; new_device_logins_7d: number; blocked_24h: number };

export type TenantSecurityActivity = {
  summary: TenantSecuritySummary;
  warnings: TenantSecurityWarning[];
  accounts: TenantSecurityAccount[];
  events: TenantSecurityEvent[];
};
