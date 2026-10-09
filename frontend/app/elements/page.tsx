import { MobileDesktopOnly } from "@/components/mobile/areas/mobile-misc";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { ElementDefinitionManager } from "@/components/template/element-definition-manager";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { templateTabs } from "@/components/ui/section-tabs";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { ElementDefinition, EventSummary, FinanceAccount, ParticipantSummary, StructuredListDefinition } from "@/types/api";

export default async function ElementsPage({ searchParams }: { searchParams: Promise<{ create?: string }> }) {
  const { create } = await searchParams;
  const session = await requireSession();
  const t = await getTranslations("nav");
  const canAdmin = session.current_role === "admin";
  if (!canAdmin) {
    redirect("/");
  }
  const definitions = await backendFetchWithSession<ElementDefinition[]>("/api/element-definitions");
  const events = (await backendFetchWithSession<EventSummary[]>("/api/events")) ?? [];
  const lists = (await backendFetchWithSession<StructuredListDefinition[]>("/api/lists")) ?? [];
  const participants = canAdmin ? (await backendFetchWithSession<ParticipantSummary[]>("/api/participants?limit=2000")) ?? [] : [];
  const accounts = (await backendFetchWithSession<FinanceAccount[]>("/api/finance/accounts")) ?? [];
  const knownEventTags = Array.from(
    new Set(events.map((event) => (event.tag ?? "").trim()).filter((tag) => tag.length > 0))
  ).sort((left, right) => left.localeCompare(right));

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileDesktopOnly navKey="elements" backHref="/templates" backNavKey="templates" />}
        desktop={
          <>
          <RouteTabs tabs={templateTabs(t)} activeHref="/elements" />
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
          </>
        }
      />
    </AppShell>
  );
}
