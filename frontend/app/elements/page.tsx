import { ElementDefinitionManager } from "@/components/template/element-definition-manager";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { ElementDefinition } from "@/types/api";

export default async function ElementsPage() {
  const session = await requireSession();
  const definitions = await backendFetchWithSession<ElementDefinition[]>("/api/element-definitions");

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <div className="eyebrow">Elements</div>
        <h1>Element definitions</h1>
        <p className="muted">
          Reusable elements live here. Each element can contain multiple blocks such as text, todos, images or fixed text.
        </p>
        <div className="info-note">
          Use this page to build complete elements once. Later, templates only choose these finished elements and sort them.
        </div>
        <ElementDefinitionManager initialDefinitions={definitions ?? []} />
      </section>
    </AppShell>
  );
}
