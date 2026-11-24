"use client";

import Link from "next/link";
import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useState, type FormEvent } from "react";
import { useLocale, useTranslations } from "next-intl";

import { TenantPicker } from "@/components/admin/tenant-picker";
import { SecurityExportButton } from "@/components/admin/security/security-export";
import { SecurityPageHeader } from "@/components/admin/security/security-page-header";
import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { stepUpFetch } from "@/lib/admin-step-up";
import { BLOCK_DURATION_PRESETS, parseBlockMinutes } from "@/lib/admin/security-blocks";
import {
  DEFAULT_EVENT_FILTERS,
  EVENT_OUTCOMES,
  EVENT_PIVOTS,
  EVENT_RANGES,
  eventApiQuery,
  eventFiltersFromParams,
  eventFiltersToParams,
  parsePivotToken,
  riskLevel,
  type EventFilters,
  type EventGroup,
  type EventPivot,
  type PivotAliases,
} from "@/lib/admin/security-events";
import { ApiError, browserApiFetch } from "@/lib/api/client";
import { useVisibleInterval } from "@/lib/hooks/use-visible-interval";
import { COUNTRY_SOURCE_URL, countryName } from "@/lib/utils/country";
import { formatDateTime, formatTime } from "@/lib/utils/format";
import type {
  AuthEventDetail,
  AuthEventGroup,
  AuthEventHistogram,
  AuthEventPage,
  AuthEventRow,
  AuthOutcome,
  ResolvedSubject,
} from "@/types/admin-security";

const PAGE_SIZE = 50;
const LIVE_MS = 30_000;
const MAX_MINUTES = 30 * 24 * 60;

// Feste Liste wie backend app/auth_security/events.py::EVENT_TYPES (technische Codes, keine UI-Texte).
export const AUTH_EVENT_TYPES = [
  "login.password", "login.locked", "login.challenge", "login.mfa.totp", "login.mfa.passkey", "login.success",
  "mfa.enroll", "mfa.remove", "mfa.setup_skipped", "session.revoke", "session.logout", "reset.request", "reset.complete",
  "password.change", "token.invalid", "block.set", "block.clear", "device.revoke", "stepup.success", "stepup.failure",
  "stepup.required", "ratelimit.backend_error", "admin.login.password", "admin.login.mfa", "admin.login.success",
  "admin.mfa.enroll", "admin.mfa.remove", "admin.stepup", "admin.logout",
] as const;

const ACTOR_KINDS = new Set(["user", "admin", "anonymous", "system"]);

export const OUTCOME_BADGE: Record<AuthOutcome, BadgeVariant> = {
  success: "success",
  failure: "danger",
  blocked: "warning",
  challenged: "info",
  info: "neutral",
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

type Loaded<T> = { data: T | null; failed: boolean; forbidden: boolean; loading: boolean };

function useLoad<T>(path: string | null, tick: number): Loaded<T> { // i18n-ok: TypeScript-Generic, kein Text
  const [state, setState] = useState<Loaded<T>>({ data: null, failed: false, forbidden: false, loading: path !== null });
  useEffect(() => {
    if (!path) {
      setState({ data: null, failed: false, forbidden: false, loading: false });
      return;
    }
    const controller = new AbortController();
    setState((current) => ({ ...current, loading: true }));
    browserApiFetch<T>(path, { signal: controller.signal })
      .then((data) => setState({ data, failed: false, forbidden: false, loading: false }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const forbidden = error instanceof ApiError && error.status === 403;
        setState({ data: null, failed: !forbidden, forbidden, loading: false });
      });
    return () => controller.abort();
  }, [path, tick]);
  return state;
}

function useEventUrlState() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [state, setState] = useState(() => {
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    return { filters: eventFiltersFromParams(params, AUTH_EVENT_TYPES), event: params.get("event") };
  });
  useEffect(() => {
    const next = eventFiltersToParams(state.filters, state.event).toString();
    if (typeof window !== "undefined" && window.location.search.replace(/^\?/, "") !== next) {
      router.replace((next ? `${pathname}?${next}` : pathname) as Route, { scroll: false });
    }
  }, [state, pathname, router]);
  const setFilters = useCallback((patch: Partial<EventFilters>) => setState((current) => ({ ...current, filters: { ...current.filters, ...patch } })), []);
  const setEvent = useCallback((event: string | null) => setState((current) => ({ ...current, event })), []);
  return { filters: state.filters, event: state.event, setFilters, setEvent };
}

