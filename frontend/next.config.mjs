import createNextIntlPlugin from "next-intl/plugin";

// CSP script-src erlaubt 'unsafe-inline': app/layout.tsx rendert zwei Inline-<script>-Tags
// (Runtime-Config __HOCX_CONFIG__ + Theme-Vorab-Anwendung vor dem ersten Paint, um FOUC zu
// vermeiden) ueber dangerouslySetInnerHTML, dazu kommen die Inline-Skripte von Next selbst.
// Eine statische CSP in next.config.mjs kann dafuer keine Nonce tragen (Nonces sind pro Request).
//
// Stand nach Audit MAIN-FE-013: Die fruehere Begruendung ("proxy.ts schliesst /login und
// /admin/login vom Matcher aus") gilt nicht mehr - der Matcher in proxy.ts erfasst inzwischen
// alle Seiten inkl. der Login-Seiten. Der Weg zu einer Nonce-CSP ist damit offen: proxy.ts
// erzeugt pro Request eine Nonce, setzt den CSP-Header (script-src 'self' 'nonce-…'
// 'strict-dynamic') und reicht sie per Request-Header `x-nonce` weiter; layout.tsx liest sie
// ueber headers() und setzt sie auf beide Inline-Skripte, Next versieht seine eigenen Skripte
// automatisch damit. Das ist noch nicht umgesetzt (braucht einen Browser-Test aller Seiten,
// inkl. statisch gerenderter), bis dahin bleibt 'unsafe-inline' der bewusste Kompromiss: kein
// CDN und keine Fremd-Domains in script-src.
const isDevelopment = process.env.NODE_ENV !== "production";
const scriptSrc = ["'self'", "'unsafe-inline'", isDevelopment && "'unsafe-eval'"]
  .filter(Boolean)
  .join(" ");

const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      `script-src ${scriptSrc}`,
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data: blob:",
      "font-src 'self'",
      "connect-src 'self'",
      "object-src 'none'",
      "frame-src 'none'",
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ].join("; "),
  },
];

const apiProxyTarget = process.env.FRONTEND_API_PROXY_TARGET?.replace(/\/$/, "");

// Kein [locale]-Routing (next-intl ohne i18n-Routing): die Sprache ist eine Benutzer-/
// Cookie-Praeferenz, keine URL-Segmentierung - siehe i18n/request.ts fuer die Herleitung.
const withNextIntl = createNextIntlPlugin("./i18n/request.ts");

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  typedRoutes: true,
  // next dev's cross-origin protection auto-allows "localhost" and the --hostname
  // value (0.0.0.0 here) but not "127.0.0.1" - dev/test tooling (this repo's e2e
  // stack included, see scripts/e2e.sh / playwright.config.ts) hits the dev server
  // via 127.0.0.1, which without this got its HMR websocket silently rejected
  // (403/handshake failure), breaking client-side hydration for the whole page:
  // markup rendered, but nothing was interactive - inputs still worked natively,
  // but anything needing JS (onClick, contenteditable) looked dead. Has no effect
  // outside dev (only read when `next dev` is running).
  allowedDevOrigins: ["127.0.0.1"],
  experimental: {
    // 10 GiB Fotos + 1 MiB Multipart-Overhead, wie der Release-Router.
    proxyClientMaxBodySize: 10738466816,
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
