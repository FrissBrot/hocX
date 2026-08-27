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

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  typedRoutes: true,
  experimental: {
    // Lokale/Test-Requests laufen ueber den Next-Proxy. Mandantenexporte duerfen laut
    // Backend bis zu 2 GiB gross sein; der Next-Standard von 10 MB schneidet solche
    // multipart-Uploads ab und endet dann mit ECONNRESET / "Internal Server Error".
    // 2050 MB lassen zusaetzlich etwas Platz fuer den multipart/form-data-Overhead.
    proxyClientMaxBodySize: "2050mb",
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
