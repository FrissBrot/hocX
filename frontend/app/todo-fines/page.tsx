import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { TodoFinesView } from "@/components/finances/todo-fines-view";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { financeTabs } from "@/components/ui/section-tabs";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { can, featureAccess } from "@/lib/permissions";
import type { FinanceAccount, FineTariffGroup, TodoFineListItem, TodoFineRule } from "@/types/api";

// Pendenzen-Bussen: eigenes Feature `todo_fines` (permissions/features.json). Ohne Buchung
// zurück auf die Startseite; abgeschaltet (Nur-Lesen) bleibt die Seite lesbar.
export default async function TodoFinesPage() {
  const session = await requireSession();
  const t = await getTranslations("nav");
  const access = featureAccess(session, "todo_fines");
  if (access === "none") redirect("/");
  const canReadSettings = can(session, "finances.read");
  const canManage = can(session, "finances.manage");
  const [fines, rules, tariffs, accounts] = await Promise.all([
    backendFetchWithSession<TodoFineListItem[]>("/api/todo-fines"),
    canReadSettings ? backendFetchWithSession<TodoFineRule[]>("/api/todo-fines/rules") : Promise.resolve([]),
    canReadSettings ? backendFetchWithSession<FineTariffGroup[]>("/api/todo-fines/tariffs") : Promise.resolve([]),
    canReadSettings ? backendFetchWithSession<FinanceAccount[]>("/api/finance/accounts") : Promise.resolve([]),
  ]);
  const view = (
    <TodoFinesView
      initialFines={fines ?? []}
      initialRules={rules ?? []}
      initialTariffs={tariffs ?? []}
      accounts={accounts ?? []}
      canManage={canManage}
      canReadSettings={canReadSettings}
      ownOnly={!can(session, "reports.personal")}
      readOnly={access === "read_only"}
    />
  );

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<section className="panel">{view}</section>}
        desktop={
          <>
            <RouteTabs tabs={financeTabs(t, { todoFines: true })} activeHref="/todo-fines" />
            <section className="panel">{view}</section>
          </>
        }
      />
    </AppShell>
  );
}
