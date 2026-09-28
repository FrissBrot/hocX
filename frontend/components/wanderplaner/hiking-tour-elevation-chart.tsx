"use client";

import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ElevationProfilePoint } from "@/types/api";

function ElevationTooltip({ active, payload }: { active?: boolean; payload?: { payload: ElevationProfilePoint }[] }) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="stats-tooltip">
      <div className="stats-tooltip-row">
        <span className="stats-tooltip-name">Distanz:</span>
        <span className="stats-tooltip-val">{(point.distance_m / 1000).toFixed(2)} km</span>
      </div>
      <div className="stats-tooltip-row">
        <span className="stats-tooltip-name">Höhe:</span>
        <span className="stats-tooltip-val">{Math.round(point.elevation_m)} m</span>
      </div>
    </div>
  );
}

type RechartsHoverState = { activePayload?: { payload: ElevationProfilePoint }[] } | null;

export function HikingTourElevationChart({
  points,
  onHoverPoint,
}: {
  points: ElevationProfilePoint[];
  onHoverPoint?: (point: ElevationProfilePoint | null) => void;
}) {
  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart
        data={points}
        onMouseMove={(state: RechartsHoverState) => onHoverPoint?.(state?.activePayload?.[0]?.payload ?? null)}
        onMouseLeave={() => onHoverPoint?.(null)}
      >
        <defs>
          <linearGradient id="wanderplaner-elevation-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.35} />
            <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="distance_m"
          tickFormatter={(value: number) => (value / 1000).toFixed(1)}
          tick={{ fontSize: 11 }}
          stroke="var(--muted)"
          label={{ value: "km", position: "insideBottomRight", offset: -4, fontSize: 11, fill: "var(--muted)" }} // design-ok: SVG-Achsenbeschriftung (Recharts-Prop, wie tick={{fontSize}} oben), keine CSS-Schrift
        />
        <YAxis
          dataKey="elevation_m"
          domain={["dataMin - 20", "dataMax + 20"]}
          tickFormatter={(value: number) => `${Math.round(value)}`}
          tick={{ fontSize: 11 }}
          stroke="var(--muted)"
          width={44}
        />
        <Tooltip content={<ElevationTooltip />} />
        <Area type="monotone" dataKey="elevation_m" stroke="var(--chart-1)" strokeWidth={2} fill="url(#wanderplaner-elevation-fill)" />
      </AreaChart>
    </ResponsiveContainer>
  );
}
