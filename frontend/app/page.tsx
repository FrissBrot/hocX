import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";

type HealthResponse = {
  status: string;
  service: string;
};

export default async function HomePage() {
  const session = await requireSession();
  const health = await backendFetchWithSession<HealthResponse>("/api/health");

  return (
    <AppShell initialSession={session}>
      <section className="panel hero">
        <div className="eyebrow">hocX studio</div>
        <h1 className="title">A calmer, sharper workspace for protocols, layouts and exports.</h1>
        <p className="muted">
          Built for focused editing instead of endless scrolling: reusable elements, snapshot-based protocols and
          document layouts now live inside one minimal fullscreen shell.
        </p>
        <div className="grid stats">
          <article className="card">
            <div className="eyebrow">Focused UI</div>
            <h3>Modal-first workflow</h3>
            <p className="muted">Cleaner navigation, overlay editors and a faster way to move through complex content.</p>
          </article>
          <article className="card">
            <div className="eyebrow">Export system</div>
            <h3>Reusable PDF layouts</h3>
            <p className="muted">Tenant-wide LaTeX parts and document templates can now be assigned per protocol.</p>
          </article>
          <article className="card">
            <div className="eyebrow">Health</div>
            <h3>{health?.status ?? "unreachable"}</h3>
            <p className="muted">{health?.service ?? "backend not reachable yet"}</p>
          </article>
        </div>
      </section>
    </AppShell>
  );
}