/** /admin/security/events (1.6): Filter (Pseudonym-Präfixe, Land, Typ, Ergebnis, Mandant, Pflicht-
 * Zeitraum), gefiltertes Histogramm, Liste mit Keyset-Pagination oder Gruppen nach Netz/Konto,
 * Detail mit Risikogewichten und «Quelle sperren» (Netz-Fingerprint, Passkey). Filter in der URL
 * (nur Codes und Pseudonym-Präfixe). */
export function SecurityEvents({ canWrite = true }: { canWrite?: boolean }) {
  const t = useTranslations("adminSecurity");
  const { filters, event: selected, setFilters, setEvent } = useEventUrlState();
  const [cursors, setCursors] = useState<string[]>([]);
  const [tick, setTick] = useState(0);
  const [live, setLive] = useState(false);
  const queryKey = eventApiQuery(filters).toString();
  const cursor = cursors.at(-1);

  // Filterwechsel: zurück auf die erste Seite
  useEffect(() => setCursors([]), [queryKey]);

  const listPath = filters.group === "flat"
    ? `/api/admin/auth-security/events?${eventApiQuery(filters, { limit: PAGE_SIZE, ...(cursor ? { cursor } : {}) })}`
    : null;
  const groupPath = filters.group !== "flat" ? `/api/admin/auth-security/events/groups?${eventApiQuery(filters, { by: filters.group })}` : null;
  const list = useLoad<AuthEventPage>(listPath, tick);
  const grouped = useLoad<AuthEventGroup[]>(groupPath, tick);
  const histogram = useLoad<AuthEventHistogram>(`/api/admin/auth-security/events/histogram?${queryKey}`, tick);
  const reload = useCallback(() => setTick((value) => value + 1), []);
  useVisibleInterval(reload, live && cursors.length === 0 ? LIVE_MS : null);

  const header = (
    <SecurityPageHeader
      title={t("events.title")}
      description={t("events.description")}
      actions={
        <div className="table-toolbar-actions">
          <FilterTabs<EventGroup>
            options={[
              { value: "flat", label: t("events.groups.flat") },
              { value: "net", label: t("events.groups.net") },
              { value: "subject", label: t("events.groups.subject") },
            ]}
            value={filters.group}
            onChange={(group) => setFilters({ group })}
          />
          <SecurityExportButton kind="auth_events" />
        </div>
      }
    />
  );

  if (histogram.forbidden || list.forbidden || grouped.forbidden) {
    return (
      <>
        {header}
        <StatusBanner tone="neutral" message={t("ownerOnly")} />
      </>
    );
  }

  const rows = list.data?.items ?? [];
  function pivot(key: EventPivot, value: string | null) {
    if (!value) return;
    setFilters({ [key]: value, group: "flat" } as Partial<EventFilters>);
    setEvent(null);
  }

  return (
    <>
      {header}
      {list.failed || histogram.failed || grouped.failed ? <StatusBanner tone="error" message={t("loadFailed")} /> : null}
      <EventFilterCard
        filters={filters}
        counts={histogram.data?.outcome_counts ?? null}
        live={live}
        onLive={() => setLive((value) => !value)}
        onChange={setFilters}
      />
      {histogram.data ? <EventHistogramChart histogram={histogram.data} /> : null}

      <div className={`admin-security-events-layout${selected ? " admin-security-events-layout-detail" : ""}`}>
        <section className="admin-security-events-main" aria-label={t("events.listLabel")}>
          {filters.group === "flat" ? (
            <>
              <EventTable rows={rows} loading={list.loading} selected={selected} onSelect={setEvent} onPivot={pivot} />
              <div className="admin-security-pager">
                <button type="button" className="button-secondary" disabled={cursors.length === 0} onClick={() => setCursors((stack) => stack.slice(0, -1))}>
                  {t("events.previous")}
                </button>
                <span className="muted">{rows.length > 0 ? t("events.pageInfoKeyset", { page: cursors.length + 1, count: rows.length }) : null}</span>
                <button
                  type="button"
                  className="button-secondary"
                  disabled={!list.data?.next_cursor}
                  onClick={() => list.data?.next_cursor && setCursors((stack) => [...stack, list.data!.next_cursor as string])}
                >
                  {t("events.next")}
                </button>
              </div>
            </>
          ) : (
            <EventGroupTable
              by={filters.group}
              groups={grouped.data ?? []}
              loading={grouped.loading}
              onPivot={(value) => pivot(filters.group === "net" ? "net" : "subject", value)}
            />
          )}
          {rows.some((row) => row.src_country) ? (
            <p className="field-help">
              {t.rich("events.countrySource", {
                link: (chunks) => <a href={COUNTRY_SOURCE_URL} target="_blank" rel="noopener noreferrer">{chunks}</a>,
              })}
            </p>
          ) : null}
        </section>
        {selected ? (
          <EventDrawer eventId={selected} canWrite={canWrite} onClose={() => setEvent(null)} onPivot={pivot} onBlocked={reload} />
        ) : null}
      </div>
    </>
  );
}

