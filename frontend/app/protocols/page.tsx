import { MobileProtocols } from "@/components/mobile/areas/mobile-protocols";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { AppShell } from "@/components/ui/app-shell";
import { ProtocolBuilder } from "@/components/protocol/protocol-builder";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { ProtocolSummary, TemplateSummary } from "@/types/api";

export default async function ProtocolsPage() {
  const session = await requireSession();
  const canWrite = ["admin", "writer"].includes(session.current_role ?? "");

  const [items, templates, preference] = await Promise.all([
    backendFetchWithSession<ProtocolSummary[]>("/api/protocols"),
    canWrite ? backendFetchWithSession<TemplateSummary[]>("/api/templates") : Promise.resolve([]),
    canWrite ? backendFetchWithSession<{ template_id: string | null }>("/api/protocols/template-preference") : Promise.resolve(null),
  ]);

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileProtocols initialProtocols={items ?? []} templates={templates ?? []} preferredTemplateId={preference?.template_id} readOnly={!canWrite} />}
        desktop={
          <section className="panel">
            <ProtocolBuilder
              initialProtocols={items ?? []}
              templates={templates ?? []} preferredTemplateId={preference?.template_id}
              readOnly={!canWrite}
            />
          </section>
        }
      />
    </AppShell>
  );
}
