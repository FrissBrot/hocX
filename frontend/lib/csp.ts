/**
 * Content-Security-Policy mit Nonce (Audit MAIN-FE-013): proxy.ts erzeugt pro Request eine
 * Nonce, setzt diesen Header auf Request (Next liest daraus die Nonce für seine eigenen Skripte)
 * und Antwort; app/layout.tsx versieht seine zwei Inline-Skripte damit. 'strict-dynamic' lässt
 * von dort nachgeladene Chunks zu, ein eingeschleustes Inline-Skript ohne Nonce läuft nicht.
 * Styles bleiben 'unsafe-inline' (React-style-Attribute, keine Skriptausführung).
 */
export const NONCE_HEADER = "x-nonce";

export function createNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

/**
 * Einzige Seite mit gelockerter CSP: der Google Picker des Datei-Imports (Plan Cloud-Import §5.3,
 * Google Drive mit drive.file). Er lädt den API-Loader von apis.google.com (per Nonce-Skript, danach
 * über 'strict-dynamic'), zeigt die Auswahl in einem iframe von docs.google.com und lädt Vorschaubilder.
 * Gilt nur für genau diesen Pfad (proxy.ts) - die Seite navigiert danach mit einem vollen Seitenwechsel
 * zurück, damit die gelockerte CSP nie für andere Ansichten gilt.
 */
export const GOOGLE_PICKER_PATH = "/files/import/google-picker";

const GOOGLE_PICKER_SOURCES = {
  script: ["https://apis.google.com"],
  frame: ["https://docs.google.com", "https://drive.google.com"],
  connect: ["https://apis.google.com", "https://www.googleapis.com", "https://content.googleapis.com"],
  // Vorschaubilder/Symbole des Pickers - nur Googles Bild-Hosts, nicht ganz *.googleusercontent.com
  img: [
    "https://lh3.googleusercontent.com",
    "https://lh4.googleusercontent.com",
    "https://lh5.googleusercontent.com",
    "https://lh6.googleusercontent.com",
    "https://drive-thirdparty.googleusercontent.com",
    "https://ssl.gstatic.com",
    "https://www.gstatic.com",
  ],
};

export type CspVariant = "default" | "google-picker";

export function cspVariantForPath(pathname: string): CspVariant {
  return pathname === GOOGLE_PICKER_PATH ? "google-picker" : "default";
}

export function contentSecurityPolicy(
  nonce: string,
  isDevelopment = process.env.NODE_ENV !== "production",
  variant: CspVariant = "default",
): string {
  const picker = variant === "google-picker";
  const extra = (sources: string[]) => (picker ? ` ${sources.join(" ")}` : "");
  const scriptSrc = ["'self'", `'nonce-${nonce}'`, "'strict-dynamic'", isDevelopment && "'unsafe-eval'"]
    .filter(Boolean)
    .join(" ");
  return [
    "default-src 'self'",
    `script-src ${scriptSrc}${extra(GOOGLE_PICKER_SOURCES.script)}`,
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' data: blob:${extra(GOOGLE_PICKER_SOURCES.img)}`,
    "font-src 'self'",
    `connect-src 'self'${extra(GOOGLE_PICKER_SOURCES.connect)}`,
    "object-src 'none'",
    picker ? `frame-src ${GOOGLE_PICKER_SOURCES.frame.join(" ")}` : "frame-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");
}
