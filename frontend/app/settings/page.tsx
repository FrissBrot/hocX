import { AppShell } from "@/components/ui/app-shell";

export default function SettingsPage() {
  return (
    <AppShell>
      <section className="panel">
        <div className="eyebrow">Master Data</div>
        <h1>Settings and reference data</h1>
        <div className="two-col">
          <article className="card">
            <h3>Tenants / users / roles</h3>
            <p className="muted">Prepared in the schema, still intentionally lightweight in V1.</p>
          </article>
          <article className="card">
            <h3>Leaders / groups / events</h3>
            <p className="muted">Master data endpoints can be expanded next without changing the core stack.</p>
          </article>
        </div>
      </section>
    </AppShell>
  );
}

