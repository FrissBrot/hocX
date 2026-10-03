"use client";

import { useEffect, useRef, useState } from "react";

import { layoutElevationLabels } from "./hiking-tour-elevation-labels";

import { Area, AreaChart, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ElevationProfilePoint, HikingTourWaypoint, MarchTimeTable } from "@/types/api";

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
  waypoints,
  marchTable,
  onHoverPoint,
}: {
  points: ElevationProfilePoint[];
  waypoints: HikingTourWaypoint[];
  marchTable: MarchTimeTable | null;
  onHoverPoint?: (point: ElevationProfilePoint | null) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  const [textWidths, setTextWidths] = useState<number[]>([]);
  const markers = waypoints.flatMap((waypoint, index) => {
    if (!points.length || waypoint.kind === "EMERGENCY_EXIT") return [];
    const entry = marchTable?.entries.find((candidate) => candidate.sequence === waypoint.sequence && candidate.kind === waypoint.kind);
    // Ohne Marschtabelle dient der räumlich nächste Profilpunkt als Position.
    const nearest = points.reduce((best, point) => {
      const distance = (candidate: ElevationProfilePoint) =>
        ((candidate.lon - waypoint.lon) * Math.cos(waypoint.lat * Math.PI / 180)) ** 2 + (candidate.lat - waypoint.lat) ** 2;
      return distance(point) < distance(best) ? point : best;
    });
    const distance = Math.max(points[0].distance_m, Math.min(entry?.cumulative_distance_m ?? nearest.distance_m, points[points.length - 1].distance_m));
    const rightIndex = points.findIndex((point) => point.distance_m >= distance);
    const right = points[rightIndex];
    const left = points[Math.max(0, rightIndex - 1)];
    const fraction = right.distance_m === left.distance_m ? 0 : (distance - left.distance_m) / (right.distance_m - left.distance_m);
    const point = { ...nearest, distance_m: distance, elevation_m: left.elevation_m + fraction * (right.elevation_m - left.elevation_m) };
    return [{ waypoint, point, label: waypoint.label || String(index + 1) }];
  });

  const labelsKey = JSON.stringify(markers.map((marker) => marker.label));
  useEffect(() => {
    const context = document.createElement("canvas").getContext("2d");
    if (!context || !containerRef.current) return;
    const style = getComputedStyle(containerRef.current);
    context.font = `${style.getPropertyValue("--text-xs").trim()} ${style.fontFamily}`;
    const labels: string[] = JSON.parse(labelsKey);
    setTextWidths(labels.map((label) => context.measureText(label).width));
  }, [labelsKey]);
  const start = points[0]?.distance_m ?? 0;
  const span = (points[points.length - 1]?.distance_m ?? start) - start;
  const minElevation = Math.min(...points.map((point) => point.elevation_m)) - 20;
  const maxElevation = Math.max(...points.map((point) => point.elevation_m)) + 20;
  const profileY = (elevation: number) => (maxElevation - elevation) / (maxElevation - minElevation) * 170;
  const layout = layoutElevationLabels(markers.map((marker, index) => ({
    x: 44 + (span ? (marker.point.distance_m - start) / span : 0) * Math.max(0, width - 52),
    y: profileY(marker.point.elevation_m),
    width: textWidths[index] ?? marker.label.length * 12,
  })), width);
  const labelHeight = Math.max(16, ...layout.map((label, index) => 28 + label.lane * 20 - profileY(markers[index].point.elevation_m)));

  return (
    <div ref={containerRef}>
    <ResponsiveContainer width="100%" height={200 + labelHeight} onResize={(nextWidth) => setWidth(nextWidth)}>

      <AreaChart
        data={points}
        margin={{ top: labelHeight, right: 8, bottom: 0, left: 0 }}
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
          type="number"
          domain={["dataMin", "dataMax"]}
          tickFormatter={(value: number) => (value / 1000).toFixed(1)}
          tick={{ fontSize: 11 }}
          stroke="var(--muted)"
          label={{ value: "km", position: "insideBottomRight", offset: -4, fontSize: 11, fill: "var(--muted)" }} // design-ok: SVG-Achsenbeschriftung (Recharts-Prop, wie tick={{fontSize}} oben), keine CSS-Schrift
        />
        <YAxis
          dataKey="elevation_m"
          domain={points.length ? [minElevation, maxElevation] : [0, 1]}
          allowDataOverflow
          tickFormatter={(value: number) => `${Math.round(value)}`}
          tick={{ fontSize: 11 }}
          stroke="var(--muted)"
          width={44}
        />
        <Tooltip content={<ElevationTooltip />} />
        <Area type="monotone" dataKey="elevation_m" stroke="var(--chart-1)" strokeWidth={2} fill="url(#wanderplaner-elevation-fill)" />
        {markers.map(({ waypoint, point, label }, index) => (
          <ReferenceDot
            key={waypoint.id}
            x={point.distance_m}
            y={point.elevation_m}
            r={4}
            fill="var(--accent)"
            stroke="var(--panel-solid)"
            label={({ viewBox }) => {
              const box = viewBox as { x: number; y: number; width: number; height: number };
              const cx = box.x + box.width / 2;
              const cy = box.y + box.height / 2;
              const placement = layout[index];
              const y = cy - 12 - placement.lane * 20;
              return (
                <g>
                  <path d={`M${cx},${cy - 5} L${placement.x},${y + 4}`} className="wanderplaner-elevation-leader" />
                  <text x={placement.x} y={y} textAnchor="middle" className="wanderplaner-elevation-label">{label}</text>
                </g>
              );
            }}
            onMouseEnter={() => onHoverPoint?.({ ...point, lat: waypoint.lat, lon: waypoint.lon })}
            onMouseLeave={() => onHoverPoint?.(null)}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
    </div>
  );
}
