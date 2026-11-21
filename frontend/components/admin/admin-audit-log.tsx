"use client";

import Link from "next/link";
import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";

import { SecurityExportButton } from "@/components/admin/security/security-export";
import { TenantPicker } from "@/components/admin/tenant-picker";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { SearchInput } from "@/components/ui/search-input";
import { StatusBanner } from "@/components/ui/status-banner";
import { useToast } from "@/contexts/toast-context";
import {
  AUDIT_RANGES,
  AUDIT_URL_CONFIG,
  auditApiQuery,
  auditDiff,
  groupByDay,
  hasActiveAuditFilter,
  relativeDay,
  selectedAreas,
  stepSelection,
  toggleArea,
  type AuditFilters,
  type AuditRange,
} from "@/lib/admin/audit-log";
import { serverTableStateFromParams, serverTableUrlQuery } from "@/lib/admin/use-server-table";
import { browserApiFetch } from "@/lib/api/client";
import { AUDIT_AREAS, auditActionLabel, auditArea, auditInitials, countByArea, type AuditArea } from "@/lib/audit-labels";
import { useVisibleInterval } from "@/lib/hooks/use-visible-interval";
import { useShortcut } from "@/lib/keyboard/use-shortcut";
import { formatDateTime, formatTime } from "@/lib/utils/format";
import { AuditLogEntry, AuditLogPage } from "@/types/api";

// /admin/security/audit nach dem Claude-Design «hocX Audit-Log» (1.5.1): Bereichs-Chips mit Zählern,
// Zeitraum, Zeitleiste (Aggregat-Endpunkt), Tabelle nach Tagen gruppiert, Detail-Spalte mit
// Vorher/Nachher (nur wenn vorhanden), «Im Zusammenhang · gleiche Person», Rohdaten und Link.
// Filter und Auswahl stehen in der URL (nur IDs/Codes); Ansehen protokolliert das Backend.

const PAGE_SIZE = 40;
const LIVE_INTERVAL_MS = 10_000;
const FRESH_MS = 3_000;

type Timeline = {
  range: AuditRange;
  bucket_seconds: number;
  buckets: { start: string; success: number; failure: number }[];
  totals: { events: number; failures: number; persons: number; sources: number };
  by_category: Record<string, number>;
  retention_days: number;
};

type EntryDetail = { entry: AuditLogEntry; context: AuditLogEntry[] };

function useAuditUrlState() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [state, setState] = useState(() => {
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    const entry = Number.parseInt(params.get("entry") ?? "", 10);
    return { filters: serverTableStateFromParams(params, AUDIT_URL_CONFIG).filters, entry: Number.isFinite(entry) && entry > 0 ? entry : null };
  });
  useEffect(() => {
    const query = serverTableUrlQuery({ filters: state.filters, offset: 0, sort: null, dir: "asc" }, AUDIT_URL_CONFIG);
    if (state.entry) query.set("entry", String(state.entry));
    const next = query.toString();
    if (window.location.pathname === pathname && window.location.search.replace(/^\?/, "") !== next) {
      router.replace((next ? `${pathname}?${next}` : pathname) as Route, { scroll: false });
    }
  }, [state, pathname, router]);
  const setFilters = useCallback((patch: Partial<AuditFilters>) => setState((current) => ({ ...current, filters: { ...current.filters, ...patch } })), []);
  const setEntry = useCallback((entry: number | null) => setState((current) => ({ ...current, entry })), []);
  return { filters: state.filters, entry: state.entry, setFilters, setEntry };
}

