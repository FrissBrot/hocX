/**
 * Ländername zu einem Ländercode (ISO 3166-1 alpha-2) in der UI-Sprache, über die CLDR-Daten des
 * Browsers (Intl.DisplayNames) - keine eigene Namensliste. Die Codes stammen aus der lokalen
 * GeoIP-Datenbank des Backends (DB-IP «IP to Country Lite», backend/app/core/geoip.py).
 * Unbekannte oder ungültige Codes: der Code selbst bzw. null.
 */
export function countryName(code: string | null | undefined, locale: string): string | null {
  if (!code || !/^[A-Z]{2}$/.test(code)) return null;
  try {
    return new Intl.DisplayNames([locale], { type: "region", fallback: "code" }).of(code) ?? code;
  } catch {
    return code;
  }
}

/** Quellenangabe der Länderdaten (CC BY 4.0 verlangt sie dort, wo die Daten erscheinen). */
export const COUNTRY_SOURCE_URL = "https://db-ip.com";
