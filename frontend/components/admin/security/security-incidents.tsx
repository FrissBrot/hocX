"use client";

import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Pagination } from "@/components/ui/pagination";
import { SearchInput } from "@/components/ui/search-input";
import { StatTile } from "@/components/ui/stat-tile";
import { StatusBanner } from "@/components/ui/status-banner";
import {
  SecurityIncidentDetailView,
  useAffectedLabel,
  useDurationText,
  useRuleTitle,
} from "@/components/admin/security/security-incident-detail";
import { SecurityPageHeader } from "@/components/admin/security/security-page-header";
import { useAdminResource } from "@/components/admin/security/use-admin-resource";
import {
  INCIDENT_SEVERITIES,
  INCIDENT_STATUSES,
  incidentApiQuery,
  incidentDurationSeconds,
  incidentFiltersFromParams,
  incidentFiltersToParams,
  incidentLabel,
  isOpenStatus,
  parseIncidentId,
  severityVariant,
  statusVariant,
  type IncidentFilters,
} from "@/lib/admin/security-incidents";
import { useVisibleInterval } from "@/lib/hooks/use-visible-interval";
import { formatDateTime } from "@/lib/utils/format";
import type { SecurityIncident, SecurityIncidentList, SecurityIncidentStats } from "@/types/admin-security";

const PAGE_SIZE = 50;
const BOARD_SIZE = 100;
const POLL_MS = 30_000;

function useIncidentUrlState() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [state, setState] = useState(() => {
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    return { filters: incidentFiltersFromParams(params), incident: parseIncidentId(params.get("incident")) };
  });
  useEffect(() => {
    const next = incidentFiltersToParams(state.filters, state.incident).toString();
    if (typeof window !== "undefined" && window.location.search.replace(/^\?/, "") !== next) {
      router.replace((next ? `${pathname}?${next}` : pathname) as Route, { scroll: false });
    }
  }, [state, pathname, router]);
  const setFilters = useCallback(
    (patch: Partial<IncidentFilters>) =>
      setState((current) => ({ ...current, filters: { ...current.filters, page: 0, ...patch } })),
    [],
  );
  const setIncident = useCallback((incident: number | null) => setState((current) => ({ ...current, incident })), []);
  return { filters: state.filters, incident: state.incident, setFilters, setIncident };
}

/** /admin/security/incidents (1.6, Design «hocX Sicherheit Vorfälle»): Kennzahlen, Filter (in der
 * URL nur Codes und die Vorfall-Nummer), Liste oder Board, Detail mit Status, Zuständig und Notizen. */
