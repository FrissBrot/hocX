import { ElevationProfilePoint, MarchTimeEntry, TerrainDangerLevel, TerrainDangerSegment } from "@/types/api";

// Reine Rechenhilfen für die Live-Navigation der Mobile-Ansicht (hiking-tour-mobile.tsx):
// Position auf die geplante Route projizieren, Restdistanz/-aufstieg, Gefahren voraus,
// Zeitplan. Alles clientseitig - der Standort verlässt das Gerät nie.

export type TrackPoint = { lat: number; lon: number; distance_m: number; elevation_m: number | null };

const EARTH_RADIUS_M = 6_371_000;

function toRad(value: number): number {
  return (value * Math.PI) / 180;
}

export function haversineM(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(a)));
}

/** Track aus dem Höhenprofil (Distanzen passen dann exakt zu Gefahrensegmenten und Marschtabelle);
 * ohne Profil aus den Routenkoordinaten ([lat, lon]) mit selbst berechneten Distanzen. */
export function buildTrack(profile: ElevationProfilePoint[] | null | undefined, routeCoordinates: [number, number][]): TrackPoint[] {
  if (profile && profile.length >= 2) {
    return profile.map((point) => ({ lat: point.lat, lon: point.lon, distance_m: point.distance_m, elevation_m: point.elevation_m }));
  }
  const track: TrackPoint[] = [];
  routeCoordinates.forEach(([lat, lon], index) => {
    const previous = track[index - 1];
    const distance_m = previous ? previous.distance_m + haversineM(previous.lat, previous.lon, lat, lon) : 0;
    track.push({ lat, lon, distance_m, elevation_m: null });
  });
  return track;
}

export type TrackProjection = { distance_m: number; offset_m: number; lat: number; lon: number };

/** Nächster Punkt auf dem Track (lokal eben gerechnet - für Distanzen bis wenige km genau genug). */
export function projectOnTrack(track: TrackPoint[], lat: number, lon: number): TrackProjection | null {
  if (track.length < 2) return null;
  const metersPerDegLat = (Math.PI * EARTH_RADIUS_M) / 180;
  const metersPerDegLon = metersPerDegLat * Math.cos(toRad(lat));
  let best: TrackProjection | null = null;
  for (let index = 1; index < track.length; index += 1) {
    const a = track[index - 1];
    const b = track[index];
    const ax = (a.lon - lon) * metersPerDegLon;
    const ay = (a.lat - lat) * metersPerDegLat;
    const bx = (b.lon - lon) * metersPerDegLon;
    const by = (b.lat - lat) * metersPerDegLat;
    const dx = bx - ax;
    const dy = by - ay;
    const lengthSq = dx * dx + dy * dy;
    const ratio = lengthSq > 0 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / lengthSq)) : 0;
    const px = ax + ratio * dx;
    const py = ay + ratio * dy;
    const offset_m = Math.hypot(px, py);
    if (!best || offset_m < best.offset_m) {
      best = {
        offset_m,
        distance_m: a.distance_m + ratio * (b.distance_m - a.distance_m),
        lat: a.lat + ratio * (b.lat - a.lat),
        lon: a.lon + ratio * (b.lon - a.lon),
      };
    }
  }
  return best;
}

export function trackLength(track: TrackPoint[]): number {
  return track.length ? track[track.length - 1].distance_m : 0;
}

export function elevationAt(track: TrackPoint[], distance_m: number): number | null {
  const index = track.findIndex((point) => point.distance_m >= distance_m);
  if (index < 0) return track[track.length - 1]?.elevation_m ?? null;
  if (index === 0) return track[0].elevation_m;
  const a = track[index - 1];
  const b = track[index];
  if (a.elevation_m === null || b.elevation_m === null) return a.elevation_m ?? b.elevation_m;
  const span = b.distance_m - a.distance_m;
  return span > 0 ? a.elevation_m + ((distance_m - a.distance_m) / span) * (b.elevation_m - a.elevation_m) : a.elevation_m;
}

/** Summe aller Anstiege ab distance_m bis zum Ziel. */
export function remainingAscent(track: TrackPoint[], distance_m: number): number {
  let ascent = 0;
  let previous = elevationAt(track, distance_m);
  for (const point of track) {
    if (point.distance_m <= distance_m || point.elevation_m === null) continue;
    if (previous !== null && point.elevation_m > previous) ascent += point.elevation_m - previous;
    previous = point.elevation_m;
  }
  return ascent;
}

export type DangerAhead =
  | { state: "inside"; danger: Exclude<TerrainDangerLevel, "normal">; remaining_m: number }
  | { state: "ahead"; danger: Exclude<TerrainDangerLevel, "normal">; distance_m: number; length_m: number };

/** Gefahrenabschnitt, in dem man steht, oder der nächste innerhalb von lookahead_m. */
export function dangerAhead(segments: TerrainDangerSegment[] | undefined, distance_m: number, lookahead_m = 1500): DangerAhead | null {
  const relevant = (segments ?? [])
    .filter((segment) => segment.danger !== "normal" && segment.to_m > distance_m)
    .sort((a, b) => a.from_m - b.from_m);
  const current = relevant.find((segment) => segment.from_m <= distance_m);
  if (current) {
    return { state: "inside", danger: current.danger as Exclude<TerrainDangerLevel, "normal">, remaining_m: current.to_m - distance_m };
  }
  const next = relevant[0];
  if (next && next.from_m - distance_m <= lookahead_m) {
    return { state: "ahead", danger: next.danger as Exclude<TerrainDangerLevel, "normal">, distance_m: next.from_m - distance_m, length_m: next.to_m - next.from_m };
  }
  return null;
}

/** Gesamtlänge je Gefahrenstufe (für die Legende unter dem Profil). */
export function dangerLengths(segments: TerrainDangerSegment[] | undefined): Record<"steep_exposed" | "alpine", number> {
  const lengths = { steep_exposed: 0, alpine: 0 };
  for (const segment of segments ?? []) {
    if (segment.danger === "steep_exposed" || segment.danger === "alpine") lengths[segment.danger] += Math.max(0, segment.to_m - segment.from_m);
  }
  return lengths;
}

/** Geplante Minuten seit Start an einer Stelle der Route (Pausen eingerechnet, linear zwischen
 * den Einträgen der Marschtabelle). */
export function plannedMinutesAt(entries: MarchTimeEntry[], distance_m: number): number | null {
  const onRoute = entries.filter((entry) => entry.kind !== "EMERGENCY_EXIT");
  if (!onRoute.length) return null;
  let elapsedBefore = 0;
  for (let index = 0; index < onRoute.length; index += 1) {
    const entry = onRoute[index];
    const startDistance = entry.cumulative_distance_m - entry.segment_distance_m;
    const arrival = elapsedBefore + entry.segment_duration_minutes;
    if (distance_m <= entry.cumulative_distance_m) {
      const ratio = entry.segment_distance_m > 0 ? Math.max(0, (distance_m - startDistance) / entry.segment_distance_m) : 1;
      return elapsedBefore + ratio * entry.segment_duration_minutes;
    }
    elapsedBefore = arrival + (entry.break_minutes ?? 0);
  }
  return elapsedBefore;
}

/** "HH:MM[:SS]" -> Minuten seit Mitternacht. */
export function clockMinutes(value: string | null | undefined): number | null {
  if (!value) return null;
  const match = /^(\d{1,2}):(\d{2})/.exec(value);
  return match ? Number(match[1]) * 60 + Number(match[2]) : null;
}

export function formatClock(minutes: number): string {
  const total = ((Math.round(minutes) % 1440) + 1440) % 1440;
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
