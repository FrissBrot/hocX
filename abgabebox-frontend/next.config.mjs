import createNextIntlPlugin from "next-intl/plugin";

// connect-src erlaubt zusaetzlich https://api.friendlycaptcha.com: components/captcha-widget.tsx
// bindet das Friendly-Captcha-Skript zwar selbst gehostet ein (public/friendly-challenge.module.min.js),
// das Widget loest die Proof-of-Work-Challenge aber per XHR/fetch gegen den data-puzzle-endpoint
// https://api.friendlycaptcha.com/api/v1/puzzle - ohne diese Ausnahme wuerde jeder Upload-Versuch
// am blockierten Captcha scheitern.
//
// worker-src braucht zusaetzlich 'blob:': data-worker-src (public/friendly-challenge.worker.min.js)
// wird vom Bundle nie gelesen - das Modul hat den Worker-Code inline als String eingebettet und
// erzeugt den Worker immer per `new Worker(URL.createObjectURL(new Blob([...])))`, also aus einer
// blob:-URL, unabhaengig vom eigenen Hosting. `worker-src 'self'` erlaubt laut CSP-Spec kein
// automatisches Fallback auf blob: und blockiert die Worker-Erzeugung, was das Widget selbst als
// "Background worker error undefined" anzeigt (Verifizierung fehlgeschlagen).
//
// Die Content-Security-Policy setzt proxy.ts pro Request mit Nonce (lib/csp.ts, Security-Audit
// SEC-012) - vorher stand hier eine statische Policy mit script-src 'unsafe-inline', weil der App
// Router die RSC-Hydration-Skripte inline einbettet.

const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  // Die URL enthaelt das Link-Token, das selbst die Zugangsberechtigung ist - es darf weder als
  // Referer an Dritte gelangen noch von Suchmaschinen indexiert werden.
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "X-Robots-Tag", value: "noindex, nofollow" },
  { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
];

const apiProxyTarget = process.env.ABGABEBOX_API_PROXY_TARGET?.replace(/\/$/, "");

const withNextIntl = createNextIntlPlugin("./i18n/request.ts");

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Kein "X-Powered-By: Next.js" (Security-Audit SEC-012).
  poweredByHeader: false,
  // Same reasoning as frontend/next.config.mjs: `next dev` only auto-allows "localhost" and
  // its --hostname, but this repo's e2e stack reaches the dev server via 127.0.0.1. Without
  // this the HMR websocket is rejected and the page never hydrates (markup renders, but
  // upload-form.tsx's effects/handlers - e.g. the dev captcha auto-bypass and the file
  // drop-zone's onChange - never run, leaving "Abgeben" permanently disabled). Has no effect
  // outside dev.
  allowedDevOrigins: ["127.0.0.1"],
  experimental: {
    proxyClientMaxBodySize: 158334976,
    staleTimes: {
      dynamic: 0,
    },
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: securityHeaders,
      },
    ];
  },
  async rewrites() {
    if (!apiProxyTarget) {
      return [];
    }
    return [
      {
        source: "/api/:path*",
        destination: `${apiProxyTarget}/api/:path*`,
      },
    ];
  },
};

export default withNextIntl(nextConfig);
