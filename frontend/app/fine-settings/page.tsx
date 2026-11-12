import { redirect } from "next/navigation";

import { FineSettingsView } from "@/components/finances/fine-settings-view";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { can, featureAccess } from "@/lib/permissions";
import type { FinanceAccount, FineTariff, FineTariffGroup, TodoFineRule } from "@/types/api";

// Bussen-Konfiguration (Navigation: Konfiguration): Anwesenheitsbussen, Tarife, Pendenzen-Regeln.
// Braucht das Feature finance und finances.read; ändern nur mit finances.manage.
export default async function FineSettingsPage() {
  const session = await requireSession();
  if (featureAccess(session, "finance") === "none" || !can(session, "finances.read")) redirect("/");
  const canManage = can(session, "finances.manage");
  const todoFinesAccess = featureAccess(session, "todo_fines");
  const [tariff, tariffs, rules, accounts] = await Promise.all([
    backendFetchWithSession<FineTariff>("/api/fines/tariff"),
    backendFetchWithSession<FineTariffGroup[]>("/api/todo-fines/tariffs"),
    todoFinesAccess !== "none" ? backendFetchWithSession<TodoFineRule[]>("/api/todo-fines/rules") : Promise.resolve([]),
    backendFetchWithSession<FinanceAccount[]>("/api/finance/accounts"),
  ]);
  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <FineSettingsView
          initialTariff={tariff ?? null}
          initialTariffs={tariffs ?? []}
          initialRules={rules ?? []}
          accounts={accounts ?? []}
          canManage={canManage}
          todoFinesAccess={todoFinesAccess}
        />
      </section>
    </AppShell>
  );
}