export function SecurityIncidents() {
  const t = useTranslations("adminSecurity.incidents");
  const tRoot = useTranslations("adminSecurity");
  const { filters, incident, setFilters, setIncident } = useIncidentUrlState();
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query), 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  const limit = filters.view === "board" ? BOARD_SIZE : PAGE_SIZE;
  const listPath = `/api/admin/auth-security/incidents?${incidentApiQuery(filters, { q: debounced, limit }).toString()}`;
  const list = useAdminResource<SecurityIncidentList>(listPath);
  const stats = useAdminResource<SecurityIncidentStats>("/api/admin/auth-security/incidents/stats");
  const reloadList = list.reload;
  const reloadStats = stats.reload;
  const reloadAll = useCallback(() => {
    reloadList();
    reloadStats();
  }, [reloadList, reloadStats]);
  useVisibleInterval(reloadAll, POLL_MS);

  const header = <SecurityPageHeader title={t("title")} description={t("description")} />;
  if (list.forbidden || stats.forbidden) {
    return (
      <>
        {header}
        <StatusBanner tone="neutral" message={tRoot("ownerOnly")} />
      </>
    );
  }

  const counts = list.data?.counts;
  const items = list.data?.items ?? [];

  return (
    <>
      {header}
      {list.failed || stats.failed ? <StatusBanner tone="error" message={tRoot("loadFailed")} /> : null}
      {stats.data ? <IncidentStats stats={stats.data} /> : null}

      <section className="card section-stack admin-incident-filters" aria-label={t("filtersLabel")}>
        <div className="admin-incident-filter-row">
          <SearchInput
            value={query}
            onChange={setQuery}
            placeholder={t("searchPlaceholder")}
            aria-label={t("searchLabel")}
            clearLabel={t("searchClear")}
            maxLength={40}
            className="admin-incident-search"
          />
          <div className="admin-incident-chips" role="group" aria-label={t("severityFilter")}>
            {INCIDENT_SEVERITIES.map((severity) => {
              const active = filters.severities.includes(severity);
              return (
                <button
                  key={severity}
                  type="button"
                  className={`button-pill${active ? " button-pill-active" : ""}`}
                  aria-pressed={active}
                  onClick={() =>
                    setFilters({ severities: active ? filters.severities.filter((value) => value !== severity) : [...filters.severities, severity] })
                  }
                >
                  <span className={`admin-incident-dot admin-incident-dot-${severity}`} aria-hidden="true" />
                  {tRoot(`severity.${severity}`)}
                </button>
              );
            })}
          </div>
          <div className="admin-incident-filter-group">
            <span className="field-label" id="incident-assignee-filter">{t("assigneeFilter")}</span>
            <div aria-labelledby="incident-assignee-filter" role="group">
              <FilterTabs
                options={(["all", "me", "none"] as const).map((value) => ({ value, label: t(`assignee.${value}`) }))}
                value={filters.assignee}
                onChange={(assignee) => setFilters({ assignee })}
              />
            </div>
          </div>
          <div className="admin-incident-filter-group">
            <span className="field-label" id="incident-view-filter">{t("views.label")}</span>
            <div aria-labelledby="incident-view-filter" role="group">
              <FilterTabs
                options={(["list", "board"] as const).map((value) => ({ value, label: t(`views.${value}`) }))}
                value={filters.view}
                onChange={(view) => setFilters({ view })}
              />
            </div>
          </div>
        </div>
        {filters.view === "list" ? (
          <div role="group" aria-label={t("statusFilter")}>
            <FilterTabs
              variant="chips"
              options={(["open", "new", "in_progress", "closed", "all"] as const).map((value) => ({
                value, label: t(`statusGroups.${value}`), count: counts?.[value],
              }))}
              value={filters.status}
              onChange={(status) => setFilters({ status })}
            />
          </div>
        ) : null}
      </section>

      <div className={`admin-security-events-layout${incident ? " admin-security-events-layout-detail" : ""}`}>
        <section className="admin-security-events-main" aria-label={t("listLabel")}>
          {filters.view === "list" ? (
            <>
              <IncidentTable items={items} loading={list.loading} selected={incident} onSelect={setIncident} />
              <Pagination
                offset={filters.page * PAGE_SIZE}
                limit={PAGE_SIZE}
                total={list.data?.total ?? 0}
                onOffsetChange={(offset) => setFilters({ page: Math.floor(offset / PAGE_SIZE) })}
              />
            </>
          ) : (
            <IncidentBoard items={items} selected={incident} onSelect={setIncident} />
          )}
        </section>
        {incident ? (
          <SecurityIncidentDetailView key={incident} incidentId={incident} variant="drawer" onClose={() => setIncident(null)} onChanged={reloadAll} />
        ) : null}
      </div>
    </>
  );
}

function IncidentStats({ stats }: { stats: SecurityIncidentStats }) {
  const t = useTranslations("adminSecurity.incidents.stats");
  const durationText = useDurationText();
  const locale = useLocale();
  const rate = stats.false_positive_rate === null ? "–" : new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 }).format(stats.false_positive_rate); // i18n-ok: Platzhalter
  return (
    <div className="admin-incident-stats">
      <StatTile
        label={t("open")}
        value={stats.open}
        status={stats.critical > 0 ? "critical" : stats.open > 0 ? "warning" : "ok"}
        statusLabel={t("openHint", { count: stats.critical })}
      />
      <StatTile label={t("unassigned")} value={stats.unassigned} hint={t("unassignedHint")} />
      <StatTile label={t("mtta")} value={durationText(stats.mtta_seconds)} hint={t("periodHint", { days: stats.days })} />
      <StatTile label={t("mttr")} value={durationText(stats.mttr_seconds)} hint={t("periodHint", { days: stats.days })} />
      <StatTile label={t("falsePositive")} value={rate} hint={t("falsePositiveHint", { count: stats.false_positives, total: stats.closed, days: stats.days })} />
    </div>
  );
}

function Spark({ values, label }: { values: number[]; label: string }) {
  const max = Math.max(1, ...values);
  return (
    <span className="admin-incident-spark" role="img" aria-label={label}>
      {values.map((value, index) => (
        // Höhe = Laufzeitwert (Anteil am Maximum)
        <span key={index} className="admin-incident-spark-bar" style={{ height: `${Math.max(8, (value / max) * 100)}%` }} />
      ))}
    </span>
  );
}

