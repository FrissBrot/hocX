import createNextIntlPlugin from "next-intl/plugin";

// CSP script-src erlaubt 'unsafe-inline': app/layout.tsx rendert zwei Inline-<script>-Tags
// (Runtime-Config __HOCX_CONFIG__ + Theme-Vorab-Anwendung vor dem ersten Paint, um FOUC zu
// vermeiden) ueber dangerouslySetInnerHTML, die auf JEDER Seite laufen muessen - auch auf
// /login und /admin/login, die proxy.ts (ehemals middleware.ts) bewusst vom Matcher ausschliesst (siehe dortiger
// Kommentar zum Login-Loop-Fix). Ein Nonce-Ansatz wuerde daher entweder den Matcher erweitern
// und die Auth-Redirect-Logik dort um Pfad-Ausnahmen ergaenzen (Risiko einer Regression in
// genau dem Login-Loop-Fix), oder die CSP komplett aus next.config.mjs in die Middleware
// verlagern (Nonces sind pro Request und koennen nicht statisch in next.config.mjs stehen).
// Beides ist fuer eine reine Security-Header-Ergaenzung unverhaeltnismaessig invasiv - bewusster
// Kompromiss: 'unsafe-inline' nur fuer script-src, kein CDN/keine Fremd-Domains in script-src.
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
