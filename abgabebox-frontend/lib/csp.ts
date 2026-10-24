/**
 * Content-Security-Policy mit Nonce für die Abgabebox (Security-Audit SEC-012), gleiches Muster
 * wie frontend/lib/csp.ts: proxy.ts erzeugt pro Request eine Nonce, setzt sie auf Request (Next
 * liest daraus die Nonce für seine eigenen Inline-Skripte, z. B. den RSC-Payload) und Antwort;
 * app/layout.tsx versieht sein Theme-Skript damit. 'strict-dynamic' lässt von dort nachgeladene
 * Skripte zu (Chunks, das selbst gehostete Friendly-Captcha-Modul aus lib/friendly-captcha.ts).
 * Vorher war 'unsafe-inline' nötig, weil Next die Hydration-Skripte inline einbettet.
 *
 * connect-src/worker-src: siehe Kommentar in next.config.mjs (Friendly Captcha).
 */
import { resolvePuzzleEndpoint } from "@/lib/friendly-captcha";

export const NONCE_HEADER = "x-nonce";

export function createNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

// Origin des Captcha-Puzzle-Endpunkts (FRIENDLY_CAPTCHA_PUZZLE_URL, Standard global).
export function captchaConnectOrigin(value = process.env.FRIENDLY_CAPTCHA_PUZZLE_URL): string {
  return new URL(resolvePuzzleEndpoint(value)).origin;
}

export function contentSecurityPolicy(
  nonce: string,
  isDevelopment = process.env.NODE_ENV !== "production",
  captchaOrigin = captchaConnectOrigin(),
): string {
  const scriptSrc = ["'self'", `'nonce-${nonce}'`, "'strict-dynamic'", isDevelopment && "'unsafe-eval'"]
    .filter(Boolean)
    .join(" ");
  return [
    "default-src 'self'",
    `script-src ${scriptSrc}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    `connect-src 'self' ${captchaOrigin}`,
    "worker-src 'self' blob:",
    "object-src 'none'",
    "frame-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");
}
