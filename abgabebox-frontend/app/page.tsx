import { redirect } from "next/navigation";

// Ohne dies wuerde Next.js diese Route ohne eigene dynamische Datenabhaengigkeit statisch
// zur Build-Zeit vorrendern - in der CI ist DEFAULT_TENANT_SLUG nicht gesetzt, also wuerde
// jede Umgebung dauerhaft die Fallback-Karte unten sehen, egal was zur Laufzeit in .env steht.
export const dynamic = "force-dynamic";

// Server-seitig gelesen (kein NEXT_PUBLIC_-Praefix noetig), konfiguriert ueber
// DEFAULT_TENANT_SLUG in .env.
const DEFAULT_SLUG = process.env.DEFAULT_TENANT_SLUG;

export default function RootPage() {
  if (DEFAULT_SLUG) {
    redirect(`/${DEFAULT_SLUG}`);
  }

  return (
    <div className="card">
      <h1>Abgabebox</h1>
      <p className="muted">
        Bitte die vollständige URL verwenden:{" "}
        <code>upload.tweber.ch/[tenant-slug]</code>
      </p>
    </div>
  );
}
