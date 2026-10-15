import { ElevationProfilePoint, TerrainDangerLevel, TerrainDangerSegment } from "@/types/api";

// Gefahreneinschätzung (siehe wanderplaner-backend/app/core/route_danger.py): gemeinsame Farben
// und Texte für Karte, Höhenprofil und Legende. "alpine" (amtlicher Status Alpinwanderweg) hat
// Vorrang vor "steep_exposed" (Geländeanalyse), siehe merge_with_official_status.
export const DANGER_COLOR_TOKEN: Record<TerrainDangerLevel, string> = {
  normal: "--route-normal",
  steep_exposed: "--route-steep",
  alpine: "--route-alpine",
};

export const DANGER_LEGEND: { danger: TerrainDangerLevel; label: string; description: string }[] = [
  { danger: "normal", label: "Route", description: "Wanderweg/Bergwanderweg ohne erkannte Gefahrenstelle" },
  { danger: "steep_exposed", label: "Steil/ausgesetzt", description: "Über 40 % Steigung oder über 70 % Gefälle direkt neben dem Weg" },
  { danger: "alpine", label: "Alpinwanderweg", description: "Amtlich als Alpinwanderweg signalisiert" },
];

/** Profilpunkt an einer Distanz, linear zwischen den Nachbarpunkten interpoliert. */
function pointAt(profile: ElevationProfilePoint[], distance_m: number): [number, number] {
  const index = profile.findIndex((point) => point.distance_m >= distance_m);
  if (index <= 0) {
    const edge = index === 0 ? profile[0] : profile[profile.length - 1];
    return [edge.lon, edge.lat];
  }
  const previous = profile[index - 1];
  const next = profile[index];
  const span = next.distance_m - previous.distance_m;
  const ratio = span > 0 ? (distance_m - previous.distance_m) / span : 0;
  return [previous.lon + ratio * (next.lon - previous.lon), previous.lat + ratio * (next.lat - previous.lat)];
}

/** Liniengeometrie je Gefahrensegment. Die Segmentgrenzen werden auf dem Höhenprofil
 * interpoliert: die Gefahreneinschätzung rechnet mit etwa 10 m Auflösung, das angezeigte Profil
 * hat nur rund 200 Punkte - kurze Gefahrenstellen lägen sonst oft zwischen zwei Profilpunkten
 * und würden gar nicht gezeichnet. */
export function buildDangerLineFeatures(
  profile: ElevationProfilePoint[],
  segments: TerrainDangerSegment[],
): GeoJSON.Feature<GeoJSON.LineString, { danger: TerrainDangerLevel }>[] {
  if (profile.length < 2) return [];
  return segments.flatMap((segment) => {
    if (segment.to_m <= segment.from_m) return [];
    const inner = profile
      .filter((point) => point.distance_m > segment.from_m && point.distance_m < segment.to_m)
      .map((point): [number, number] => [point.lon, point.lat]);
    return [{
      type: "Feature" as const,
      properties: { danger: segment.danger },
      geometry: {
        type: "LineString" as const,
        coordinates: [pointAt(profile, segment.from_m), ...inner, pointAt(profile, segment.to_m)],
      },
    }];
  });
}
