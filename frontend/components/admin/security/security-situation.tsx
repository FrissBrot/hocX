"use client";

import Link from "next/link";
import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { HealthBadge, type HealthState } from "@/components/ui/health-badge";
import { Sparkline } from "@/components/ui/sparkline";
import { StatTile, type StatTileDelta } from "@/components/ui/stat-tile";
import { StatusBanner } from "@/components/ui/status-banner";
import { TimeRangeTabs } from "@/components/ui/time-range-tabs";
import {
  SecurityIncidentDetailView,
  useAffectedLabel,
  useDurationText,
  useRuleTitle,
} from "@/components/admin/security/security-incident-detail";
import { SecurityPageHeader } from "@/components/admin/security/security-page-header";
import { useAdminResource } from "@/components/admin/security/use-admin-resource";
import {
  SITUATION_RANGES,
  SITUATION_SERIES,
  heatmapGrid,
  incidentLabel,
  parseIncidentId,
  percentChange,
  positionPercent,
  severityVariant,
  stackedHeights,
  statusVariant,
  type SituationRange,
  type SituationSeries,
} from "@/lib/admin/security-incidents";
import { useVisibleInterval } from "@/lib/hooks/use-visible-interval";
import { countryName } from "@/lib/utils/country";
import { formatDateTime, formatShortWeekdayDate, formatTime } from "@/lib/utils/format";
import type { AlertRuleRow, SecurityIncidentList, SecuritySituation, SituationLevel } from "@/types/admin-security";

const POLL_MS = 30_000;
const QUEUE_FILTERS = ["open", "closed", "all"] as const;
type QueueFilter = (typeof QUEUE_FILTERS)[number];
const LEVELS: SituationLevel[] = ["calm", "elevated", "attack", "attack_mode"];
const LEVEL_HEALTH: Record<SituationLevel, HealthState> = { calm: "ok", elevated: "warning", attack: "critical", attack_mode: "critical" };
const RULE_HEALTH: Record<AlertRuleRow["state"], HealthState> = { fired: "critical", near: "warning", quiet: "ok" };

function useSituationUrlState() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [state, setState] = useState(() => {
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    const range = params.get("range");
    const queue = params.get("queue");
    return {
      range: (SITUATION_RANGES as readonly string[]).includes(range ?? "") ? (range as SituationRange) : "24h",
      queue: (QUEUE_FILTERS as readonly string[]).includes(queue ?? "") ? (queue as QueueFilter) : "open",
      incident: parseIncidentId(params.get("incident")),
    };
  });
  useEffect(() => {
    const params = new URLSearchParams();
    if (state.range !== "24h") params.set("range", state.range);
    if (state.queue !== "open") params.set("queue", state.queue);
    if (state.incident) params.set("incident", String(state.incident));
    const next = params.toString();
    if (typeof window !== "undefined" && window.location.search.replace(/^\?/, "") !== next) {
      router.replace((next ? `${pathname}?${next}` : pathname) as Route, { scroll: false });
    }
  }, [state, pathname, router]);
  const update = useCallback((patch: Partial<typeof state>) => setState((current) => ({ ...current, ...patch })), []);
  return { ...state, update };
}

/** /admin/security (1.6, Design «hocX Sicherheit Lagebild»): Lage-Stufe, Kennzahlen mit Verlauf,
 * Vorfälle mit Detail, Verlauf mit Vorfall-Markierungen, Wochenmuster, Alarmregeln, Herkunft. Nur
 * echte Daten; jedes Diagramm mit Zusammenfassung und Tabellenalternative. */
