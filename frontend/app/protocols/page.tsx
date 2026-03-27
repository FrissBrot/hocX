import { AppShell } from "@/components/ui/app-shell";
import { ProtocolBuilder } from "@/components/protocol/protocol-builder";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { DocumentTemplate, ProtocolSummary, TemplateSummary } from "@/types/api";

export default async function ProtocolsPage() {
  const session = await requireSession();
  const [items, templates, documentTemplates] = await Promise.all([
    backendFetchWithSession<ProtocolSummary[]>("/api/protocols"),
    backendFetchWithSession<TemplateSummary[]>("/api/templates"),
    backendFetchWithSession<DocumentTemplate[]>("/api/document-templates")
  ]);

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <div className="eyebrow">Protocols</div>
        <h1>Protocol list</h1>
        <p className="muted">Create new protocol snapshots from templates and inspect the resulting protocol records.</p>
        <ProtocolBuilder initialProtocols={items ?? []} templates={templates ?? []} documentTemplates={documentTemplates ?? []} />
      </section>
    </AppShell>
  );
}