function EventFilterCard({
  filters, counts, live, onLive, onChange,
}: {
  filters: EventFilters;
  counts: Record<AuthOutcome, number> | null;
  live: boolean;
  onLive: () => void;
  onChange: (patch: Partial<EventFilters>) => void;
}) {
  const t = useTranslations("adminSecurity");
  const inputId = useId();
  const [draft, setDraft] = useState("");
  const [invalid, setInvalid] = useState(false);
  const aliases: PivotAliases = useMemo(
    () => Object.fromEntries(EVENT_PIVOTS.map((key) => [key, [t(`events.pivots.${key}`)]])) as PivotAliases,
    [t],
  );
  const total = counts ? Object.values(counts).reduce((sum, value) => sum + value, 0) : undefined;
  const active = EVENT_PIVOTS.filter((key) => filters[key]);
  const anyFilter = active.length > 0 || Boolean(filters.type || filters.outcome || filters.tenant_id);

  function submit(event: FormEvent) {
    event.preventDefault();
    const token = parsePivotToken(draft, aliases);
    if (!token) {
      setInvalid(draft.trim().length > 0);
      return;
    }
    onChange({ [token.key]: token.value } as Partial<EventFilters>);
    setDraft("");
    setInvalid(false);
  }

  return (
    <section className="card section-stack" aria-label={t("events.filtersLabel")}>
      <div className="admin-security-filter-row">
        <form className="admin-security-token-form" onSubmit={submit} role="search">
          <label className="visually-hidden" htmlFor={inputId}>{t("events.tokenLabel")}</label>
          <div className="admin-security-token-field">
            {active.map((key) => (
              <span key={key} className="admin-security-pivot">
                <span className="admin-security-pivot-key">{t(`events.pivots.${key}`)}:</span>
                <code>{filters[key]}</code>
                <button
                  type="button"
                  className="button-icon-soft button-icon-soft-sm"
                  aria-label={t("events.removePivot", { filter: `${t(`events.pivots.${key}`)}: ${filters[key]}` })}
                  onClick={() => onChange({ [key]: "" } as Partial<EventFilters>)}
                >
                  ×
                </button>
              </span>
            ))}
            <input
              id={inputId}
              value={draft}
              onChange={(event) => {
                setDraft(event.target.value);
                setInvalid(false);
              }}
              aria-invalid={invalid}
              aria-describedby={`${inputId}-help`}
              placeholder={t("events.tokenPlaceholder")}
              autoComplete="off"
              spellCheck={false}
            />
          </div>
          <span id={`${inputId}-help`} className={invalid ? "field-help admin-security-token-error" : "field-help"}>
            {invalid ? t("events.tokenInvalid") : t("events.tokenHelp")}
          </span>
        </form>
        <label className="field-stack admin-security-type-filter">
          <span className="field-label">{t("events.typeLabel")}</span>
          <SearchableSelect
            options={[...AUTH_EVENT_TYPES]}
            getId={(item) => item}
            getLabel={(item) => item}
            value={filters.type || null}
            onChange={(item) => onChange({ type: item ?? "" })}
            nullLabel={t("events.typeAll")}
          />
        </label>
        <div className="field-stack admin-security-type-filter">
          <span className="field-label">{t("events.tenantLabel")}</span>
          <TenantPicker value={filters.tenant_id || null} onChange={(tenant) => onChange({ tenant_id: tenant?.id ?? "" })} nullLabel={t("events.tenantAll")} />
        </div>
      </div>
      <div className="admin-security-filter-row">
        <FilterTabs<EventFilters["outcome"]>
          variant="chips"
          options={[
            { value: "", label: t("outcomes.all"), count: total },
            ...EVENT_OUTCOMES.map((value) => ({ value, label: t(`outcomes.${value}`), count: counts?.[value] })),
          ]}
          value={filters.outcome}
          onChange={(outcome) => onChange({ outcome })}
        />
        <FilterTabs<EventFilters["range"]>
          options={EVENT_RANGES.map((value) => ({ value, label: t(`events.ranges.${value}`) }))}
          value={filters.range}
          onChange={(range) => onChange({ range })}
        />
        <button type="button" className={`button-secondary audit-live${live ? " audit-live-on" : ""}`} aria-pressed={live} onClick={onLive}>
          <span className="audit-live-dot" aria-hidden="true" />
          {live ? t("events.liveOn") : t("events.liveOff")}
        </button>
        {anyFilter ? (
          <button
            type="button"
            className="button-secondary button-ghost"
            onClick={() => onChange({ ...DEFAULT_EVENT_FILTERS, range: filters.range, group: filters.group })}
          >
            {t("events.reset")}
          </button>
        ) : null}
      </div>
    </section>
  );
}

