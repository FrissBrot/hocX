// connect-src erlaubt zusaetzlich https://api.friendlycaptcha.com: components/captcha-widget.tsx
// bindet das Friendly-Captcha-Skript zwar selbst gehostet ein (public/friendly-challenge.module.min.js,
// data-worker-src ebenfalls self-hosted unter public/friendly-challenge.worker.min.js -> keine
// Ausnahme in script-src/worker-src noetig), das Widget loest die Proof-of-Work-Challenge aber per
// XHR/fetch gegen den data-puzzle-endpoint https://api.friendlycaptcha.com/api/v1/puzzle - ohne
// diese Ausnahme wuerde jeder Upload-Versuch am blockierten Captcha scheitern. Keine Inline-Scripts
// in dieser App (siehe app/layout.tsx) -> script-src bleibt strikt ohne 'unsafe-inline'.
const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      "script-src 'self'",
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
