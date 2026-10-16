import createNextIntlPlugin from "next-intl/plugin";

// Die Content-Security-Policy setzt proxy.ts pro Request mit Nonce (lib/csp.ts, Audit
// MAIN-FE-013) - eine statische CSP hier könnte keine Nonce tragen und würde zusätzlich
// erzwungen. Die übrigen Sicherheitsheader bleiben statisch.
const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
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
