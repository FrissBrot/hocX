import { MobileDesktopOnly } from "@/components/mobile/areas/mobile-misc";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { TaskPackageManager } from "@/components/task-packages/task-package-manager";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { templateAreaTabs } from "@/components/ui/section-tabs";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { eligibleResponsibleList } from "@/lib/utils/responsible-lists";
import {
  CycleConfigSummary,
  EventSummary,
  ParticipantSummary,
  StructuredListDefinition,
  StructuredListEntry,
  TaskPackage,
} from "@/types/api";
import { FeatureNotice } from "@/components/ui/feature-notice";
import { can, featureAccess } from "@/lib/permissions";

export default async function TaskPackagesPage() {
  const session = await requireSession();
  if (!can(session, "templates.manage")) {
    redirect("/");
  }
  const t = await getTranslations("nav");
  const access = featureAccess(session, "task_packages");
  if (access === "none") {
    return (
      <AppShell initialSession={session}>
        <RouteTabs tabs={templateAreaTabs(t, true)} activeHref="/task-packages" />
        <FeatureNotice feature="task_packages" access={access} />
      </AppShell>
    );
  }
  const [taskPackages, cycleConfigs, lists, participants, events] = await Promise.all([
    backendFetchWithSession<TaskPackage[]>("/api/task-packages"),
    backendFetchWithSession<CycleConfigSummary[]>("/api/cycle-configs"),
    backendFetchWithSession<StructuredListDefinition[]>("/api/lists"),
    backendFetchWithSession<ParticipantSummary[]>("/api/participants?limit=500"),
    backendFetchWithSession<EventSummary[]>("/api/events?limit=500"),
  ]);
  // Nur Listen mit Text- und Personenspalte (z. B. Ämtlilisten) liefern Verantwortliche.
  const responsibleLists = (lists ?? []).filter((definition) => definition.is_active && eligibleResponsibleList(definition));
  const entriesByList = Object.fromEntries(
    await Promise.all(
      responsibleLists.map(async (definition) => [
        definition.id,
        (await backendFetchWithSession<StructuredListEntry[]>(`/api/lists/${definition.id}/entries`)) ?? [],
      ])
    )
  ) as Record<string, StructuredListEntry[]>;
  const eventTags = Array.from(new Set((events ?? []).map((event) => event.tag).filter((tag): tag is string => !!tag))).sort();

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileDesktopOnly navKey="taskPackages" backHref="/templates" backNavKey="templates" />}
        desktop={
          <>
            <RouteTabs tabs={templateAreaTabs(t, can(session, "templates.manage"))} activeHref="/task-packages" />
            <FeatureNotice feature="task_packages" access={access} />
            <section className="panel">
              <TaskPackageManager
                initialPackages={taskPackages ?? []}
                cycleConfigs={cycleConfigs ?? []}
                responsibleLists={responsibleLists}
                entriesByList={entriesByList}
                participants={participants ?? []}
                eventTags={eventTags}
              />
            </section>
          </>
        }
      />
    </AppShell>
  );
}
