import { ElevationProfilePoint, TerrainDangerLevel, TerrainDangerSegment } from "@/types/api";

import { DANGER_COLOR_TOKEN } from "./hiking-tour-danger";

// Gleiche Token-Zuordnung wie Karte und Legende (hiking-tour-danger.ts), hier als SVG-taugliche
// var(...)-Strings (Recharts akzeptiert diese direkt als stopColor - kein getComputedStyle
// nötig, anders als bei MapLibres Canvas-Paint).
const DANGER_COLOR = Object.fromEntries(
  Object.entries(DANGER_COLOR_TOKEN).map(([danger, token]) => [danger, `var(${token})`]),
) as Record<TerrainDangerLevel, string>;

export type DangerGradientStop = { offset: string; color: string };

const FALLBACK_STOPS: DangerGradientStop[] = [
  { offset: "0%", color: DANGER_COLOR.normal },
  { offset: "100%", color: DANGER_COLOR.normal },
];

/** Übersetzt die Gefahrensegmente (tourweite Distanz) in Gradient-Stops über die Distanz-Range
 * des Höhenprofil-Charts. Zwei Stops an derselben Offset-Grenze mit unterschiedlicher Farbe
 * ergeben in SVG einen harten Farbwechsel statt eines weichen Verlaufs zwischen den Abschnitten
 * - genau das wird hier gebraucht (Abschnittsfarbe, kein Verlauf). Ohne Segmente/Punkte bleibt
 * es bei der bisherigen einfarbigen Linie. */
export function buildDangerGradientStops(points: ElevationProfilePoint[], segments?: TerrainDangerSegment[]): DangerGradientStop[] {
  if (!segments?.length || points.length < 2) return FALLBACK_STOPS;
  const start = points[0].distance_m;
  const span = points[points.length - 1].distance_m - start;
  if (span <= 0) return FALLBACK_STOPS;
  const offsetOf = (distance_m: number) => {
    const clamped = Math.min(Math.max(distance_m, start), start + span);
    return `${(((clamped - start) / span) * 100).toFixed(2)}%`;
  };
  return segments.flatMap((segment) => [
    { offset: offsetOf(segment.from_m), color: DANGER_COLOR[segment.danger] },
    { offset: offsetOf(segment.to_m), color: DANGER_COLOR[segment.danger] },
  ]);
}