function EventHistogramChart({ histogram }: { histogram: AuthEventHistogram }) {
  const t = useTranslations("adminSecurity");
  const locale = useLocale();
  const summaryId = useId();
  const max = Math.max(1, ...histogram.buckets.map((bucket) => bucket.success + bucket.failure + bucket.blocked + bucket.challenged + bucket.info));
  const sums = histogram.buckets.reduce(
    (acc, bucket) => ({ failure: acc.failure + bucket.failure, other: acc.other + bucket.blocked + bucket.challenged, success: acc.success + bucket.success }),
    { failure: 0, other: 0, success: 0 },
  );
  const middle = histogram.buckets[Math.floor(histogram.buckets.length / 2)]?.start;
  return (
    <section className="card section-stack admin-security-histogram">
      <div className="admin-security-section-head">
        <h2 className="section-title">{t("events.histogramTitle")}</h2>
        <div className="admin-security-legend">
          <span><span className="admin-security-swatch admin-security-swatch-failure" aria-hidden="true" />{t("outcomes.failure")}</span>
          <span><span className="admin-security-swatch admin-security-swatch-other" aria-hidden="true" />{t("events.histogramOther")}</span>
          <span><span className="admin-security-swatch admin-security-swatch-success" aria-hidden="true" />{t("outcomes.success")}</span>
        </div>
      </div>
      <p id={summaryId} className="muted">{t("events.histogramSummary", sums)}</p>
      <div className="admin-security-bars" role="img" aria-label={t("events.histogramTitle")} aria-describedby={summaryId}>
        {histogram.buckets.map((bucket) => {
          const other = bucket.blocked + bucket.challenged + bucket.info;
          const sum = bucket.success + bucket.failure + other;
          // Höhe wurzelskaliert, damit Spitzen kleine Abschnitte nicht verschwinden lassen
          const height = sum ? Math.max(4, Math.sqrt(sum / max) * 100) : 0;
          const part = (value: number) => `${sum ? (value / sum) * height : 0}%`;
          return (
            <div
              key={bucket.start}
              className="admin-security-bar"
              title={t("events.barTitle", { time: formatDateTime(bucket.start, locale), failure: bucket.failure, other, success: bucket.success })}
            >
              {/* Höhen sind Laufzeitwerte (Anteile) */}
              <div className="admin-security-bar-failure" style={{ height: part(bucket.failure) }} />
              <div className="admin-security-bar-other" style={{ height: part(other) }} />
              <div className="admin-security-bar-success" style={{ height: part(bucket.success) }} />
            </div>
          );
        })}
      </div>
      <div className="audit-axis">
        <span>{formatDateTime(histogram.start, locale)}</span>
        <span>{middle ? formatDateTime(middle, locale) : null}</span>
        <span>{t("events.now")}</span>
      </div>
      <details className="admin-analytics-table">
        <summary>{t("overview.showTable")}</summary>
        <DataTable columns={[t("events.columns.time"), t("outcomes.failure"), t("events.histogramOther"), t("outcomes.success")]}>
          {histogram.buckets.map((bucket) => (
            <tr key={bucket.start}>
              <td>{formatDateTime(bucket.start, locale)}</td>
              <td>{bucket.failure}</td>
              <td>{bucket.blocked + bucket.challenged + bucket.info}</td>
              <td>{bucket.success}</td>
            </tr>
          ))}
        </DataTable>
      </details>
    </section>
  );
}

