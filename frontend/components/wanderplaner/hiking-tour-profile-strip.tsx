"use client";

import { ElevationProfilePoint, TerrainDangerSegment } from "@/types/api";

const WIDTH = 350;
const HEIGHT = 54;

/** Kompaktes Höhenprofil der Mobile-Ansicht: Gefahrenabschnitte als Bänder, optional die
 * aktuelle Position als Linie. Rein darstellend (aria-hidden), Werte stehen daneben als Text. */
export function HikingTourProfileStrip({
  points,
  dangerSegments,
  positionM,
  compact = false,
}: {
  points: ElevationProfilePoint[];
  dangerSegments?: TerrainDangerSegment[];
  positionM?: number | null;
  compact?: boolean;
}) {
  if (points.length < 2) return null;
  const total = points[points.length - 1].distance_m || 1;
  const elevations = points.map((point) => point.elevation_m);
  const low = Math.min(...elevations);
  const high = Math.max(...elevations);
  const span = high - low || 1;
  const x = (distance: number) => ((distance / total) * WIDTH).toFixed(1);
  const y = (elevation: number) => (HEIGHT - 4 - ((elevation - low) / span) * (HEIGHT - 8)).toFixed(1);
  const line = points.map((point) => `${x(point.distance_m)},${y(point.elevation_m)}`).join(" ");
  return (
    <svg
      className={`wanderplaner-m-profile${compact ? " wanderplaner-m-profile-compact" : ""}`}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      preserveAspectRatio="none"
      aria-hidden="true"
      focusable="false"
    >
      {(dangerSegments ?? [])
        .filter((segment) => segment.danger !== "normal" && segment.to_m > segment.from_m)
        .map((segment) => (
          <rect
            key={`${segment.from_m}-${segment.danger}`}
            className={`wanderplaner-m-profile-band wanderplaner-m-profile-band-${segment.danger}`}
            x={x(segment.from_m)}
            y={0}
            width={x(segment.to_m - segment.from_m)}
            height={HEIGHT}
          />
        ))}
      <polygon className="wanderplaner-m-profile-area" points={`0,${HEIGHT} ${line} ${WIDTH},${HEIGHT}`} />
      <polyline className="wanderplaner-m-profile-line" points={line} />
      {positionM !== null && positionM !== undefined && (
        <line className="wanderplaner-m-profile-position" x1={x(positionM)} x2={x(positionM)} y1={0} y2={HEIGHT} />
      )}
    </svg>
  );
}
