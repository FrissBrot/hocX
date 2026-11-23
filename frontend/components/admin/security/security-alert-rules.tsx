"use client";

import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useId, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { HealthBadge, type HealthState } from "@/components/ui/health-badge";
import { StatusBanner } from "@/components/ui/status-banner";
import { useAdminResource } from "@/components/admin/security/use-admin-resource";
import { useVisibleInterval } from "@/lib/hooks/use-visible-interval";
import { formatDateTime, formatTime } from "@/lib/utils/format";
import type { AlertRuleRow, AlertRuleSeries, AlertRuleState } from "@/types/admin-security";

export const ALERT_RULES = ["stuffing", "spraying", "account_attack", "admin_mfa", "admin_new_device", "blocks", "network", "cross_tenant", "tenant", "limiter"] as const;
const STATE_FILTERS = ["all", "fired", "near", "quiet"] as const;
type StateFilter = (typeof STATE_FILTERS)[number];
const STATE_HEALTH: Record<AlertRuleState, HealthState> = { fired: "critical", near: "warning", quiet: "ok" };
const POLL_MS = 30_000;

function useRuleUrlState() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [state, setState] = useState(() => {
    const filter = params?.get("state") ?? "all";
    const rule = params?.get("rule") ?? "";
    return {
      filter: ((STATE_FILTERS as readonly string[]).includes(filter) ? filter : "all") as StateFilter,
      rule: (ALERT_RULES as readonly string[]).includes(rule) ? rule : "",
    };
  });
  useEffect(() => {
    const query = new URLSearchParams();
    if (state.filter !== "all") query.set("state", state.filter);
    if (state.rule) query.set("rule", state.rule);
    const next = query.toString();
    if (window.location.search.replace(/^\?/, "") !== next) router.replace((next ? `${pathname}?${next}` : pathname) as Route, { scroll: false });
  }, [state, pathname, router]);
  return {
    filter: state.filter,
    rule: state.rule,
    setFilter: (filter: StateFilter) => setState((current) => ({ ...current, filter })),
    setRule: (rule: string) => setState((current) => ({ ...current, rule })),
  };
}

function formatValue(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(value);
}

/** /admin/security/alerts (1.6, Design «hocX Sicherheit Alarmregeln»): alle zehn Regeln mit Messwert
 * gegen Schwelle (auch darunter), Auslösungen 30 Tage, Kurve 24 h je Regel und Einstellungen (nur
 * lesen). Zustand und gewählte Regel stehen in der URL. */
