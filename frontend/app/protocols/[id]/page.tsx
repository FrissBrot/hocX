import { ProtocolOverview } from "@/components/protocol/protocol-builder";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetch } from "@/lib/api/client";
import { ProtocolSummary } from "@/types/api";

export default async function ProtocolDetailPage({ params }: { params: { id: string } }) {
  const protocol = await backendFetch<ProtocolSummary>(`/api/protocols/${params.id}`);

  if (!protocol) {
    return (
      <AppShell>
        <section className="panel">
          <div className="eyebrow">Protocol Detail</div>
          <h1>Protocol not found</h1>
          <p className="muted">The requested protocol could not be loaded from the backend.</p>
        </section>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <section className="panel">
        <div className="eyebrow">Protocol Detail</div>
        <h1>{protocol.title ?? protocol.protocol_number}</h1>
        <p className="muted">This is the first real protocol detail view backed by the API.</p>
        <ProtocolOverview protocol={protocol} />
      </section>
    </AppShell>
  );
}
