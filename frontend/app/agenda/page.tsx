import { AgendaListView } from "@/components/agenda/agenda-list-view";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { AgendaItem, AgendaTemplateOption } from "@/types/api";

export default async function AgendaPage() {
  const session = await requireSession();
  const canEdit = ["admin", "writer"].includes(session.current_role ?? "");

  const [items, templates, preference] = await Promise.all([
    backendFetchWithSession<AgendaItem[]>("/api/agenda-items"),
    backendFetchWithSession<AgendaTemplateOption[]>("/api/agenda-items/templates"),
    canEdit
      ? backendFetchWithSession<{ template_id: string | null }>("/api/agenda-items/template-preference")
      : Promise.resolve(null),
  ]);

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <AgendaListView
          items={items ?? []}
          templates={templates ?? []}
          preferredTemplateId={preference?.template_id ?? null}
          canEdit={canEdit}
        />
      </section>
    </AppShell>
  );
}