function RiskCell({ score }: { score: number | null }) {
  const t = useTranslations("adminSecurity.events");
  const level = riskLevel(score);
  if (score === null || !level) return <span className="muted">—</span>;
  return (
    <span className="admin-security-risk">
      <span className={`admin-security-risk-meter admin-security-risk-${level}`} aria-hidden="true">
        {/* Breite = Laufzeitwert (Score in %) */}
        <span style={{ width: `${Math.min(100, score)}%` }} />
      </span>
      <span>{score}</span>
      <span className="visually-hidden">{t(`riskLevels.${level}`)}</span>
    </span>
  );
}

function EventTable({
  rows, loading, selected, onSelect, onPivot,
}: {
  rows: AuthEventRow[];
  loading: boolean;
  selected: string | null;
  onSelect: (id: string | null) => void;
  onPivot: (key: EventPivot, value: string | null) => void;
}) {
  const t = useTranslations("adminSecurity");
  const locale = useLocale();
  return (
    <DataTable
      columns={[
        t("events.columns.time"), t("events.columns.type"), t("events.columns.outcome"), t("events.columns.tenant"),
        t("events.columns.subject"), t("events.columns.network"), t("events.columns.country"), t("events.columns.risk"), t("events.columns.client"),
      ]}
      emptyMessage={loading ? undefined : t("events.empty")}
    >
      {rows.map((row) => {
        const isSelected = row.event_id === selected;
        return (
          <tr
            key={row.event_id}
            className={`table-row-clickable${isSelected ? " audit-row-selected" : ""}`}
            onClick={() => onSelect(isSelected ? null : row.event_id)} /* a11y-ok: Maus-Abkürzung, Tastatur über table-row-link (Zeit) */
          >
            <td className="admin-security-nowrap">
              <button
                type="button"
                className="table-row-link"
                aria-pressed={isSelected}
                aria-label={t("events.openEvent", { time: formatDateTime(row.ts, locale), type: row.event_type })}
                onClick={(event) => {
                  event.stopPropagation();
                  onSelect(isSelected ? null : row.event_id);
                }}
              >
                {formatTime(row.ts, locale)}
              </button>
            </td>
            <td>
              <code>{row.event_type}</code>
              <div className="muted admin-cell-sub">{ACTOR_KINDS.has(row.actor_kind) ? t(`events.actorKinds.${row.actor_kind}`) : row.actor_kind}</div>
            </td>
            <td><Badge variant={OUTCOME_BADGE[row.outcome] ?? "neutral"} dot>{t(`outcomes.${row.outcome}`)}</Badge></td>
            <td>{row.tenant_name ?? <span className="muted">—</span>}</td>
            <td><PivotButton value={row.subject_hash} label={t("events.pivots.subject")} onPivot={() => onPivot("subject", row.subject_hash)} /></td>
            <td><PivotButton value={row.src_net_hash} label={t("events.pivots.net")} onPivot={() => onPivot("net", row.src_net_hash)} /></td>
            <td>{row.src_country ? <span title={row.src_country}>{countryName(row.src_country, locale)}</span> : <span className="muted">—</span>}</td>
            <td><RiskCell score={row.risk_score} /></td>
            <td>{row.user_agent_family ?? <span className="muted">—</span>}</td>
          </tr>
        );
      })}
    </DataTable>
  );
}

function PivotButton({ value, label, onPivot }: { value: string | null; label: string; onPivot: () => void }) {
  const t = useTranslations("adminSecurity.events");
  if (!value) return <span className="muted">—</span>;
  return (
    <button
      type="button"
      className="admin-security-pivot-button"
      aria-label={t("filterBy", { filter: label, value })}
      onClick={(event) => {
        event.stopPropagation();
        onPivot();
      }}
    >
      {value}
    </button>
  );
}