export function SecurityAlertRules() {
  const t = useTranslations("adminSecurity");
  const locale = useLocale();
  const rules = useAdminResource<AlertRuleRow[]>("/api/admin/auth-security/alert-rules");
  const { filter, rule, setFilter, setRule } = useRuleUrlState();
  const reload = rules.reload;
  useVisibleInterval(reload, POLL_MS);

  if (rules.forbidden) return <StatusBanner tone="neutral" message={t("ownerOnly")} />;
  const all = rules.data ?? [];
  const visible = all.filter((item) => filter === "all" || item.state === filter);
  const selected = all.find((item) => item.rule === rule) ?? visible[0] ?? null;

  return (
    <section className="section-stack" aria-labelledby="security-alert-rules">
      <div className="admin-security-section-head">
        <h2 id="security-alert-rules" className="section-title">{t("rules.title")}</h2>
        <FilterTabs<StateFilter>
          variant="chips"
          options={STATE_FILTERS.map((value) => ({
            value,
            label: t(`rules.states.${value}`),
            count: value === "all" ? all.length : all.filter((item) => item.state === value).length,
          }))}
          value={filter}
          onChange={setFilter}
        />
      </div>
      {rules.failed ? <StatusBanner tone="error" message={t("loadFailed")} /> : null}
      <p className="muted">{t("rules.description")}</p>
      <div className="admin-security-rules-layout">
        <ul className="admin-security-rule-list" aria-label={t("rules.listLabel")}>
          {visible.length === 0 && !rules.loading ? <li className="muted">{t("rules.empty")}</li> : null}
          {visible.map((item) => {
            const percent = item.threshold ? Math.min(100, Math.max(2, (item.value / item.threshold) * 100)) : 0;
            const isSelected = selected?.rule === item.rule;
            return (
              <li key={item.rule}>
                <button
                  type="button"
                  className={`admin-security-rule admin-security-rule-${item.state}${isSelected ? " admin-security-rule-selected" : ""}`}
                  aria-pressed={isSelected}
                  onClick={() => setRule(item.rule)}
                >
                  <span className="admin-security-rule-head">
                    <span className="admin-security-rule-name">
                      <strong>{t(`alerts.rules.${item.rule}`)}</strong>
                      <code className="muted">{`auth:${item.rule}`}</code>
                    </span>
                    <HealthBadge state={STATE_HEALTH[item.state]} label={t(`rules.states.${item.state}`)} />
                  </span>
                  <span className="admin-security-rule-body">
                    <span className="admin-security-rule-value">
                      <span className="admin-security-meter" aria-hidden="true">
                        {/* Breite = Laufzeitwert (Anteil an der Schwelle) */}
                        <span className={`admin-security-meter-fill admin-security-rule-fill-${item.state}`} style={{ width: `${percent}%` }} />
                      </span>
                      <span>
                        {t("rules.valueLine", {
                          value: formatValue(item.value, locale),
                          threshold: formatValue(item.threshold, locale),
                          unit: t(`rules.units.${item.rule}`),
                          severity: t(`severity.${item.severity}`),
                          minutes: item.window_minutes,
                        })}
                      </span>
                    </span>
                    <span className="admin-security-rule-history">
                      <span className="admin-security-mini-bars" aria-hidden="true">
                        {item.daily_30d.map((count, index) => (
                          <span key={index} className={count ? `admin-security-mini-bar-on admin-security-mini-bar-${item.severity}` : undefined} />
                        ))}
                      </span>
                      <span className="muted">{t("rules.triggered30", { count: item.triggers_30d })}</span>
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
        {selected ? <RuleDetail rule={selected} /> : null}
      </div>
    </section>
  );
}

function RuleDetail({ rule }: { rule: AlertRuleRow }) {
  const t = useTranslations("adminSecurity");
  const locale = useLocale();
  const headingId = useId();
  const unit = t(`rules.units.${rule.rule}`);
  const firstSetting = Object.values(rule.settings)[0];
  return (
    <article className="card section-stack admin-security-rule-detail" aria-labelledby={headingId}>
      <div className="admin-security-section-head">
        <div>
          <div className="admin-security-rule-tags">
            <code>{`auth:${rule.rule}[:…]`}</code>
            <Badge variant={rule.severity === "critical" ? "danger" : "warning"}>{t(`severity.${rule.severity}`)}</Badge>
          </div>
          <h2 id={headingId} className="section-title">{t(`alerts.rules.${rule.rule}`)}</h2>
        </div>
        <HealthBadge state={STATE_HEALTH[rule.state]} label={t(`rules.states.${rule.state}`)} />
      </div>
      <p className="admin-security-rule-condition">
        {t(`rules.conditions.${rule.rule}`, { threshold: formatValue(rule.threshold, locale), setting: String(firstSetting ?? ""), minutes: rule.window_minutes })}
      </p>
      <RuleSeries rule={rule} unit={unit} />
      <dl className="admin-security-rule-facts">
        <div><dt>{t("rules.facts.now")}</dt><dd>{formatValue(rule.value, locale)} {unit}</dd></div>
        <div><dt>{t("rules.facts.threshold")}</dt><dd>{t(rule.comparator === ">" ? "rules.thresholdAbove" : "rules.thresholdAtLeast", { threshold: formatValue(rule.threshold, locale), unit })}</dd></div>
        <div><dt>{t("rules.facts.window")}</dt><dd>{t("rules.window", { minutes: rule.window_minutes })}</dd></div>
        <div><dt>{t("rules.facts.triggered")}</dt><dd>{rule.triggers_30d}</dd></div>
      </dl>
      <div className="admin-security-columns">
        <div className="section-stack">
          <h3 className="audit-detail-title">{t("rules.settingsTitle")}</h3>
          {Object.keys(rule.settings).length === 0 ? (
            <p className="muted">{t("rules.noSettings")}</p>
          ) : (
            <dl className="admin-key-value">
              {Object.entries(rule.settings).map(([name, value]) => (
                <div key={name}><dt><code>{name.toUpperCase()}</code></dt><dd>{String(value)}</dd></div>
              ))}
            </dl>
          )}
          <p className="field-help">{t("rules.settingsHelp", { minutes: rule.window_minutes })}</p>
        </div>
        <div className="section-stack">
          <h3 className="audit-detail-title">{t("rules.recentTitle")}</h3>
          {rule.recent.length === 0 ? (
            <p className="muted">{t("rules.noRecent")}</p>
          ) : (
            <ul className="admin-security-reason-list">
              {rule.recent.map((item) => (
                <li key={`${item.at}-${item.subject ?? ""}`}>
                  <span>{formatDateTime(item.at, locale)}</span>
                  <span className="admin-security-mono">{item.subject ?? "—"}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </article>
  );
}

function RuleSeries({ rule, unit }: { rule: AlertRuleRow; unit: string }) {
  const t = useTranslations("adminSecurity");
  const locale = useLocale();
  const summaryId = useId();
  const series = useAdminResource<AlertRuleSeries>(`/api/admin/auth-security/alert-rules/${encodeURIComponent(rule.rule)}/series`);
  useVisibleInterval(series.reload, 60_000);
  const points = series.data?.points ?? [];
  const max = Math.max(rule.threshold * 1.25, ...points.map((point) => point.value), 1);
  const peak = points.reduce((best, point) => Math.max(best, point.value), 0);
  const over = points.filter((point) => (rule.comparator === ">" ? point.value > rule.threshold : point.value >= rule.threshold)).length;
  return (
    <div className="section-stack">
      <div className="admin-security-section-head">
        <h3 className="audit-detail-title">{t("rules.seriesTitle")}</h3>
        <span className="muted">{t("rules.seriesThreshold", { threshold: formatValue(rule.threshold, locale), unit })}</span>
      </div>
      <p className="field-help">{t("rules.seriesApprox", { minutes: series.data?.bucket_minutes ?? Math.max(15, rule.window_minutes) })}</p>
      <p id={summaryId} className="visually-hidden">
        {t("rules.seriesSummary", { peak: formatValue(peak, locale), threshold: formatValue(rule.threshold, locale), over, minutes: series.data?.bucket_minutes ?? rule.window_minutes })}
      </p>
      <div className="admin-security-series" role="img" aria-label={t("rules.seriesTitle")} aria-describedby={summaryId}>
        {points.map((point) => {
          const hit = rule.comparator === ">" ? point.value > rule.threshold : point.value >= rule.threshold;
          return (
            <span
              key={point.start}
              className={`admin-security-series-bar${hit ? " admin-security-series-bar-hit" : ""}`}
              style={{ height: `${Math.max(1.5, (point.value / max) * 100)}%` }}
              title={`${formatTime(point.start, locale)}: ${formatValue(point.value, locale)} ${unit}`}
            />
          );
        })}
        {/* Lage der Schwellenlinie = Laufzeitwert */}
        <span className="admin-security-series-threshold" style={{ bottom: `${(rule.threshold / max) * 100}%` }} aria-hidden="true" />
      </div>
      <details className="admin-analytics-table">
        <summary>{t("overview.showTable")}</summary>
        <DataTable columns={[t("events.columns.time"), t("rules.facts.now")]}>
          {points.map((point) => (
            <tr key={point.start}>
              <td>{formatDateTime(point.start, locale)}</td>
              <td>{formatValue(point.value, locale)}</td>
            </tr>
          ))}
        </DataTable>
      </details>
    </div>
  );
}