export function AdminAuditLog({ initialPage }: { initialPage: AuditLogPage }) {
  const t = useTranslations("admin.auditLog");
  const tActions = useTranslations("common.auditActions");
  const locale = useLocale();
  const showToast = useToast();
  const { filters, entry: selectedId, setFilters, setEntry } = useAuditUrlState();
  const [items, setItems] = useState<AuditLogEntry[]>(initialPage.items);
  const [total, setTotal] = useState(initialPage.total);
  const [retention, setRetention] = useState<number | null>(initialPage.retention_days ?? null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [live, setLive] = useState(false);
  const [fresh, setFresh] = useState<Set<number>>(new Set());
  const [detail, setDetail] = useState<EntryDetail | null>(null);
  const queryKey = auditApiQuery(filters).toString();
  const debounceText = useRef(filters.action);

  const load = useCallback(
    async (offset: number, signal?: AbortSignal) => {
      const page = await browserApiFetch<AuditLogPage>(`/api/admin/audit-log?${auditApiQuery(filters, { limit: PAGE_SIZE, offset })}`, { signal });
      return page;
    },
    // queryKey enthält alle Filter
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [queryKey],
  );

  // Liste und Zeitleiste bei jeder Filteränderung neu (Textfeld verzögert)
  useEffect(() => {
    const controller = new AbortController();
    const textChanged = debounceText.current !== filters.action;
    debounceText.current = filters.action;
    const timer = window.setTimeout(() => {
      setLoading(true);
      load(0, controller.signal)
        .then((page) => {
          setItems(page.items);
          setTotal(page.total);
          if (page.retention_days) setRetention(page.retention_days);
          setFailed(false);
        })
        .catch(() => {
          if (!controller.signal.aborted) setFailed(true);
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
      const range = (filters.range || "7d") as AuditRange;
      browserApiFetch<Timeline>(`/api/admin/audit-log/timeline?${auditApiQuery({ ...filters, range })}`, { signal: controller.signal })
        .then(setTimeline)
        .catch(() => undefined);
    }, textChanged ? 300 : 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey]);

  // Live: erste Seite und Zeitleiste alle 10 s neu, nur bei sichtbarer Seite; neue Einträge kurz markiert
  const poll = useCallback(() => {
    load(0)
      .then((page) => {
        setItems((current) => {
          const known = new Set(current.map((item) => item.id));
          const added = page.items.filter((item) => !known.has(item.id));
          if (added.length === 0) return current;
          setFresh(new Set(added.map((item) => item.id)));
          window.setTimeout(() => setFresh(new Set()), FRESH_MS);
          return [...added, ...current];
        });
        setTotal(page.total);
      })
      .catch(() => undefined);
    browserApiFetch<Timeline>(`/api/admin/audit-log/timeline?${auditApiQuery({ ...filters, range: filters.range || "7d" })}`).then(setTimeline).catch(() => undefined);
  }, [load, filters]);
  useVisibleInterval(poll, live ? LIVE_INTERVAL_MS : null);

  async function loadMore() {
    setLoading(true);
    try {
      const page = await load(items.length);
      setItems((current) => [...current, ...page.items.filter((item) => !current.some((known) => known.id === item.id))]);
      setTotal(page.total);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }

  // Detail (auch über ?entry=<id>, z. B. aus «Link zum Eintrag kopieren»)
  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    browserApiFetch<EntryDetail>(`/api/admin/audit-log/entries/${selectedId}`, { signal: controller.signal })
      .then(setDetail)
      .catch(() => {
        if (!controller.signal.aborted) setDetail(null);
      });
    return () => controller.abort();
  }, [selectedId]);

  const ids = useMemo(() => items.map((item) => item.id), [items]);
  useShortcut("admin.auditNext", () => setEntry(stepSelection(ids, selectedId, 1)));
  useShortcut("admin.auditPrevious", () => setEntry(stepSelection(ids, selectedId, -1)));

  const areas = selectedAreas(filters);
  const areaCounts = timeline ? countByArea(timeline.by_category) : null;
  const groups = groupByDay(items);
  const activeFilter = hasActiveAuditFilter(filters);
  const range = (filters.range || "7d") as AuditRange;

  function reset() {
    setFilters({ ...AUDIT_URL_CONFIG.defaults, range });
  }

  function dayTitle(date: Date): string {
    const base = new Intl.DateTimeFormat(locale, { weekday: "long", day: "numeric", month: "long" }).format(date);
    const relative = relativeDay(date);
    return relative ? t(`days.${relative}`, { date: base }) : base;
  }

  const labelOf = (action: string) => auditActionLabel(action, tActions);
  // Mit offener Detail-Spalte: Mandant und Quelle stehen dort, die Tabelle bleibt ohne Querscrollen
  const compact = detail !== null;

  return (
    <div className="grid audit-page">
      <div className="page-header">
        <div className="audit-heading">
          <h1 className="page-title">{t("title")}</h1>
          <p className="muted">{t("description")}</p>
          <ul className="audit-facts">
            <li>{t("facts.appendOnly")}</li>
            {retention ? <li>{t("facts.retention", { days: retention })}</li> : null}
            <li>{t("facts.viewLogged")}</li>
          </ul>
        </div>
        <div className="table-toolbar-actions">
          <button
            type="button"
            className={`button-secondary audit-live${live ? " audit-live-on" : ""}`}
            aria-pressed={live}
            onClick={() => setLive((value) => !value)}
          >
            <span className="audit-live-dot" aria-hidden="true" />
            {live ? t("live.on") : t("live.off")}
          </button>
          <SecurityExportButton kind="audit_log" />
        </div>
      </div>

      <section className="card audit-filters" aria-label={t("filtersLabel")}>
        <div className="audit-filter-row">
          <SearchInput value={filters.action} onChange={(value) => setFilters({ action: value })} placeholder={t("actionPlaceholder")} />
          <FilterTabs<string>
            options={[
              { value: "", label: t("filterAll") },
              { value: "success", label: t("outcome.success") },
              { value: "failure", label: t("filterFailures") },
            ]}
            value={filters.outcome}
            onChange={(value) => setFilters({ outcome: value })}
          />
          <FilterTabs<AuditRange>
            options={AUDIT_RANGES.map((value) => ({ value, label: t(`ranges.${value}`) }))}
            value={range}
            onChange={(value) => setFilters({ range: value })}
          />
          <div className="audit-tenant-filter">
            <TenantPicker value={filters.tenant_id || null} onChange={(tenant) => setFilters({ tenant_id: tenant?.id ?? "" })} nullLabel={t("allTenants")} />
          </div>
        </div>

        <div className="audit-area-row" role="group" aria-label={t("areaLabel")}>
          <span className="audit-area-title">{t("areaLabel")}</span>
          {AUDIT_AREAS.map((area) => (
            <button
              key={area}
              type="button"
              className={`audit-area-chip audit-area-${area}${areas.includes(area) ? " audit-area-chip-active" : ""}`}
              aria-pressed={areas.includes(area)}
              onClick={() => setFilters({ area: toggleArea(filters, area) })}
            >
              <span className="audit-area-dot" aria-hidden="true" />
              {t(`areas.${area}`)}
              {areaCounts ? <span className="audit-area-count">{areaCounts[area]}</span> : null}
            </button>
          ))}
          {activeFilter ? (
            <button type="button" className="button-secondary button-ghost audit-reset" onClick={reset}>
              {t("reset")}
            </button>
          ) : null}
        </div>

        <ActiveFilters filters={filters} onClear={setFilters} />

        {timeline ? <AuditTimeline timeline={timeline} /> : null}
      </section>

      {failed ? <StatusBanner tone="error" message={t("loadFailed")} /> : null}

      <div className={`audit-layout${detail ? " audit-layout-detail" : ""}`}>
        <div className="audit-table">
          {items.length === 0 && !loading ? (
            <div className="audit-empty">
              <strong>{t("emptyTitle")}</strong>
              <span className="muted">{t("emptyHint")}</span>
              {activeFilter ? (
                <button type="button" className="button-secondary" onClick={reset}>
                  {t("reset")}
                </button>
              ) : null}
            </div>
          ) : (
            <DataTable
              columns={compact ? [t("colTime"), t("colAction"), t("colActor"), t("colOutcome")] : [t("colTime"), t("colAction"), t("colActor"), t("tenant"), t("colSource"), t("colOutcome")]}
              emptyMessage={loading ? t("loading") : t("empty")}
            >
              {groups.map((group) => (
                <DayRows
                  key={group.key}
                  columns={compact ? 4 : 6}
                  title={dayTitle(group.date)}
                  meta={t("dayMeta", { count: group.entries.length, failures: group.failures })}
                >
                  {group.entries.map((entry) => {
                    const { label, known } = labelOf(entry.action);
                    const area = auditArea(entry.action);
                    const selected = entry.id === selectedId;
                    return (
                      <tr
                        key={entry.id}
                        className={`table-row-clickable audit-row${selected ? " audit-row-selected" : ""}${fresh.has(entry.id) ? " audit-row-fresh" : ""}`}
                        onClick={() => setEntry(selected ? null : entry.id)} /* a11y-ok: Maus-Abkürzung, Tastatur über table-row-link (Zeit) */
                      >
                        <td className="audit-time">
                          <button
                            type="button"
                            className="table-row-link"
                            aria-pressed={selected}
                            aria-label={t("openEntry", { time: formatDateTime(entry.created_at, locale), action: label })}
                            onClick={(event) => {
                              event.stopPropagation();
                              setEntry(selected ? null : entry.id);
                            }}
                          >
                            {formatTime(entry.created_at, locale)}
                          </button>
                        </td>
                        <td>
                          <div className={`audit-action audit-area-${area ?? "none"}`}>
                            <span className="audit-area-dot" aria-hidden="true" />
                            <div className="audit-action-text">
                              <span className={known ? "audit-action-label" : "audit-action-label audit-action-code-only"}>{label}</span>
                              {known ? <span className="audit-log-code">{entry.action}</span> : null}
                            </div>
                          </div>
                        </td>
                        <td>
                          <div className="audit-actor">
                            <span className="audit-avatar" aria-hidden="true">{auditInitials(entry.actor_name ?? entry.actor_email)}</span>
                            <span className="audit-ellipsis">{entry.actor_name ?? entry.actor_email ?? t(`actorKinds.${entry.actor_kind ?? "system"}`)}</span>
                          </div>
                        </td>
                        {compact ? null : <td className="audit-ellipsis">{entry.tenant_name ?? t("platform")}</td>}
                        {compact ? null : <td className="audit-hash">{entry.ip_hash ? entry.ip_hash.slice(0, 16) : "—"}</td>}
                        <td>
                          <Badge variant={entry.outcome === "failure" ? "danger" : "neutral"} dot>{t(`outcome.${entry.outcome}`)}</Badge>
                        </td>
                      </tr>
                    );
                  })}
                </DayRows>
              ))}
            </DataTable>
          )}
          <div className="audit-footer">
            <span className="muted">{total ? t("shown", { shown: items.length, total }) : t("none")}</span>
            <span className="audit-keys muted">
              <kbd>J</kbd>
              <kbd>K</kbd>
              {t("navigateHint")}
            </span>
            {items.length < total ? (
              <button type="button" className="button-secondary" disabled={loading} onClick={() => void loadMore()}>
                {t("loadMore")}
              </button>
            ) : null}
          </div>
        </div>

        {detail ? (
          <AuditDetail
            detail={detail}
            onClose={() => setEntry(null)}
            onPrevious={() => setEntry(stepSelection(ids, selectedId, -1))}
            onNext={() => setEntry(stepSelection(ids, selectedId, 1))}
            onSelect={setEntry}
            onPivot={(patch) => setFilters(patch)}
            onCopied={(message) => showToast(message, "success")}
          />
        ) : null}
      </div>
    </div>
  );
}

function DayRows({ title, meta, columns, children }: { title: string; meta: string; columns: number; children: ReactNode }) {
  return (
    <>
      <tr className="audit-day-row">
        <th scope="colgroup" colSpan={columns}>
          <span>{title}</span>
          <span className="audit-day-meta">{meta}</span>
        </th>
      </tr>
      {children}
    </>
  );
}

function ActiveFilters({ filters, onClear }: { filters: AuditFilters; onClear: (patch: Partial<AuditFilters>) => void }) {
  const t = useTranslations("admin.auditLog");
  const chips: { key: string; label: string; clear: Partial<AuditFilters> }[] = [];
  if (filters.actor_kind) chips.push({ key: "actor", label: t(filters.actor_id ? "active.actorSelected" : `actorKinds.${filters.actor_kind}`), clear: { actor_kind: "", actor_id: "" } });
  if (filters.source) chips.push({ key: "source", label: t("active.source", { source: filters.source }), clear: { source: "" } });
  if (filters.entity_type) chips.push({ key: "entity", label: t("active.entity", { entity: `${filters.entity_type}${filters.entity_id ? ` #${filters.entity_id}` : ""}` }), clear: { entity_type: "", entity_id: "" } });
  if (chips.length === 0) return null;
  return (
    <div className="audit-active-filters">
      {chips.map((chip) => (
        <button key={chip.key} type="button" className="button-pill" aria-label={t("active.remove", { filter: chip.label })} onClick={() => onClear(chip.clear)}>
          {chip.label} <span aria-hidden="true">×</span>
        </button>
      ))}
    </div>
  );
}

function AuditTimeline({ timeline }: { timeline: Timeline }) {
  const t = useTranslations("admin.auditLog");
  const locale = useLocale();
  const summaryId = useId();
  const max = Math.max(1, ...timeline.buckets.map((bucket) => bucket.success + bucket.failure));
  const { events, failures, persons, sources } = timeline.totals;
  const share = events ? Math.round((failures / events) * 100) : 0;
  const first = timeline.buckets[0]?.start;
  const middle = timeline.buckets[Math.floor(timeline.buckets.length / 2)]?.start;
  return (
    <div className="audit-timeline">
      <div className="audit-stats">
        <div><strong>{events}</strong><span className="muted">{t("stats.events")}</span></div>
        <div className={failures ? "audit-stat-alert" : undefined}><strong>{failures}</strong><span className="muted">{t("stats.failures", { share })}</span></div>
        <div><strong>{persons}</strong><span className="muted">{t("stats.persons")}</span></div>
        <div><strong>{sources}</strong><span className="muted">{t("stats.sources")}</span></div>
        <div className="audit-legend">
          <span><span className="audit-legend-dot audit-legend-ok" aria-hidden="true" />{t("outcome.success")}</span>
          <span><span className="audit-legend-dot audit-legend-fail" aria-hidden="true" />{t("outcome.failure")}</span>
        </div>
      </div>
      <p id={summaryId} className="visually-hidden">{t("timelineSummary", { events, failures })}</p>
      <div className="audit-bars" role="img" aria-label={t("timelineLabel")} aria-describedby={summaryId}>
        {timeline.buckets.map((bucket) => {
          const sum = bucket.success + bucket.failure;
          const height = sum ? Math.max(6, (sum / max) * 100) : 3;
          return (
            <div key={bucket.start} className="audit-bar" title={t("barTitle", { time: formatDateTime(bucket.start, locale), count: sum, failures: bucket.failure })}>
              {/* Höhen sind Laufzeitwerte (Anteil am Maximum) */}
              <div className="audit-bar-fail" style={{ height: `${sum ? (bucket.failure / sum) * height : 0}%` }} />
              <div className="audit-bar-ok" style={{ height: `${sum ? (bucket.success / sum) * height : height}%` }} />
            </div>
          );
        })}
      </div>
      <div className="audit-axis">
        <span>{first ? formatDateTime(first, locale) : null}</span>
        <span>{middle ? formatDateTime(middle, locale) : null}</span>
        <span>{t("now")}</span>
      </div>
      <details className="admin-analytics-table">
        <summary>{t("showTable")}</summary>
        <DataTable columns={[t("colTime"), t("outcome.success"), t("outcome.failure")]}>
          {timeline.buckets.map((bucket) => (
            <tr key={bucket.start}>
              <td>{formatDateTime(bucket.start, locale)}</td>
              <td>{bucket.success}</td>
              <td>{bucket.failure}</td>
            </tr>
          ))}
        </DataTable>
      </details>
    </div>
  );
}

function AuditDetail({
  detail, onClose, onPrevious, onNext, onSelect, onPivot, onCopied,
}: {
  detail: EntryDetail;
  onClose: () => void;
  onPrevious: () => void;
  onNext: () => void;
  onSelect: (id: number) => void;
  onPivot: (patch: Partial<AuditFilters>) => void;
  onCopied: (message: string) => void;
}) {
  const t = useTranslations("admin.auditLog");
  const tActions = useTranslations("common.auditActions");
  const locale = useLocale();
  const { entry, context } = detail;
  const { label } = auditActionLabel(entry.action, tActions);
  const area = auditArea(entry.action);
  const diff = auditDiff(entry.details);
  const raw = JSON.stringify(entry, null, 2);
  const headingId = useId();

  async function copy(text: string, message: string) {
    try {
      await navigator.clipboard.writeText(text);
      onCopied(message);
    } catch {
      // ohne Zwischenablage (unsicherer Kontext): nichts zu tun
    }
  }

  return (
    <aside className="audit-detail card" aria-labelledby={headingId} onKeyDown={(event) => { if (event.key === "Escape") onClose(); }}>
      <div className="audit-detail-head">
        <span className={`audit-detail-area audit-area-${area ?? "none"}`}>
          <span className="audit-area-dot" aria-hidden="true" />
          {area ? t(`areas.${area}`) : t("areas.other")}
        </span>
        <div className="audit-detail-nav">
          <button type="button" className="button-icon" aria-label={t("detail.previous")} title={t("detail.previous")} onClick={onPrevious}>↑</button>
          <button type="button" className="button-icon" aria-label={t("detail.next")} title={t("detail.next")} onClick={onNext}>↓</button>
          <button type="button" className="button-icon" aria-label={t("detail.close")} title={t("detail.close")} onClick={onClose}>✕</button>
        </div>
      </div>
      <h2 id={headingId} className="section-title">{label}</h2>
      <div className="audit-detail-badges">
        <Badge variant={entry.outcome === "failure" ? "danger" : "neutral"} dot>{t(`outcome.${entry.outcome}`)}</Badge>
        <code className="audit-log-code">{entry.action}</code>
      </div>

      <dl className="admin-key-value">
        <div><dt>{t("detail.time")}</dt><dd>{formatDateTime(entry.created_at, locale)}</dd></div>
        <div><dt>{t("colActor")}</dt><dd>{entry.actor_name ?? t(`actorKinds.${entry.actor_kind ?? "system"}`)}</dd></div>
        <div><dt>{t("detail.email")}</dt><dd>{entry.actor_email ?? "—"}</dd></div>
        <div><dt>{t("tenant")}</dt><dd>{entry.tenant_id ? <Link href={`/admin/tenants/${entry.tenant_id}` as Route}>{entry.tenant_name}</Link> : t("platform")}</dd></div>
        <div><dt>{t("colSource")}</dt><dd><code>{entry.ip_hash ?? "—"}</code></dd></div>
        <div><dt>{t("detailEntity")}</dt><dd><code>{entry.entity_type ? `${entry.entity_type}${entry.entity_id ? ` #${entry.entity_id}` : ""}` : "—"}</code></dd></div>
      </dl>

      <div className="audit-pivots">
        {entry.actor_id && entry.actor_kind && entry.actor_kind !== "system" ? (
          <button type="button" className="button-secondary" onClick={() => onPivot({ actor_kind: entry.actor_kind ?? "", actor_id: entry.actor_id ?? "" })}>
            {t("pivot.person")}
          </button>
        ) : null}
        {entry.ip_hash ? (
          <button type="button" className="button-secondary" onClick={() => onPivot({ source: (entry.ip_hash ?? "").slice(0, 8) })}>{t("pivot.source")}</button>
        ) : null}
        <button type="button" className="button-secondary" onClick={() => onPivot({ action: entry.action })}>{t("pivot.action")}</button>
      </div>

      {diff ? (
        <div className="audit-detail-section">
          <h3 className="audit-detail-title">{t("detail.change")}</h3>
          <div className="audit-diff">
            {diff.field ? <div className="audit-diff-field">{diff.field}</div> : null}
            <div className="audit-diff-before"><span aria-hidden="true">−</span><span className="visually-hidden">{t("detail.before")}</span><span>{diff.before}</span></div>
            <div className="audit-diff-after"><span aria-hidden="true">+</span><span className="visually-hidden">{t("detail.after")}</span><span>{diff.after}</span></div>
          </div>
        </div>
      ) : null}

      {context.length > 0 ? (
        <div className="audit-detail-section">
          <h3 className="audit-detail-title">{t("detail.context")}</h3>
          <ul className="audit-context">
            {context.map((item) => {
              const itemArea = auditArea(item.action);
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    className={`audit-context-item audit-area-${itemArea ?? "none"}${item.id === entry.id ? " audit-context-current" : ""}${item.outcome === "failure" ? " audit-context-failure" : ""}`}
                    aria-current={item.id === entry.id ? "true" : undefined}
                    onClick={() => onSelect(item.id)}
                  >
                    <span className="audit-hash">{formatTime(item.created_at, locale)}</span>
                    <span className="audit-area-dot" aria-hidden="true" />
                    <span className="audit-ellipsis">{auditActionLabel(item.action, tActions).label}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      <div className="audit-detail-section">
        <div className="audit-detail-raw-head">
          <h3 className="audit-detail-title">{t("detail.raw")}</h3>
          <button type="button" className="button-secondary button-ghost" onClick={() => void copy(raw, t("detail.jsonCopied"))}>{t("detail.copyJson")}</button>
        </div>
        <pre className="audit-raw">{raw}</pre>
      </div>

      <button type="button" className="button-secondary" onClick={() => void copy(`${window.location.origin}/admin/security/audit?entry=${entry.id}`, t("detail.linkCopied"))}>
        {t("detail.copyLink")}
      </button>
    </aside>
  );
}
