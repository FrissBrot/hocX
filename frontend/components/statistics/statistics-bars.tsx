"use client";

import { CSSProperties, ReactNode } from "react";

import { monthLabel, percentLabel, type AttendanceBar } from "./statistics-model";

export { monthLabel, percentLabel };

/**
 * Diagramm-Bausteine der Statistik (Dashboard v2) als schlichte Balken aus CSS statt recharts:
 * Desktop und Mobile zeigen dieselben Formen. Farben über Klassen `stats-fill-<reihe>` in
 * app/styles/statistics.css bzw. home.css - dieselbe Zuordnung wie lib/constants/chart-colors.ts.
 */
export type Series =
  | "present"
  | "late"
  | "excused"
  | "absent"
  | "done"
  | "open"
  | "onTrack"
  | "paid"
  | "finesOpen"
  | "surplus"
  | "deficit"
  | "groupAll"
  | "groupWith"
  | "previous";

const pct = (value: number) => `${Math.max(0, Math.min(1, value)) * 100}%`;

export function ChartLegend({ items }: { items: { series: Series; label: string }[] }) {
  return (
    <div className="stats-legend">
      {items.map((item) => (
        <span key={item.series} className="stats-legend-item">
          <span className={`stats-legend-swatch stats-fill-${item.series}${item.series === "previous" ? " stats-legend-swatch-line" : ""}`} aria-hidden="true" />
          {item.label}
        </span>
      ))}
    </div>
  );
}

/** Gestapelte Säulen je Monat (Anwesenheitsquote) mit Vorjahresmarke. */
export function AttendanceMonthChart({
  bars,
  locale,
  compact = false,
  title,
}: {
  bars: AttendanceBar[];
  locale: string;
  compact?: boolean;
  title: (bar: AttendanceBar) => string;
}) {
  return (
    <div className={`stats-columns${compact ? " stats-columns-compact" : ""}`}>
      {compact ? null : (
        <div className="stats-axis" aria-hidden="true">
          <span>{percentLabel(1, locale)}</span>
          <span>{percentLabel(0.5, locale)}</span>
          <span>0</span>
        </div>
      )}
      <div className="stats-columns-body">
        <div className="stats-columns-plot" role="img" aria-label={bars.map(title).join("; ")}>
          {bars.map((bar) => (
            <div key={bar.month} className="stats-column" title={title(bar)}>
              <span className="stats-fill-absent stats-column-top" style={{ height: pct(bar.absent) }} />
              <span className="stats-fill-excused" style={{ height: pct(bar.excused) }} />
              <span className="stats-fill-late" style={{ height: pct(bar.late) }} />
              <span className="stats-fill-present" style={{ height: pct(bar.present) }} />
              {bar.previousRate !== null ? <span className="stats-column-previous stats-fill-previous" style={{ bottom: pct(bar.previousRate) }} /> : null}
            </div>
          ))}
        </div>
        <div className="stats-columns-labels" aria-hidden="true">
          {bars.map((bar) => (
            <span key={bar.month}>{monthLabel(bar.month, locale, compact ? "narrow" : "short")}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

/** Waagrechter Balken aus Abschnitten (Anteile 0–1 bzw. relative Gewichte). */
export function StackedBar({
  segments,
  width = 1,
  mode = "share",
  className = "",
}: {
  segments: { series: Series; value: number }[];
  /** Länge des ganzen Balkens (0–1), z. B. im Verhältnis zur grössten Zeile */
  width?: number;
  /** share: value ist ein Anteil; weight: value wird relativ zur Summe verteilt */
  mode?: "share" | "weight";
  className?: string;
}) {
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);
  return (
    <div className={`stats-stack ${className}`.trim()} style={{ width: pct(width) }} aria-hidden="true">
      {segments.map((segment) =>
        segment.value > 0 ? (
          <span
            key={segment.series}
            className={`stats-fill-${segment.series}`}
            style={mode === "weight" ? { flex: `${segment.value} 1 0` } : { width: pct(total > 0 ? segment.value : 0) }}
          />
        ) : null
      )}
    </div>
  );
}

/** Fortschrittsbalken auf grauer Schiene. */
export function ProgressBar({ value, series }: { value: number; series: Series }) {
  return (
    <div className="stats-track" aria-hidden="true">
      <span className={`stats-track-fill stats-fill-${series}`} style={{ width: pct(value) }} />
    </div>
  );
}

/** Zwei überlagerte Balken auf einer Schiene (Gruppen: alle Termine / davon mit Teilnehmerzahl). */
export function OverlayBar({ outer, inner }: { outer: number; inner: number }) {
  return (
    <div className="stats-track stats-track-overlay" aria-hidden="true">
      <span className="stats-track-fill stats-fill-groupAll" style={{ width: pct(outer) }} />
      <span className="stats-track-fill stats-fill-groupWith" style={{ width: pct(inner) }} />
    </div>
  );
}

/** Ergebnis je Monat: Überschuss nach oben, Defizit nach unten. */
export function DivergingMonthChart({
  months,
  scale,
  locale,
  compact = false,
  axis,
  title,
}: {
  months: { month: string; net: number }[];
  scale: number;
  locale: string;
  compact?: boolean;
  axis?: { top: string; bottom: string };
  title: (month: { month: string; net: number }) => string;
}) {
  const share = (value: number) => (scale > 0 ? Math.min(1, Math.abs(value) / scale) : 0);
  return (
    <div className={`stats-columns stats-columns-diverging${compact ? " stats-columns-compact" : ""}`}>
      {axis && !compact ? (
        <div className="stats-axis stats-axis-wide" aria-hidden="true">
          <span>{axis.top}</span>
          <span>0</span>
          <span>{axis.bottom}</span>
        </div>
      ) : null}
      <div className="stats-columns-body">
        <div className="stats-columns-plot stats-diverging-plot" role="img" aria-label={months.map(title).join("; ")}>
          {months.map((month) => (
            <div key={month.month} className="stats-diverging-column" title={title(month)}>
              <div className="stats-diverging-half stats-diverging-up">
                {month.net > 0 ? <span className="stats-fill-surplus" style={{ height: pct(share(month.net)) }} /> : null}
              </div>
              <div className="stats-diverging-half stats-diverging-down">
                {month.net < 0 ? <span className="stats-fill-deficit" style={{ height: pct(share(month.net)) }} /> : null}
              </div>
            </div>
          ))}
        </div>
        <div className="stats-columns-labels" aria-hidden="true">
          {months.map((month) => (
            <span key={month.month}>{monthLabel(month.month, locale, compact ? "narrow" : "short")}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

/** Ring mit Anteil (Erledigungsquote). */
export function DonutRing({ value, children }: { value: number; children: ReactNode }) {
  return (
    <div className="stats-ring" style={{ "--stats-ring-value": pct(value) } as CSSProperties}>
      <div className="stats-ring-inner">{children}</div>
    </div>
  );
}
