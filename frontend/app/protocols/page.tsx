import { AppShell } from "@/components/ui/app-shell";
import { backendFetch } from "@/lib/api/client";

type ProtocolSummary = {
  id: number;
  protocol_number: string;
  title: string | null;
  status: string;
};

export default async function ProtocolsPage() {
  const items = await backendFetch<ProtocolSummary[]>("/api/protocols");

  return (
    <AppShell>
      <section className="panel">
        <div className="eyebrow">Protocols</div>
        <h1>Protocol list</h1>
        <div className="grid">
          {(items ?? []).map((item) => (
            <article className="card" key={item.id}>
              <div className="eyebrow">{item.protocol_number}</div>
              <h3>{item.title ?? "Untitled protocol"}</h3>
              <p className="muted">{item.status}</p>
            </article>
          ))}
          {!items?.length ? (
            <article className="card">
              <h3>No protocols yet</h3>
              <p className="muted">Create a protocol from a template once the database is migrated and seeded.</p>
            </article>
          ) : null}
        </div>
      </section>
    </AppShell>
  );
}

