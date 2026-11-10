/**
 * Content-Security-Policy mit Nonce (Audit MAIN-FE-013): proxy.ts erzeugt pro Request eine
 * Nonce, setzt diesen Header auf Request (Next liest daraus die Nonce für seine eigenen Skripte)
 * und Antwort; app/layout.tsx versieht seine zwei Inline-Skripte damit. 'strict-dynamic' lässt
 * von dort nachgeladene Chunks zu, ein eingeschleustes Inline-Skript ohne Nonce läuft nicht.
 * Styles bleiben 'unsafe-inline' (React-style-Attribute, keine Skriptausführung).
 *
 * Wanderplaner-Karte (MapLibre GL, components/wanderplaner/hiking-tour-map.tsx): lädt
 * Vector-Tiles, Style, Höhenprofil und Geocoding direkt im Browser von den offiziellen
 * geo.admin.ch-Diensten (kein Server-Proxy) und parst Tiles in einem Web-Worker aus einer
 * blob:-URL. Wildcard nur für diese eine swisstopo-Domain: die Vector-Tiles kommen über
 * nummerierte, nicht stabile Subdomains (vectortiles0-4.geo.admin.ch).
 */
const GEO_ADMIN_HOSTS = ["https://*.geo.admin.ch"];
export const NONCE_HEADER = "x-nonce";

export function createNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

export function contentSecurityPolicy(nonce: string, isDevelopment = process.env.NODE_ENV !== "production"): string {
  const scriptSrc = ["'self'", `'nonce-${nonce}'`, "'strict-dynamic'", isDevelopment && "'unsafe-eval'"]
    .filter(Boolean)
    .join(" ");
  return [
    "default-src 'self'",
    `script-src ${scriptSrc}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    `connect-src 'self' ${GEO_ADMIN_HOSTS.join(" ")}`,
    "worker-src 'self' blob:",
    "object-src 'none'",
    "frame-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");
}
