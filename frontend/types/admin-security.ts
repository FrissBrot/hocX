// Antworten der Sicherheits-Endpunkte (backend app/api/routes/admin_auth_security.py und
// auth_security.py, Admin-Redesign Phase E). Pseudonyme sind immer gekürzt, IP-Adressen gibt es nie.

export type AuthOutcome = "success" | "failure" | "blocked" | "challenged" | "info";

export type AuthTimeseriesPoint = { bucket: string; failures: number; successes: number; blocked: number; challenged: number };

export type AuthTopNetwork = { src_net_hash: string | null; failures: number; accounts: number; tenants: number; last_seen: string };

export type AuthTopAccount = { subject_hash: string | null; user_id: number | null; tenant_id: number | null; failures: number; networks: number; last_seen: string };

export type AuthBlockScope = "source" | "net" | "net_fp";

/** Aktive Sperre (1.6: Beginn, Dauer, Abgewiesen-Zähler, setzender Admin). `subject` ist der
 * Schlüssel für Aufheben/Verlängern, angezeigt wird nur `short`. */
export type AuthBlock = {
  subject: string;
  short: string;
  scope: AuthBlockScope;
  until: number;
  reason: string;
  manual: boolean;
  stage: number;
  remaining_seconds: number;
  created: number;
  minutes: number;
  admin_id: number | null;
  admin_name: string | null;
  incident_id: number | null;
  repeat: number;
  rejected: number;
};

/** GET /api/admin/auth-security/blocks/ladder */
export type AuthDefenseLadder = {
  events_24h: { observed: number; limited: number; challenged: number };
  automatic: number;
  manual: number;
  strikes: number;
  durations: number[];
  max_automatic_minutes: number;
  max_manual_minutes: number;
};

export type AuthBlockHistoryBar = {
  start: string;
  end: string;
  minutes: number;
  manual: boolean;
  stage: number | null;
  reason: string | null;
  cleared: boolean;
  replaced: boolean;
};

/** GET /api/admin/auth-security/blocks/history (7 Tage) */
export type AuthBlockHistory = {
  start: string;
  end: string;
  sources: { subject: string; scope: AuthBlockScope | null; country: string | null; bars: AuthBlockHistoryBar[] }[];
};

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
  active_alerts: number;
  critical_alerts: number;
  open_incidents: number;
  new_incidents: number;
  active_blocks: number;
};

export type AuthAlert = {
  key: string;
  rule: string;
  subject: string | null;
  severity: "critical" | "warning";
  title: string;
  message: string;
  /** Letztes auslösendes Ereignis, Fenster der Regel und wann sie ohne neues Ereignis abklingt (1.5.1) */
  last_at?: string | null;
  window_minutes?: number;
  clears_at?: string | null;
  /** Name statt interner ID bei Admin-/Mandanten-Regeln (nur owner sieht Warnungen) */
  subject_label?: string | null;
  /** Zugehöriger Vorfall (1.7, ersetzt die Quittung aus 1.5.1): offener, sonst jüngster */
  incident?: { id: number; status: IncidentStatus; assignee: string | null } | null;
};

/** POST /api/admin/auth-security/events/{id}/resolve-subject */
export type ResolvedSubject = {
  kind: "user" | "admin" | "unknown";
  via: "event" | "related_event" | "hash" | "none";
  user_id: string | null;
  admin_id: string | null;
  display_name: string | null;
  email: string | null;
  tenant_id: string | null;
  tenant_name: string | null;
  login_enabled: boolean | null;
  is_active: boolean | null;
};

/** Zeile der Ereignisliste (1.6): Pseudonyme gekürzt (12 Zeichen), Mandant als öffentliche ID + Name. */
export type AuthEventRow = {
  event_id: string;
  ts: string;
  event_type: string;
  outcome: AuthOutcome;
  actor_kind: string;
  platform_admin_id: number | null;
  tenant_id: string | null;
  tenant_name: string | null;
  subject_hash: string | null;
  src_net_hash: string | null;
  device_hash: string | null;
  /** Ländercode der Quelle (lokale GeoIP-Datenbank), nie die IP */
  src_country: string | null;
  risk_score: number | null;
  risk_reasons: string[];
  enforcement: string | null;
  user_agent_family: string | null;
};

/** GET /api/admin/auth-security/events (Keyset) */
export type AuthEventPage = { items: AuthEventRow[]; next_cursor: string | null; start: string; end: string };

export type AuthEventHistogram = {
  start: string;
  end: string;
  bucket_seconds: number;
  buckets: ({ start: string } & Record<AuthOutcome, number>)[];
  outcome_counts: Record<AuthOutcome, number>;
  total: number;
};

export type AuthEventGroup = {
  key: string;
  events: number;
  failure: number;
  blocked: number;
  challenged: number;
  success: number;
  distinct_other: number;
  tenants: number;
  max_risk: number | null;
  last_at: string;
  country: string | null;
  tenant_name: string | null;
};

