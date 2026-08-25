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
// script-src braucht 'unsafe-inline': per echtem Playwright-Browser-Test (nicht nur `npm run
// build`) festgestellt, dass der App Router auf dynamischen Seiten (z.B. /[tenantSlug]) selbst
// mehrere inline <script>-Tags fuer den RSC-Hydration-Payload einbettet (self.__next_f.push...),
// unabhaengig vom eigenen App-Code. Ohne 'unsafe-inline' wurden diese von der CSP geblockt und
// die Seite hydratisierte nie (kein Fehler im Server-Log, nur eine tote Seite im Browser) - der
// urspruengliche Build-only-Test hatte das nicht erkannt. Ein Nonce-basierter Ansatz waere die
// sauberere Loesung, ist hier aber (wie in frontend/next.config.mjs) bewusst zurueckgestellt.
const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      "script-src 'self' 'unsafe-inline'",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data: blob:",
      "font-src 'self'",
      "connect-src 'self' https://api.friendlycaptcha.com",
      "worker-src 'self' blob:",
      "object-src 'none'",
      "frame-src 'none'",
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ].join("; "),
  },
];

const apiProxyTarget = process.env.ABGABEBOX_API_PROXY_TARGET?.replace(/\/$/, "");

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  experimental: {
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

export default nextConfig;
