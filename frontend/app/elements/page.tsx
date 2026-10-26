import { MobileDesktopOnly } from "@/components/mobile/areas/mobile-misc";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { ComponentsLibrary } from "@/components/documents/components-library";
import { ElementDefinitionManager } from "@/components/template/element-definition-manager";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { templateAreaTabs } from "@/components/ui/section-tabs";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import type { Capabilities } from "@/lib/documents/api";
import { ElementDefinition, EventSummary, FinanceAccount, ParticipantSummary, StructuredListDefinition } from "@/types/api";

export default async function ElementsPage({ searchParams }: { searchParams: Promise<{ create?: string }> }) {
  const { create } = await searchParams;
  const session = await requireSession();
  const t = await getTranslations("nav");
  const canAdmin = session.current_role === "admin";
  if (!canAdmin && session.current_role !== "writer") {
    redirect("/");
  }
  // Bausteine: nur die Bibliothek (Einzelstücke gehören ihrer Sitzungsvorlage)
  const definitions = await backendFetchWithSession<ElementDefinition[]>("/api/element-definitions?library=true");
  const events = (await backendFetchWithSession<EventSummary[]>("/api/events")) ?? [];
  const lists = (await backendFetchWithSession<StructuredListDefinition[]>("/api/lists")) ?? [];
  const participants = (await backendFetchWithSession<ParticipantSummary[]>("/api/participants?limit=2000")) ?? [];
  const accounts = (await backendFetchWithSession<FinanceAccount[]>("/api/finance/accounts")) ?? [];
  const capabilities = await backendFetchWithSession<Capabilities>("/api/document-studio/capabilities");
  const knownEventTags = Array.from(
    new Set(events.map((event) => (event.tag ?? "").trim()).filter((tag) => tag.length > 0))
  ).sort((left, right) => left.localeCompare(right));

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileDesktopOnly navKey="elements" backHref="/templates" backNavKey="templates" />}
        desktop={
          <>
          <RouteTabs tabs={templateAreaTabs(t, session.current_role === "admin")} activeHref="/elements" />
          <section className="panel">
            <ElementDefinitionManager
              initialDefinitions={definitions ?? []}
              knownEventTags={knownEventTags}
              availableParticipants={participants}
              availableEvents={events}
              availableLists={lists}
              availableAccounts={accounts}
              tenantId={session.current_tenant?.id ?? null}
              autoOpenCreate={create === "1"}
            />
          </section>
          {capabilities ? (
            <section className="panel">
              <ComponentsLibrary capabilities={capabilities} />
            </section>
          ) : null}
          </>
        }
      />
    </AppShell>
  );
}
