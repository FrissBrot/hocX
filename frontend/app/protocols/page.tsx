import { AppShell } from "@/components/ui/app-shell";
import { ProtocolBuilder } from "@/components/protocol/protocol-builder";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { ProtocolSummary, TemplateSummary } from "@/types/api";

export default async function ProtocolsPage() {
  const session = await requireSession();
  const canWrite = session.user?.is_superadmin || ["admin", "writer"].includes(session.current_role ?? "");

  const [items, templates] = await Promise.all([
    backendFetchWithSession<ProtocolSummary[]>("/api/protocols"),
    canWrite ? backendFetchWithSession<TemplateSummary[]>("/api/templates") : Promise.resolve([]),
  ]);

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <ProtocolBuilder
          initialProtocols={items ?? []}
          templates={templates ?? []}
          readOnly={!canWrite}
        />
      </section>
    </AppShell>
  );
}