function IncidentTable({
  items, loading, selected, onSelect,
}: {
  items: SecurityIncident[];
  loading: boolean;
  selected: number | null;
  onSelect: (id: number) => void;
}) {
  const t = useTranslations("adminSecurity.incidents");
  const tRoot = useTranslations("adminSecurity");
  const locale = useLocale();
  const ruleTitle = useRuleTitle();
  const affected = useAffectedLabel();
  const durationText = useDurationText();
  const now = useMemo(() => Date.now(), [items]); // eslint-disable-line react-hooks/exhaustive-deps -- Dauer je Abruf
  const columns = [t("columns.id"), t("columns.incident"), t("columns.affected"), t("columns.status"), t("columns.trend"),
    t("columns.assignee"), t("columns.start"), t("columns.duration")];
  return (
    <DataTable columns={columns} emptyMessage={loading ? undefined : t("empty")}>
      {items.map((item) => (
        <tr key={item.id} className={`${selected === item.id ? "admin-incident-row-selected" : ""}${isOpenStatus(item.status) ? "" : " admin-incident-row-closed"}`}>
          <td>
            <span className={`admin-incident-dot admin-incident-dot-${item.severity}`} aria-hidden="true" />
            <button type="button" className="table-row-link admin-security-mono admin-incident-id-link" aria-label={t("openIncident", { label: incidentLabel(item.id) })} onClick={() => onSelect(item.id)}>
              {incidentLabel(item.id)}
            </button>
          </td>
          <td>
            <span>{ruleTitle(item.rule)}</span>
            <div className="muted admin-cell-sub">
              <Badge variant={severityVariant(item.severity)}>{tRoot(`severity.${item.severity}`)}</Badge>{" "}
              {item.active ? t("active") : t("cleared")} · {t("triggers", { count: item.trigger_count })}
            </div>
          </td>
          <td>{affected(item)}</td>
          <td><Badge variant={statusVariant(item.status)} dot>{tRoot(`statuses.${item.status}`)}</Badge></td>
          <td>{item.spark ? <Spark values={item.spark} label={t("sparkLabel", { values: item.spark.join(", ") })} /> : null}</td>
          <td>{item.assignee?.name ?? <span className="muted">{t("nobody")}</span>}</td>
          <td>{formatDateTime(item.first_seen_at, locale)}</td>
          <td>{durationText(incidentDurationSeconds(item.first_seen_at, item.closed_at, now))}</td>
        </tr>
      ))}
    </DataTable>
  );
}

function IncidentBoard({ items, selected, onSelect }: { items: SecurityIncident[]; selected: number | null; onSelect: (id: number) => void }) {
  const t = useTranslations("adminSecurity.incidents");
  const tRoot = useTranslations("adminSecurity");
  const locale = useLocale();
  const ruleTitle = useRuleTitle();
  const affected = useAffectedLabel();
  return (
    <div className="admin-incident-board">
      {INCIDENT_STATUSES.map((status) => {
        const column = items.filter((item) => item.status === status);
        const headingId = `incident-board-${status}`;
        return (
          <section key={status} className="admin-incident-column" aria-labelledby={headingId}>
            <h2 id={headingId} className="admin-incident-column-head">
              <Badge variant={statusVariant(status)} dot>{tRoot(`statuses.${status}`)}</Badge>
              <span className="muted">{column.length}</span>
            </h2>
            {column.length === 0 ? <p className="muted">{t("boardEmpty")}</p> : (
              <ul className="admin-incident-column-list">
                {column.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      className={`admin-incident-card${selected === item.id ? " admin-incident-card-selected" : ""}`}
                      aria-pressed={selected === item.id}
                      onClick={() => onSelect(item.id)}
                    >
                      <span className="admin-incident-card-meta">
                        <span className="admin-security-mono">{incidentLabel(item.id)}</span>
                        <Badge variant={severityVariant(item.severity)}>{tRoot(`severity.${item.severity}`)}</Badge>
                        <span className="muted">{formatDateTime(item.first_seen_at, locale)}</span>
                      </span>
                      <strong className="admin-incident-card-title">{ruleTitle(item.rule)}</strong>
                      <span className="muted">{affected(item)} · {item.assignee?.name ?? t("nobody")}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}
