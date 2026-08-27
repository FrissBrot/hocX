import { redirect } from "next/navigation";
import { headers } from "next/headers";

// Ohne dies wuerde Next.js diese Route ohne eigene dynamische Datenabhaengigkeit statisch
// zur Build-Zeit vorrendern - in der CI ist DEFAULT_TENANT_SLUG nicht gesetzt, also wuerde
// jede Umgebung dauerhaft die Fallback-Karte unten sehen, egal was zur Laufzeit in .env steht.
export const dynamic = "force-dynamic";

// Server-seitig gelesen (kein NEXT_PUBLIC_-Praefix noetig), konfiguriert ueber
// DEFAULT_TENANT_SLUG in .env.
const DEFAULT_SLUG = process.env.DEFAULT_TENANT_SLUG;

export default async function RootPage() {
  if (DEFAULT_SLUG) {
    redirect(`/${DEFAULT_SLUG}`);
  }

  // Derived from the incoming request's Host header instead of a hardcoded developer
  // domain, so the example always matches whatever domain this instance is actually
  // reachable under (main TRAEFIK_ABGABEBOX_DOMAIN or a tenant custom domain). Falls back
  // to a clearly generic placeholder if the header is ever missing (e.g. some test setups).
  const host = (await headers()).get("host") ?? "ihre-domain.example.com";

  return (
    <div className="card">
      <h1>Abgabebox</h1>
      <p className="muted">
        Bitte die vollständige URL verwenden:{" "}
        <code>{host}/[tenant-slug]</code>
      </p>
    </div>
  );
}