function EventGroupTable({
  by, groups, loading, onPivot,
}: {
  by: EventGroup;
  groups: AuthEventGroup[];
  loading: boolean;
  onPivot: (value: string) => void;
}) {
  const t = useTranslations("adminSecurity");
  const locale = useLocale();
  const max = Math.max(1, ...groups.map((group) => group.events));
  return (
    <DataTable
      columns={[
        by === "net" ? t("events.groupColumns.net") : t("events.groupColumns.subject"), t("events.groupColumns.distribution"),
        t("events.groupColumns.events"), by === "net" ? t("events.groupColumns.accounts") : t("events.groupColumns.networks"),
        t("events.groupColumns.maxRisk"), t("events.groupColumns.last"),
      ]}
      emptyMessage={loading ? undefined : t("events.empty")}
    >
      {groups.map((group) => {
        const share = (value: number) => `${(value / group.events) * 100}%`;
        return (
          <tr key={group.key}>
            <td>
              <button type="button" className="admin-security-pivot-button" aria-label={t("events.filterBy", { filter: t(`events.pivots.${by === "net" ? "net" : "subject"}`), value: group.key })} onClick={() => onPivot(group.key)}>
                {group.key}
              </button>
              <div className="muted admin-cell-sub">
                {by === "net" ? (group.country ? countryName(group.country, locale) : null) : group.tenant_name}
              </div>
            </td>
            <td>
              <span className="admin-security-distribution" style={{ width: `${Math.max(8, (group.events / max) * 100)}%` }} aria-hidden="true">
                {/* Anteile = Laufzeitwerte */}
                <span className="admin-security-bar-failure" style={{ width: share(group.failure) }} />
                <span className="admin-security-bar-other" style={{ width: share(group.blocked + group.challenged) }} />
                <span className="admin-security-bar-success" style={{ width: share(group.success) }} />
              </span>
              <span className="visually-hidden">
                {t("events.distribution", { failure: group.failure, other: group.blocked + group.challenged, success: group.success })}
              </span>
            </td>
            <td>{group.events.toLocaleString()}</td>
            <td>{group.distinct_other.toLocaleString()}</td>
            <td><RiskCell score={group.max_risk} /></td>
            <td>{formatDateTime(group.last_at, locale)}</td>
          </tr>
        );
      })}
    </DataTable>
  );
}

