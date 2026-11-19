import { MobileFinances } from "@/components/mobile/areas/mobile-finances";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";

import { AppShell } from "@/components/ui/app-shell";
import { FinancesView } from "@/components/finances/finances-view";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { FinanceAccount, OpenFinesSummary, TodoFineListItem } from "@/types/api";
import { can, featureAccess } from "@/lib/permissions";

export default async function FinancesPage() {
  const session = await requireSession();
  const hasFinanceRole = can(session, "finances.read");
  const hasFinanceFeature = featureAccess(session, "finance") !== "none";
  if (!hasFinanceRole || !hasFinanceFeature) redirect("/");

  // Zähler am Reiter «Bussen»: offene Präsenz-Bussen (serverseitig gezählt) plus offene,
  // laufende und strittige Pendenzen-Bussen - dieselbe Zählweise wie der Filter «Offen».
  const todoFinesEnabled = featureAccess(session, "todo_fines") !== "none";
  const [accounts, openSummary, todoFines] = await Promise.all([
    backendFetchWithSession<FinanceAccount[]>("/api/finance/accounts").then((value) => value ?? []),
    backendFetchWithSession<OpenFinesSummary>("/api/fines/open-summary"),
    todoFinesEnabled ? backendFetchWithSession<TodoFineListItem[]>("/api/todo-fines") : Promise.resolve(null),
  ]);
  const openTodoFines = (todoFines ?? []).filter((fine) => fine.status !== "collected" && fine.status !== "deleted").length;
  const openFineCount = openSummary ? openSummary.count + openTodoFines : null;
  // Eine Währung je Verein, gesetzt in den Mandanten-Einstellungen
  const currency = session.current_tenant?.finance_currency ?? accounts[0]?.currency_label ?? "";

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        // can() berücksichtigt den Nur-Lesen-Zustand nach einem Downgrade schon (finances.manage ist
        // keine Lese-Berechtigung des Features «finance»): canWrite ist dann false.
        mobile={<MobileFinances initialAccounts={accounts} currency={currency} canWrite={can(session, "finances.manage")} readOnly={featureAccess(session, "finance") === "read_only"} />}
        desktop={
          <FinancesView
            initialAccounts={accounts}
            currency={currency}
            canWrite={can(session, "finances.manage")}
            readOnly={featureAccess(session, "finance") === "read_only"}
            openFineCount={openFineCount}
          />
        }
      />
    </AppShell>
  );
}
