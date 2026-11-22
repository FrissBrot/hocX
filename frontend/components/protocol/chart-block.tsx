"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import dynamic from "next/dynamic";
import { StatisticsOverview } from "@/types/api";
import { browserApiFetch } from "@/lib/api/client";
import { ChartCycleSelection } from "@/components/protocol/chart-cycle-selection";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { Select } from "@/components/ui/select";

// Recharts (gut 100 KB gzip) erst laden, wenn ein Diagramm tatsächlich gezeichnet wird - nicht
// mit dem Protokoll-Editor, der nur bumpStatsCharts aus dieser Datei braucht.
const loadChartPreview = () => import("@/components/protocol/chart-preview");
const ChartPreview = dynamic(() => loadChartPreview().then((module) => module.ChartPreview), { ssr: false });

const STATS_BUMP_EVENT = "hocx:stats-refresh";
// Hintergrund-Aktualisierung offener Diagramme: nur bei sichtbarem Tab und höchstens einmal pro
// Minute (Concurrency-Audit CONC-016 - vorher alle 15 s, auch in Hintergrund-Tabs). Wird der Tab
// wieder sichtbar und ist der letzte Stand älter, sofort nachladen.
const STATS_POLL_MS = 60_000;
let _statsVersion = 0;
let _lastStatsBump = Date.now();
// Versionen aus der Hintergrund-Aktualisierung dürfen das kurz gecachte Server-Ergebnis nutzen
// (?cached=1); nach eigenen Änderungen (bumpStatsCharts aus dem Editor) wird frisch gerechnet.
const _cachedVersions = new Set<number>();

// Wird auch direkt als Promise-Callback benutzt (`.then(bumpStatsCharts)`) - das Argument ist dann
// ein beliebiger Wert, deshalb nur ein ausdrückliches { allowCached: true } auswerten.
export function bumpStatsCharts(options?: unknown) {
  _statsVersion++;
  if (typeof options === "object" && options !== null && (options as { allowCached?: unknown }).allowCached === true) {
    _cachedVersions.add(_statsVersion);
  }
  _lastStatsBump = Date.now();
  window.dispatchEvent(new Event(STATS_BUMP_EVENT));
}

// Diagramme mit derselben Zyklus-Auswahl teilen Cache, Anfrage und Polling.
type StatsResult = { data: StatisticsOverview | null; stale: boolean };
const statsCaches = new Map<string, { version: number; result: StatsResult }>();
const statsRequests = new Map<string, { version: number; promise: Promise<StatsResult> }>();
let _statsPollInterval: ReturnType<typeof setInterval> | null = null;
let _statsPollRefCount = 0;

function statsPollTick() {
  if (document.visibilityState === "visible") bumpStatsCharts({ allowCached: true });
}

function statsVisibilityChanged() {
  if (document.visibilityState === "visible" && Date.now() - _lastStatsBump >= STATS_POLL_MS) bumpStatsCharts({ allowCached: true });
}

function acquireStatsPolling() {
  _statsPollRefCount++;
  if (!_statsPollInterval) {
    _statsPollInterval = setInterval(statsPollTick, STATS_POLL_MS);
    document.addEventListener("visibilitychange", statsVisibilityChanged);
  }
}

function releaseStatsPolling() {
  _statsPollRefCount = Math.max(0, _statsPollRefCount - 1);
  if (_statsPollRefCount === 0 && _statsPollInterval) {
    clearInterval(_statsPollInterval);
    _statsPollInterval = null;
    document.removeEventListener("visibilitychange", statsVisibilityChanged);
  }
}

function fetchStatsOverview(version: number, scope: string): Promise<StatsResult> {
  const cached = statsCaches.get(scope);
  if (cached?.version === version) return Promise.resolve(cached.result);
  const request = statsRequests.get(scope);
  if (request?.version === version) return request.promise;
  const cachedParam = _cachedVersions.has(version) ? "&cached=1" : "";
  const promise = browserApiFetch<StatisticsOverview>(`/api/statistics/overview?_t=${version}${cachedParam}${scope}`)
    .then((data) => {
      const result = { data: data ?? null, stale: false };
      statsCaches.set(scope, { version, result });
      return result;
    })
    .catch(() => ({ data: cached?.result.data ?? null, stale: !!cached?.result.data }))
    .finally(() => { if (statsRequests.get(scope)?.version === version) statsRequests.delete(scope); });
  statsRequests.set(scope, { version, promise });
  return promise;
}