export type AuthEventDetail = AuthEventRow & {
  policy_version: string | null;
  endpoint: string | null;
  host_kind: string | null;
  reasons: { code: string; weight: number | null }[];
  has_weights: boolean;
  details: Record<string, unknown>;
  related: Partial<Record<"net" | "subject" | "country", number>>;
  related_hours: number;
  can_block: boolean;
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

// ── Alarmregeln (1.6) ──

export type AlertRuleState = "fired" | "near" | "quiet";

/** GET /api/admin/auth-security/alert-rules */
export type AlertRuleRow = {
  rule: string;
  window_minutes: number;
  value: number;
  threshold: number;
  comparator: ">=" | ">";
  state: AlertRuleState;
  severity: "critical" | "warning";
  fired: number;
  triggers_30d: number;
  daily_30d: number[];
  recent: { at: string; subject: string | null; severity: string }[];
  settings: Record<string, number | string | boolean>;
};

/** GET /api/admin/auth-security/alert-rules/{rule}/series */
export type AlertRuleSeries = {
  rule: string;
  bucket_minutes: number;
  hours: number;
  threshold: number;
  comparator: ">=" | ">";
  points: { start: string; value: number }[];
};

// ── Vorfälle und Lagebild (1.7) ─────────────────────────────────────────────────────────────

export type IncidentStatus = "new" | "in_progress" | "resolved" | "false_positive";
export type IncidentSeverity = "critical" | "warning";

/** GET /api/admin/auth-security/incidents (Eintrag) */
export type SecurityIncident = {
  id: number;
  key: string;
  rule: string;
  subject: string | null;
  subject_label: string | null;
  severity: IncidentSeverity;
  status: IncidentStatus;
  active: boolean;
  trigger_count: number;
  first_seen_at: string;
  last_triggered_at: string;
  cleared_at: string | null;
  acknowledged_at: string | null;
  closed_at: string | null;
  updated_at: string;
  assignee: { id: string; name: string } | null;
  tenant: { id: string; name: string } | null;
  window_minutes: number | null;
  spark: number[] | null;
};

export type SecurityIncidentList = {
  items: SecurityIncident[];
  total: number;
  offset: number;
  limit: number;
  counts: Record<"open" | "new" | "in_progress" | "closed" | "all", number>;
};

export type SecurityIncidentStats = {
  open: number;
  critical: number;
  unassigned: number;
  new: number;
  mtta_seconds: number | null;
  mttr_seconds: number | null;
  false_positives: number;
  closed: number;
  false_positive_rate: number | null;
  days: number;
};

export type IncidentActivity = {
  kind: "activity";
  id: number;
  at: string;
  type: "triggered" | "retriggered" | "cleared" | "escalated" | "status" | "assigned" | "note" | "block";
  admin: string | null;
  from: string | null;
  to: string | null;
  note: string | null;
};

export type IncidentTimelineEvent = {
  kind: "event";
  at: string;
  event_id: string;
  event_type: string;
  outcome: string;
  risk_score: number | null;
  subject: string | null;
  net: string | null;
  country: string | null;
  marker: "first" | "last" | null;
  stage: number | null;
  block_scope: string | null;
};

export type IncidentParticipant = { key: string; events: number; failures: number; country?: string | null };

/** GET /api/admin/auth-security/incidents/{id} */
export type SecurityIncidentDetail = SecurityIncident & {
  window: { start: string; end: string };
  facts: Record<"events" | "failures" | "blocked" | "challenged" | "successes" | "accounts" | "networks" | "tenants" | "countries", number>;
  max_risk: number | null;
  stage: number;
  participants: {
    networks: IncidentParticipant[];
    accounts: IncidentParticipant[];
    tenants: { id: string; name: string; events: number; failures: number; accounts: number }[];
    countries: { code: string; events: number; failures: number }[];
  };
  reasons: { code: string; count: number; weight: number | null }[];
  timeline: (IncidentActivity | IncidentTimelineEvent)[];
  notes: IncidentActivity[];
  assignees: { id: string; name: string }[];
  can_block: boolean;
  event_filter: { net?: string; subject?: string; tenant_id?: string };
  me: string;
};

export type SituationLevel = "calm" | "elevated" | "attack" | "attack_mode";

export type SituationPoint = { start: string; failures: number; blocked: number; challenged: number; successes: number };

/** GET /api/admin/auth-security/situation */
export type SecuritySituation = {
  range: "24h" | "7d";
  start: string;
  end: string;
  bucket_minutes: number;
  posture: { level: SituationLevel; attack_mode: boolean; open: number; critical: number; active_rules: number; rules_near: number };
  points: SituationPoint[];
  totals: Omit<SituationPoint, "start"> & { admin_logins: number };
  previous: Omit<SituationPoint, "start"> & { admin_logins: number };
  incident_stats: SecurityIncidentStats;
  markers: { id: number; rule: string; severity: IncidentSeverity; status: IncidentStatus; at: string }[];
  heatmap: { dow: number; hour: number; count: number }[];
  heatmap_days: number;
  countries: { code: string | null; failures: number }[];
  networks: { net: string; failures: number; accounts: number; tenants: number; country: string | null }[];
  accounts: { subject: string; failures: number; networks: number }[];
  active_blocks: number;
};