function EventDrawer({
  eventId, canWrite, onClose, onPivot, onBlocked,
}: {
  eventId: string;
  canWrite: boolean;
  onClose: () => void;
  onPivot: (key: EventPivot, value: string | null) => void;
  onBlocked: () => void;
}) {
  const t = useTranslations("adminSecurity");
  const locale = useLocale();
  const confirm = useConfirm();
  const showToast = useToast();
  const headingId = useId();
  const detail = useLoad<AuthEventDetail>(`/api/admin/auth-security/events/${encodeURIComponent(eventId)}`, 0);
  const [resolved, setResolved] = useState<ResolvedSubject | null>(null);
  const [blockOpen, setBlockOpen] = useState(false);
  const event = detail.data;

  async function resolveSubject() {
    if (!event) return;
    const ok = await confirm({ message: t("events.resolveConfirm"), confirmLabel: t("events.resolve") });
    if (!ok) return;
    try {
      setResolved(await stepUpFetch<ResolvedSubject>("security-resolve", `/api/admin/auth-security/events/${encodeURIComponent(event.event_id)}/resolve-subject`, { method: "POST" }));
    } catch (error) {
      showToast(errorMessage(error), "error");
    }
  }

  const level = riskLevel(event?.risk_score);
  const weightSum = event ? event.reasons.reduce((sum, reason) => sum + (reason.weight ?? 0), 0) : 0;

  return (
    <aside className="audit-detail card admin-security-drawer" aria-labelledby={headingId} onKeyDown={(keyEvent) => { if (keyEvent.key === "Escape") onClose(); }}>
      <div className="audit-detail-head">
        <span className="muted">{event ? formatDateTime(event.ts, locale) : null}</span>
        <button type="button" className="button-icon" aria-label={t("events.closeDetail")} title={t("events.closeDetail")} onClick={onClose}>✕</button>
      </div>
      {detail.failed ? <StatusBanner tone="error" message={t("loadFailed")} /> : null}
      {event ? (
        <>
          <h2 id={headingId} className="section-title"><code>{event.event_type}</code></h2>
          <div className="audit-detail-badges">
            <Badge variant={OUTCOME_BADGE[event.outcome] ?? "neutral"} dot>{t(`outcomes.${event.outcome}`)}</Badge>
          </div>

          <div className="audit-detail-section">
            <h3 className="audit-detail-title">
              {event.risk_score !== null && level
                ? t("events.riskHeading", { score: event.risk_score, level: t(`events.riskLevels.${level}`) })
                : t("events.riskNone")}
            </h3>
            {event.has_weights && weightSum > 0 ? (
              <div className="admin-security-risk-stack" aria-hidden="true">
                {event.reasons.map((reason) => (
                  <span
                    key={reason.code}
                    className={`admin-security-risk-part admin-security-weight-${(reason.weight ?? 0) >= 20 ? "high" : (reason.weight ?? 0) >= 10 ? "mid" : "low"}`}
                    style={{ width: `${((reason.weight ?? 0) / weightSum) * Math.min(100, event.risk_score ?? 0)}%` }}
                  />
                ))}
              </div>
            ) : null}
            {event.reasons.length === 0 ? (
              <p className="muted">{t("events.noReasons")}</p>
            ) : (
              <ul className="admin-security-reason-list">
                {event.reasons.map((reason) => (
                  <li key={reason.code}>
                    <span>{t.has(`events.reasons.${reason.code}`) ? t(`events.reasons.${reason.code}`) : reason.code}</span>
                    <span className="admin-security-mono">{reason.weight !== null ? `+${reason.weight}` : null}</span>
                  </li>
                ))}
              </ul>
            )}
            {event.has_weights || event.reasons.length === 0 ? null : <p className="field-help">{t("events.noWeights")}</p>}
          </div>

          <dl className="admin-key-value">
            <div><dt>{t("events.columns.actor")}</dt><dd>{ACTOR_KINDS.has(event.actor_kind) ? t(`events.actorKinds.${event.actor_kind}`) : event.actor_kind}</dd></div>
            <div>
              <dt>{t("events.columns.tenant")}</dt>
              <dd>{event.tenant_id ? <Link href={`/admin/tenants/${event.tenant_id}` as Route}>{event.tenant_name}</Link> : "—"}</dd>
            </div>
            <div><dt>{t("events.columns.subject")}</dt><dd><code>{event.subject_hash ?? "—"}</code></dd></div>
            <div><dt>{t("events.columns.network")}</dt><dd><code>{event.src_net_hash ?? "—"}</code></dd></div>
            <div><dt>{t("events.columns.device")}</dt><dd><code>{event.device_hash ?? "—"}</code></dd></div>
            <div><dt>{t("events.columns.country")}</dt><dd>{event.src_country ? countryName(event.src_country, locale) : "—"}</dd></div>
            <div><dt>{t("events.columns.client")}</dt><dd>{event.user_agent_family ?? "—"}</dd></div>
            <div><dt>{t("events.columns.enforcement")}</dt><dd><code>{event.enforcement ?? "—"}</code></dd></div>
            <div><dt>{t("events.columns.policy")}</dt><dd><code>{event.policy_version ?? "—"}</code></dd></div>
            <div><dt>{t("events.columns.details")}</dt><dd><code>{Object.keys(event.details).length ? JSON.stringify(event.details) : "—"}</code></dd></div>
          </dl>

          <div className="audit-detail-section">
            <h3 className="audit-detail-title">{t("events.trace", { hours: event.related_hours })}</h3>
            <div className="admin-security-trace">
              {(["net", "subject", "country"] as const).map((key) => {
                const value = key === "net" ? event.src_net_hash : key === "subject" ? event.subject_hash : event.src_country;
                const count = event.related[key];
                if (!value || count === undefined) return null;
                return (
                  <button key={key} type="button" className="admin-security-trace-item" onClick={() => onPivot(key, value)}>
                    <span>{t(`events.traceKinds.${key}`)}</span>
                    <span className="muted">{count.toLocaleString()}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {canWrite ? (
            <div className="admin-security-block-actions">
              {event.subject_hash || event.platform_admin_id ? (
                <button type="button" className="button-secondary" onClick={() => void resolveSubject()}>{t("events.resolve")}</button>
              ) : null}
              {event.can_block ? (
                <button type="button" className="button-danger" onClick={() => setBlockOpen(true)}>{t("events.blockSource")}</button>
              ) : null}
            </div>
          ) : null}
          <BlockSourceModal
            open={blockOpen}
            event={event}
            onClose={() => setBlockOpen(false)}
            onDone={() => {
              setBlockOpen(false);
              onBlocked();
            }}
          />
          <SubjectModal subject={resolved} onClose={() => setResolved(null)} />
        </>
      ) : null}
    </aside>
  );
}

function BlockSourceModal({ open, event, onClose, onDone }: { open: boolean; event: AuthEventDetail; onClose: () => void; onDone: () => void }) {
  const t = useTranslations("adminSecurity");
  const tBlocks = useTranslations("adminSecurity.blocks");
  const showToast = useToast();
  const [preset, setPreset] = useState("60");
  const [custom, setCustom] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const minutes = parseBlockMinutes(preset, custom, MAX_MINUTES);
  const valid = reason.trim().length > 2 && minutes !== null;

  async function submit() {
    if (!valid || minutes === null) return;
    setBusy(true);
    try {
      await stepUpFetch("security-block", `/api/admin/auth-security/events/${encodeURIComponent(event.event_id)}/block`, {
        method: "POST",
        body: JSON.stringify({ minutes, reason: reason.trim() }),
      });
      showToast(t("events.blocked"), "success");
      setReason("");
      onDone();
    } catch (error) {
      showToast(tBlocks("failed", { message: errorMessage(error) }), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} title={t("events.blockTitle", { net: event.src_net_hash ?? "" })} description={t("events.blockDescription")} onClose={onClose}>
      <ModalSaveForm className="section-stack" onSubmit={(formEvent) => { formEvent.preventDefault(); return submit(); }}>
        {/* Geteilte Netze (NAT, Proxy) treffen alle ohne bekanntes Gerät (Security-Review 1.6) */}
        <StatusBanner tone="warning" message={t("events.blockShared", { count: event.related.net ?? 0, hours: event.related_hours })} />
        <div className="field-stack">
          <span className="field-label">{tBlocks("durationLabel")}</span>
          <FilterTabs
            variant="chips"
            options={[
              ...BLOCK_DURATION_PRESETS.map((value) => ({ value: String(value), label: tBlocks(`presets.${value}`) })),
              { value: "custom", label: tBlocks("presets.custom") },
            ]}
            value={preset}
            onChange={setPreset}
          />
          {preset === "custom" ? (
            <label className="field-stack">
              <span className="field-label">{tBlocks("minutesLabel")}</span>
              <input type="number" min={1} max={MAX_MINUTES} inputMode="numeric" value={custom} onChange={(change) => setCustom(change.target.value)} />
            </label>
          ) : null}
        </div>
        <label className="field-stack">
          <span className="field-label">{tBlocks("reasonLabel")}</span>
          <input value={reason} onChange={(change) => setReason(change.target.value)} maxLength={200} required />
          <span className="field-help">{tBlocks("reasonHelp")}</span>
        </label>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>{tBlocks("cancel")}</button>
          <button type="submit" className="button-primary" disabled={!valid || busy}>{tBlocks("save")}</button>
        </div>
      </ModalSaveForm>
    </Modal>
  );
}

function SubjectModal({ subject, onClose }: { subject: ResolvedSubject | null; onClose: () => void }) {
  const t = useTranslations("adminSecurity.subject");
  return (
    <Modal open={subject !== null} onClose={onClose} title={t("title")} description={t("description")}>
      {subject ? (
        subject.kind === "unknown" ? (
          <StatusBanner tone="neutral" message={t("unknown")} />
        ) : (
          <dl className="admin-key-value">
            <div>
              <dt>{t("kind")}</dt>
              <dd>{t(`kinds.${subject.kind}`)}</dd>
            </div>
            <div>
              <dt>{t("name")}</dt>
              <dd>{subject.display_name ?? "—"}</dd>
            </div>
            <div>
              <dt>{t("email")}</dt>
              <dd>{subject.email ?? "—"}</dd>
            </div>
            {subject.kind === "user" ? (
              <div>
                <dt>{t("tenant")}</dt>
                <dd>
                  {subject.tenant_id ? (
                    <Link href={`/admin/tenants/${subject.tenant_id}` as Route}>{subject.tenant_name ?? subject.tenant_id}</Link>
                  ) : "—"}
                </dd>
              </div>
            ) : null}
            <div>
              <dt>{t("via")}</dt>
              <dd>{t(`viaKinds.${subject.via}`)}</dd>
            </div>
          </dl>
        )
      ) : null}
    </Modal>
  );
}
