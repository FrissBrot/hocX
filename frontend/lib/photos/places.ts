// Foto-Standorte (Backend: services/photo_places.py, Migration 0260): Anzeige des Ortsnamens,
// Treffer der Ortssuche und Umkreis-Filter. Reine Hilfsfunktionen - `t` kommt vom Aufrufer
// (Namespace "photos.places").

export type PhotoPlace = {
  key: string | null;
  name: string | null;
  kind: string | null;
  locality_name: string | null;
  locality_kind: string | null;
  admin1_code: string | null;
  country_code: string | null;
  near: boolean;
  source: "gps" | "manual";
  distance_m: number | null;
};

export type PlaceSearchHit = {
  key: string;
  name: string;
  kind: string;
  admin1_code: string | null;
  admin1_name: string | null;
  country_code: string | null;
  locality_name: string | null;
  radius_km: number;
};

/** Aktiver Umkreis-Filter der Fotosuche (Ort + Radius in km). */
export type PlaceFilter = { key: string; label: string; radiusKm: number; baseRadiusKm: number };

export type PlacesT = (key: string, values?: Record<string, string | number>) => string;

export const PLACE_RADIUS_STEP_KM = 10;
export const PLACE_RADIUS_MAX_KM = 200;

const KNOWN_KINDS = new Set([
  "city", "town", "village", "hamlet", "district", "peak", "pass", "hut", "lake", "glacier", "poi", "station", "field", "region",
]);

export function countryName(code: string | null, locale: string): string | null {
  if (!code) return null;
  try {
    return new Intl.DisplayNames([locale], { type: "region" }).of(code) ?? code;
  } catch {
    return code;
  }
}

/** «Kandersteg BE» in der Schweiz, sonst «Chamonix-Mont-Blanc, Frankreich». */
export function regionLabel(name: string | null, adminCode: string | null, countryCode: string | null, locale: string): string | null {
  if (!name) return countryName(countryCode, locale);
  if (countryCode === "CH") return adminCode && /^[A-Z]{2}$/.test(adminCode) ? `${name} ${adminCode}` : name; // i18n-ok: Ortsname + Kantonskürzel
  const country = countryName(countryCode, locale);
  return country ? `${name}, ${country}` : name; // i18n-ok: Ortsname + Land
}

/** Ortsname am Foto, z. B. «Nähe Blüemlisalphütte, Kandersteg BE». */
export function formatPlaceLabel(place: PhotoPlace | null | undefined, t: PlacesT, locale: string): string | null {
  if (!place) return null;
  const locality = regionLabel(place.locality_name, place.admin1_code, place.country_code, locale);
  if (place.name) {
    return locality ? t("labelNearWithLocality", { place: place.name, locality }) : t("labelNear", { place: place.name });
  }
  if (!locality) return null;
  return place.near ? t("labelNear", { place: locality }) : locality;
}

export function kindLabel(kind: string | null, t: PlacesT): string {
  return t(`kinds.${kind && KNOWN_KINDS.has(kind) ? kind : "poi"}`);
}

/** Treffer der Ortssuche: «Blüemlisalphütte SAC · Hütte · Kandersteg BE». */
export function formatSearchHit(hit: PlaceSearchHit, t: PlacesT, locale: string): string {
  const context = hit.locality_name
    ? regionLabel(hit.locality_name, hit.admin1_code, hit.country_code, locale)
    : hit.country_code === "CH"
      ? hit.admin1_code
      : countryName(hit.country_code, locale);
  return [hit.name, kindLabel(hit.kind, t), context].filter(Boolean).join(" · "); // i18n-ok: Trennzeichen
}

/** Kurzname eines Treffers für den Filter-Chip («Kandersteg BE»). */
export function hitShortLabel(hit: PlaceSearchHit, locale: string): string {
  return hit.locality_name || hit.kind === "region" ? hit.name : regionLabel(hit.name, hit.admin1_code, hit.country_code, locale) ?? hit.name;
}

export function placeFilterQuery(filter: PlaceFilter | null): string {
  if (!filter) return "";
  const params = new URLSearchParams();
  params.set("near", filter.key);
  params.set("near_km", String(filter.radiusKm));
  return params.toString();
}

export function widenRadius(filter: PlaceFilter): PlaceFilter {
  return { ...filter, radiusKm: Math.min(PLACE_RADIUS_MAX_KM, filter.radiusKm + PLACE_RADIUS_STEP_KM) };
}

// Umkreis je Ortsart wie im Backend (photo_places.RADIUS_KM) - für Chip und «+10 km»
const RADIUS_KM: Record<string, number> = {
  peak: 2, hut: 2, pass: 2, poi: 2, station: 2, field: 2, hamlet: 2, lake: 3, glacier: 3, district: 3,
  village: 5, town: 10, city: 20, region: 20,
};

export function radiusForKind(kind: string | null): number {
  return (kind && RADIUS_KM[kind]) || 5;
}