function chartOptions(t: (key: string) => string) {
  return [
    { value: "attendance_over_time", label: t("options.attendanceOverTime") },
    { value: "attendance_by_participant", label: t("options.attendanceByParticipant") },
    { value: "finance_by_month", label: t("options.financeByMonth") },
    { value: "fines_by_participant", label: t("options.finesByParticipant") },
    { value: "fines_by_type", label: t("options.finesByType") },
    { value: "groups_sessions", label: t("options.groupsSessions") },
    { value: "groups_avg", label: t("options.groupsAvg") },
    { value: "todos", label: t("options.todos") },
  ];
}

type Config = {
  chart_type?: string;
  cycle_key?: string;
  cycle_config_id?: string | null;
  cycle_offset?: number;
};

type Props = {
  config: Config;
  editable: boolean;
  onSave: (cfg: Record<string, unknown>) => void;
};

export function ChartBlock({ config, editable, onSave }: Props) {
  const t = useTranslations("protocols.chart");
  const locale = useLocale();
  const scope = config.cycle_config_id ? `&cycle_config_id=${encodeURIComponent(config.cycle_config_id)}&cycle_offset=${config.cycle_offset ?? 0}` : "";
  const [data, setData] = useState<StatisticsOverview | null>(null);
  const [stale, setStale] = useState(false);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(() => _statsVersion);
  const chartType = config.chart_type ?? "";
  const cycleKey = config.cycle_key ?? "all";

  useEffect(() => {
    // Diagramm-Code parallel zu den Statistikdaten holen, damit das Diagramm nicht später erscheint
    void loadChartPreview();
    const refresh = () => setTick(_statsVersion);
    window.addEventListener(STATS_BUMP_EVENT, refresh);
    acquireStatsPolling();
    return () => {
      window.removeEventListener(STATS_BUMP_EVENT, refresh);
      releaseStatsPolling();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchStatsOverview(tick, scope).then(({ data: d, stale: s }) => {
      if (cancelled) return;
      setData(d);
      setStale(s);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [tick, scope]);

  function save(partial: Partial<Config>) {
    onSave({ ...config, ...partial });
  }

  if (loading) return <div className="muted" style={{ padding: "var(--space-3) 0" }}>{t("loading")}</div>;
  if (!data) return <div className="muted" style={{ padding: "var(--space-3) 0" }}>{t("noData")}</div>;

  const hasCycles = data.cycles.length > 0;
  const cycleOptions = [
    { key: "all", label: t("allCycles") },
    ...data.cycles.map((c) => ({ key: `${c.cycle_config_id}:${c.cycle_year}`, label: c.label })),
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      {editable && (
        <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap", alignItems: "center" }}>
          <Select
            className="stats-cycle-select"
            value={chartType}
            onChange={(e) => save({ chart_type: e.target.value })}
            style={{ minWidth: 220 }}
          >
            <option value="">{t("selectPlaceholder")}</option>
            {chartOptions(t).map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </Select>
          {!config.cycle_config_id && hasCycles && (chartType === "groups_sessions" || chartType === "groups_avg") && (
            <SearchableSelect
              className="stats-cycle-select"
              options={cycleOptions}
              getId={(o) => o.key}
              getLabel={(o) => o.label}
              value={cycleKey}
              onChange={(o) => save({ cycle_key: o ? o.key : "all" })}
            />
          )}
        </div>
      )}
      {editable && <ChartCycleSelection config={config} onChange={(partial) => save({ ...partial, cycle_key: "all" })} />}
      {!editable && !chartType && (
        <p className="muted">{t("noChartSelected")}</p>
      )}
      {stale && (
        <p className="muted" style={{ fontSize: "var(--text-xs)" }}>
          ⚠ {t("staleWarning")}
        </p>
      )}
      {chartType && <ChartPreview chartType={chartType} cycleKey={cycleKey} data={data} t={t} locale={locale} />}
    </div>
  );
}
