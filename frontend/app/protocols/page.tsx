import { AppShell } from "@/components/ui/app-shell";
import { ProtocolBuilder } from "@/components/protocol/protocol-builder";
import { backendFetch } from "@/lib/api/client";
import { ProtocolSummary, TemplateSummary } from "@/types/api";

export default async function ProtocolsPage() {
  const [items, templates] = await Promise.all([
    backendFetch<ProtocolSummary[]>("/api/protocols"),
    backendFetch<TemplateSummary[]>("/api/templates")
  ]);

  return (
    <AppShell>
      <section className="panel">
        <div className="eyebrow">Protocols</div>
        <h1>Protocol list</h1>
        <p className="muted">Create new protocol snapshots from templates and inspect the resulting protocol records.</p>
        <ProtocolBuilder initialProtocols={items ?? []} templates={templates ?? []} />
      </section>
    </AppShell>
  );
}