export function SecuritySituationView() {
  const t = useTranslations("adminSecurity.situation");
  const tRoot = useTranslations("adminSecurity");
  const { range, queue, incident, update } = useSituationUrlState();
  const [live, setLive] = useState(true);
  const data = useAdminResource<SecuritySituation>(`/api/admin/auth-security/situation?range=${range}`);
  const queueList = useAdminResource<SecurityIncidentList>(`/api/admin/auth-security/incidents?status=${queue}&limit=8&spark=false`);
  const rules = useAdminResource<AlertRuleRow[]>("/api/admin/auth-security/alert-rules");
  const reloadData = data.reload;
  const reloadQueue = queueList.reload;
  const reloadRules = rules.reload;
  const poll = useCallback(() => {
    reloadData();
    reloadQueue();
    reloadRules();
  }, [reloadData, reloadQueue, reloadRules]);
  useVisibleInterval(poll, live ? POLL_MS : null);

  // Ohne Auswahl: der schwerste offene Vorfall (wie im Design)
  const selected = incident ?? queueList.data?.items.find((item) => item.status === "new" || item.status === "in_progress")?.id ?? null;

  const header = (
    <SecurityPageHeader
      title={t("title")}
      description={t("description")}
      actions={
        <div className="admin-situation-actions">
          <TimeRangeTabs ranges={SITUATION_RANGES} value={range} onChange={(value) => update({ range: value })} />
          <button
            type="button"
            className="button-secondary button-ghost admin-situation-live"
            aria-pressed={live}
            title={t("liveLabel")}
            onClick={() => setLive((value) => !value)}
          >
            <span className={`admin-situation-live-dot${live ? " admin-situation-live-dot-on" : ""}`} aria-hidden="true" />
            {live ? t("live") : t("paused")}
          </button>
        </div>
      }
    />
  );

  if (data.forbidden) {
    return (
      <>
        {header}
        <StatusBanner tone="neutral" message={tRoot("ownerOnly")} />
      </>
    );
  }

  return (
    <>
      {header}
      {data.failed || queueList.failed ? <StatusBanner tone="error" message={tRoot("loadFailed")} /> : null}
      {data.data ? (
        <div className="admin-situation-top">
          <Posture situation={data.data} />
          <Kpis situation={data.data} />
        </div>
      ) : null}

      <div className="admin-situation-incidents">
        <section className="card section-stack" aria-labelledby="situation-queue">
          <div className="admin-security-section-head">
            <h2 id="situation-queue" className="section-title">{t("queue.title")}</h2>
            <Link href={"/admin/security/incidents" as Route} className="admin-security-inline-link">{t("queue.all")}</Link>
          </div>
          <p className="muted">{t("queue.hint")}</p>
          <FilterTabs
            variant="chips"
            options={QUEUE_FILTERS.map((value) => ({ value, label: t(`queue.filters.${value}`), count: queueList.data?.counts[value] }))}
            value={queue}
            onChange={(value) => update({ queue: value })}
          />
          <IncidentQueue list={queueList.data} loading={queueList.loading} selected={selected} onSelect={(id) => update({ incident: id })} />
        </section>
        {selected ? (
          <SecurityIncidentDetailView key={selected} incidentId={selected} variant="panel" onChanged={poll} />
        ) : (
          <section className="card"><p className="muted">{t("detailEmpty")}</p></section>
        )}
      </div>

      {data.data ? (
        <>
          <div className="admin-situation-row">
            <TrafficChart situation={data.data} onSelect={(id) => update({ incident: id })} />
            <Heatmap situation={data.data} />
          </div>
          <div className="admin-situation-row">
            <RuleMeters rules={rules.data ?? []} />
            <Origins situation={data.data} />
          </div>
        </>
      ) : null}
    </>
  );
}

