// connect-src erlaubt zusaetzlich https://api.friendlycaptcha.com: components/captcha-widget.tsx
// bindet das Friendly-Captcha-Skript zwar selbst gehostet ein (public/friendly-challenge.module.min.js,
// data-worker-src ebenfalls self-hosted unter public/friendly-challenge.worker.min.js -> keine
// Ausnahme in script-src/worker-src noetig), das Widget loest die Proof-of-Work-Challenge aber per
// XHR/fetch gegen den data-puzzle-endpoint https://api.friendlycaptcha.com/api/v1/puzzle - ohne
// diese Ausnahme wuerde jeder Upload-Versuch am blockierten Captcha scheitern.
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
      "worker-src 'self'",
      "object-src 'none'",
      "frame-src 'none'",
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ].join("; "),
  },
];

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
};

export default nextConfig;
