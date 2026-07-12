import { redirect } from "next/navigation";

// Configured via NEXT_PUBLIC_DEFAULT_TENANT_SLUG in .env
const DEFAULT_SLUG = process.env.NEXT_PUBLIC_DEFAULT_TENANT_SLUG;

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