function Posture({ situation }: { situation: SecuritySituation }) {
  const t = useTranslations("adminSecurity.situation.posture");
  const { posture } = situation;
  const index = LEVELS.indexOf(posture.level);
  return (
    <section className={`card admin-situation-posture admin-situation-posture-${posture.level}`} aria-labelledby="situation-posture">
      <h2 id="situation-posture" className="field-label">{t("title")}</h2>
      <HealthBadge state={LEVEL_HEALTH[posture.level]} label={t(`levels.${posture.level}`)} className="admin-situation-posture-badge" />
      <p>{t(`texts.${posture.level}`, { open: posture.open, critical: posture.critical, near: posture.rules_near })}</p>
      <ol className="admin-situation-steps" aria-label={t("stepsLabel")}>
        {LEVELS.map((level, step) => (
          <li key={level} className={`admin-situation-step${step <= index ? " admin-situation-step-on" : ""}`} aria-current={step === index ? "step" : undefined}>
            <span className="admin-situation-step-bar" aria-hidden="true" />
            <span>{t(`levels.${level}`)}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Kpis({ situation }: { situation: SecuritySituation }) {
  const t = useTranslations("adminSecurity.situation.kpis");
  const tRange = useTranslations("common.timeRange");
  const durationText = useDurationText();
  const locale = useLocale();
  const number = (value: number) => value.toLocaleString(locale);
  const rangeLabel = tRange(situation.range);
  function delta(key: "failures" | "blocked" | "challenged" | "successes" | "admin_logins", badWhenUp: boolean): StatTileDelta {
    const current = situation.totals[key];
    const previous = situation.previous[key];
    const change = percentChange(current, previous);
    const direction = current > previous ? "up" : current < previous ? "down" : "flat"; // i18n-ok: Richtungscodes, kein Text
    return {
      text: change === null ? t("noPrevious", { previous: number(previous) }) : t("vsPrevious", { change, previous: number(previous) }),
      direction,
      tone: direction === "flat" ? "neutral" : (direction === "up") === badWhenUp ? "bad" : "good",
    };
  }
  const series = (key: SituationSeries) => situation.points.map((point) => point[key]);
  const stats = situation.incident_stats;
  return (
    <div className="admin-situation-kpis">
      <StatTile
        label={t("openIncidents")}
        value={number(stats.open)}
        status={stats.critical > 0 ? "critical" : stats.open > 0 ? "warning" : "ok"}
        statusLabel={t("openHint", { count: stats.critical })}
        href="/admin/security/incidents"
      />
      <StatTile label={t("failures", { range: rangeLabel })} value={number(situation.totals.failures)} delta={delta("failures", true)} href="/admin/security/events?outcome=failure">
        <Sparkline values={series("failures")} tone="danger" label={t("sparkLabel", { label: t("failures", { range: rangeLabel }) })} />
      </StatTile>
      <StatTile label={t("blocked", { range: rangeLabel })} value={number(situation.totals.blocked)} hint={t("blockedHint", { count: situation.active_blocks })} href="/admin/security/blocks">
        <Sparkline values={series("blocked")} tone="warning" label={t("sparkLabel", { label: t("blocked", { range: rangeLabel }) })} />
      </StatTile>
      <StatTile label={t("challenged", { range: rangeLabel })} value={number(situation.totals.challenged)} hint={t("challengedHint")}>
        <Sparkline values={series("challenged")} tone="accent" label={t("sparkLabel", { label: t("challenged", { range: rangeLabel }) })} />
      </StatTile>
      <StatTile label={t("successes", { range: rangeLabel })} value={number(situation.totals.successes)} delta={delta("successes", false)}>
        <Sparkline values={series("successes")} tone="success" label={t("sparkLabel", { label: t("successes", { range: rangeLabel }) })} />
      </StatTile>
      <StatTile label={t("adminLogins", { range: rangeLabel })} value={number(situation.totals.admin_logins)} delta={delta("admin_logins", true)} />
      <StatTile label={t("mtta")} value={durationText(stats.mtta_seconds)} hint={t("mttaHint", { days: stats.days })} />
    </div>
  );
}

function IncidentQueue({
  list, loading, selected, onSelect,
}: {
  list: SecurityIncidentList | null;
  loading: boolean;
  selected: number | null;
  onSelect: (id: number) => void;
}) {
  const t = useTranslations("adminSecurity.situation.queue");
  const tRoot = useTranslations("adminSecurity");
  const locale = useLocale();
  const ruleTitle = useRuleTitle();
  const affected = useAffectedLabel();
  const items = list?.items ?? [];
  if (items.length === 0) return <p className="muted">{loading ? null : t("empty")}</p>;
  return (
    <ul className="admin-situation-queue">
      {items.map((item) => (
        <li key={item.id}>
          <button
            type="button"
            className={`admin-incident-card admin-incident-card-${item.severity}${selected === item.id ? " admin-incident-card-selected" : ""}`}
            aria-pressed={selected === item.id}
            onClick={() => onSelect(item.id)}
          >
            <span className="admin-incident-card-meta">
              <span className="admin-security-mono">{incidentLabel(item.id)}</span>
              <Badge variant={severityVariant(item.severity)}>{tRoot(`severity.${item.severity}`)}</Badge>
              <span className="muted">{formatDateTime(item.first_seen_at, locale)}</span>
            </span>
            <strong className="admin-incident-card-title">{ruleTitle(item.rule)}</strong>
            <span className="admin-incident-card-meta">
              <Badge variant={statusVariant(item.status)} dot>{tRoot(`statuses.${item.status}`)}</Badge>
              <span className="muted">{affected(item)} · {item.assignee?.name ?? tRoot("incidents.nobody")}</span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function TrafficChart({ situation, onSelect }: { situation: SecuritySituation; onSelect: (id: number) => void }) {
  const t = useTranslations("adminSecurity.situation.chart");
  const locale = useLocale();
  const summaryId = useId();
  const [asTable, setAsTable] = useState(false);
  const [hidden, setHidden] = useState<SituationSeries[]>([]);
  const visible = SITUATION_SERIES.filter((key) => !hidden.includes(key));
  const heights = useMemo(() => stackedHeights(situation.points, visible), [situation.points, visible]);
  const ticks = situation.points.filter((_, index) => index % Math.max(1, Math.round(situation.points.length / 6)) === 0);
  const label = (iso: string) => (situation.range === "24h" ? formatTime(iso, locale) : `${formatShortWeekdayDate(iso, locale)} ${formatTime(iso, locale)}`);
  return (
    <section className="card section-stack admin-situation-chart" aria-labelledby="situation-chart">
      <div className="admin-security-section-head">
        <div>
          <h2 id="situation-chart" className="section-title">{t("title")}</h2>
          <p className="muted" id={summaryId}>{t("summary", situation.totals)}</p>
        </div>
        <button type="button" className="button-secondary button-ghost" aria-pressed={asTable} onClick={() => setAsTable((value) => !value)}>
          {asTable ? t("showChart") : t("showTable")}
        </button>
      </div>
      <div className="admin-situation-series" role="group" aria-label={t("seriesLabel")}>
        {SITUATION_SERIES.map((key) => (
          <button
            key={key}
            type="button"
            className={`button-pill${hidden.includes(key) ? "" : " button-pill-active"}`}
            aria-pressed={!hidden.includes(key)}
            onClick={() => setHidden((current) => (current.includes(key) ? current.filter((value) => value !== key) : [...current, key]))}
          >
            <span className={`admin-security-swatch admin-situation-fill-${key}`} aria-hidden="true" />
            {t(`series.${key}`)}
          </button>
        ))}
      </div>
      {asTable ? (
        <DataTable columns={[t("columns.bucket"), t("series.failures"), t("series.blocked"), t("series.challenged"), t("series.successes")]}>
          {situation.points.map((point) => (
            <tr key={point.start}>
              <td>{formatDateTime(point.start, locale)}</td>
              <td>{point.failures}</td>
              <td>{point.blocked}</td>
              <td>{point.challenged}</td>
              <td>{point.successes}</td>
            </tr>
          ))}
        </DataTable>
      ) : (
        <>
          {situation.markers.length ? (
            <ul className="admin-situation-markers" aria-label={t("markersLabel")}>
              {situation.markers.map((marker) => (
                <li key={marker.id} style={{ left: `${positionPercent(marker.at, situation.start, situation.end)}%` }}>
                  <button
                    type="button"
                    className={`admin-situation-marker admin-situation-marker-${marker.severity}`}
                    aria-label={t("marker", { label: `#${marker.id}`, time: formatDateTime(marker.at, locale) })} // i18n-ok: Kurzform der Nummer wie die sichtbare Markierung
                    onClick={() => onSelect(marker.id)}
                  >
                    #{marker.id}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          <div className="admin-security-bars admin-situation-bars" role="img" aria-label={t("title")} aria-describedby={summaryId}>
            {situation.points.map((point, index) => (
              <div
                key={point.start}
                className="admin-security-bar"
                title={t("bar", { time: label(point.start), failures: point.failures, blocked: point.blocked, challenged: point.challenged, successes: point.successes })}
              >
                {/* Höhen = Laufzeitwerte (Wurzelskala) */}
                {SITUATION_SERIES.map((key) =>
                  heights[index][key] > 0 ? <div key={key} className={`admin-situation-fill-${key}`} style={{ height: `${heights[index][key]}%` }} /> : null,
                )}
              </div>
            ))}
          </div>
          <div className="admin-situation-ticks" aria-hidden="true">
            {ticks.map((point) => (
              <span key={point.start} style={{ left: `${positionPercent(point.start, situation.start, situation.end)}%` }}>{label(point.start)}</span>
            ))}
          </div>
          <p className="field-help">{t("scaleHint", { minutes: situation.bucket_minutes })}</p>
        </>
      )}
    </section>
  );
}

function Heatmap({ situation }: { situation: SecuritySituation }) {
  const t = useTranslations("adminSecurity.situation.heatmap");
  const summaryId = useId();
  const [asTable, setAsTable] = useState(false);
  const { rows, max } = useMemo(() => heatmapGrid(situation.heatmap), [situation.heatmap]);
  const total = situation.heatmap.reduce((sum, cell) => sum + cell.count, 0);
  return (
    <section className="card section-stack" aria-labelledby="situation-heatmap">
      <div className="admin-security-section-head">
        <div>
          <h2 id="situation-heatmap" className="section-title">{t("title")}</h2>
          <p className="muted" id={summaryId}>{t("summary", { days: situation.heatmap_days, total, max })}</p>
        </div>
        <button type="button" className="button-secondary button-ghost" aria-pressed={asTable} onClick={() => setAsTable((value) => !value)}>
          {asTable ? t("showChart") : t("showTable")}
        </button>
      </div>
      {asTable ? (
        <DataTable columns={[t("columns.day"), ...Array.from({ length: 24 }, (_, hour) => String(hour).padStart(2, "0"))]}>
          {rows.map((row) => (
            <tr key={row[0].dow}>
              <th scope="row">{t(`days.${row[0].dow}`)}</th>
              {row.map((cell) => <td key={cell.hour}>{cell.count}</td>)}
            </tr>
          ))}
        </DataTable>
      ) : (
        <div className="admin-situation-heatmap-scroll">
          <div className="admin-situation-heatmap" role="img" aria-label={t("title")} aria-describedby={summaryId}>
            {rows.map((row) => (
              <div key={row[0].dow} className="admin-situation-heatmap-row">
                <span className="admin-situation-heatmap-day">{t(`days.${row[0].dow}`)}</span>
                {row.map((cell) => (
                  <span
                    key={cell.hour}
                    className={`admin-situation-heat admin-situation-heat-${cell.level}`}
                    title={t("cell", { day: t(`days.${cell.dow}`), hour: String(cell.hour).padStart(2, "0"), count: cell.count })}
                  />
                ))}
              </div>
            ))}
            <div className="admin-situation-heatmap-row admin-situation-heatmap-axis" aria-hidden="true">
              <span />
              {Array.from({ length: 24 }, (_, hour) => <span key={hour}>{hour % 6 === 0 ? String(hour).padStart(2, "0") : ""}</span>)}
            </div>
          </div>
          <div className="admin-situation-legend" aria-hidden="true">
            {t("less")}
            {[1, 2, 3, 4].map((level) => <span key={level} className={`admin-situation-heat admin-situation-heat-${level}`} />)}
            {t("more")}
          </div>
        </div>
      )}
    </section>
  );
}

function RuleMeters({ rules }: { rules: AlertRuleRow[] }) {
  const t = useTranslations("adminSecurity.situation.rules");
  const tRoot = useTranslations("adminSecurity");
  const locale = useLocale();
  const ruleTitle = useRuleTitle();
  return (
    <section className="card section-stack" aria-labelledby="situation-rules">
      <div className="admin-security-section-head">
        <div>
          <h2 id="situation-rules" className="section-title">{t("title")}</h2>
          <p className="muted">{t("hint")}</p>
        </div>
        <Link href={"/admin/security/alerts" as Route} className="admin-security-inline-link">{t("link")}</Link>
      </div>
      <ul className="admin-situation-rules">
        {rules.map((rule) => {
          const ratio = rule.threshold > 0 ? Math.min(1, rule.value / rule.threshold) : 0;
          return (
            <li key={rule.rule} className="admin-situation-rule">
              <span className="admin-situation-rule-head">
                <span>{ruleTitle(rule.rule)}</span>
                <HealthBadge state={RULE_HEALTH[rule.state]} label={tRoot(`rules.states.${rule.state}`)} />
              </span>
              <span
                className="admin-security-meter"
                role="meter"
                aria-valuemin={0}
                aria-valuemax={rule.threshold}
                aria-valuenow={rule.value}
                aria-label={t("meter", { rule: ruleTitle(rule.rule) })}
              >
                {/* Breite = Messwert / Schwelle */}
                <span className={`admin-security-meter-fill admin-situation-rule-fill-${rule.state}`} style={{ width: `${Math.max(2, ratio * 100)}%` }} />
              </span>
              <span className="muted admin-situation-rule-value">
                {t("value", {
                  value: rule.value.toLocaleString(locale),
                  threshold: rule.threshold.toLocaleString(locale),
                  unit: tRoot(`rules.units.${rule.rule}`),
                  minutes: rule.window_minutes,
                })}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Origins({ situation }: { situation: SecuritySituation }) {
  const t = useTranslations("adminSecurity.situation");
  const tRange = useTranslations("common.timeRange");
  const locale = useLocale();
  const summaryId = useId();
  const max = Math.max(1, ...situation.countries.map((country) => country.failures));
  return (
    <section className="card section-stack" aria-labelledby="situation-origins">
      <div>
        <h2 id="situation-origins" className="section-title">{t("countries.title")}</h2>
        <p className="muted" id={summaryId}>{t("countries.hint", { range: tRange(situation.range) })}</p>
      </div>
      {situation.countries.length === 0 ? <p className="muted">{t("countries.empty")}</p> : (
        <DataTable columns={[t("countries.country"), t("countries.share"), t("countries.failures")]}>
          {situation.countries.map((country) => (
            <tr key={country.code ?? "unknown"}>
              <td>{country.code ? `${countryName(country.code, locale) ?? country.code} (${country.code})` : t("countries.unknown")}</td>
              <td aria-hidden="true">
                <span className="admin-situation-share">
                  {/* Breite = Anteil am grössten Land */}
                  <span className={country.code === "CH" ? "admin-situation-share-home" : "admin-situation-share-fill"} style={{ width: `${Math.max(4, (country.failures / max) * 100)}%` }} />
                </span>
              </td>
              <td>{country.failures.toLocaleString(locale)}</td>
            </tr>
          ))}
        </DataTable>
      )}
      <h3 className="audit-detail-title">{t("networks.title")}</h3>
      {situation.networks.length === 0 ? <p className="muted">{t("networks.empty")}</p> : (
        <DataTable columns={[t("networks.net"), t("networks.failures"), t("networks.meta")]}>
          {situation.networks.map((net) => (
            <tr key={net.net}>
              <td>
                <Link href={`/admin/security/events?range=7d&net=${net.net}` as Route} className="admin-security-inline-link"><code>{net.net}</code></Link>
              </td>
              <td>{net.failures.toLocaleString(locale)}</td>
              <td>
                {t("networks.metaText", { accounts: net.accounts, tenants: net.tenants })}
                {net.country ? ` · ${countryName(net.country, locale) ?? net.country}` : null}
              </td>
            </tr>
          ))}
        </DataTable>
      )}
      <h3 className="audit-detail-title">{t("accounts.title")}</h3>
      {situation.accounts.length === 0 ? <p className="muted">{t("accounts.empty")}</p> : (
        <DataTable columns={[t("accounts.account"), t("accounts.failures"), t("accounts.networks")]}>
          {situation.accounts.map((account) => (
            <tr key={account.subject}>
              <td>
                <Link href={`/admin/security/events?range=7d&subject=${account.subject}` as Route} className="admin-security-inline-link"><code>{account.subject}</code></Link>
              </td>
              <td>{account.failures.toLocaleString(locale)}</td>
              <td>{account.networks.toLocaleString(locale)}</td>
            </tr>
          ))}
        </DataTable>
      )}
    </section>
  );
}
