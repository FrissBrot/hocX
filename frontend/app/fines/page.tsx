import { MobileFines } from "@/components/mobile/areas/mobile-finances";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";

import { AppShell } from "@/components/ui/app-shell";
import { FinesView } from "@/components/finances/fines-view";
import { FINES_PAGE_SIZE } from "@/components/finances/fines-model";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { AttendanceFineListItem, FinanceAccount, TodoFineListItem } from "@/types/api";
import { can, featureAccess } from "@/lib/permissions";

export default async function FinesPage() {
  const session = await requireSession();
  // Eigene Bussen sieht jedes Konto (ohne reports.personal nur die eigenen, siehe GET /api/fines);
  // entscheidend hier ist allein, ob der Mandant Finanzen gebucht hat (Direktzugriffsschutz zum
  // Nav-Link in app-shell-nav.ts).
  const hasFinanceFeature = featureAccess(session, "finance") !== "none";
  if (!hasFinanceFeature) redirect("/");
  const hasFinance = can(session, "finances.read");
  // Erste Seite gross (FINES_PAGE_SIZE): Gruppierung nach Person und Kennzahlen rechnen mit allem Geladenen.
  const fines = await backendFetchWithSession<AttendanceFineListItem[]>(`/api/fines?limit=${FINES_PAGE_SIZE}`) ?? [];
  const accounts = hasFinance ? (await backendFetchWithSession<FinanceAccount[]>("/api/finance/accounts") ?? []) : [];
  const canWrite = can(session, "fines.manage");
  // Pendenzen-Bussen (Feature todo_fines) stehen in derselben Liste; abgeschaltet nur lesbar.
  const todoFinesAccess = featureAccess(session, "todo_fines");
  const todoFines = todoFinesAccess !== "none" ? (await backendFetchWithSession<TodoFineListItem[]>("/api/todo-fines") ?? []) : null;

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileFines initialFines={fines} initialTodoFines={todoFines} todoFinesWritable={todoFinesAccess === "full"} accounts={accounts} canWrite={canWrite} ownOnly={!can(session, "reports.personal")} />}
        desktop={
          <FinesView
            initialFines={fines}
            initialTodoFines={todoFines}
            todoFinesWritable={todoFinesAccess === "full"}
            accounts={accounts}
            canWrite={canWrite}
            ownOnly={!can(session, "reports.personal")}
            readOnly={featureAccess(session, "finance") === "read_only"}
            showAccountsTab={hasFinance}
            currency={session.current_tenant?.finance_currency ?? accounts[0]?.currency_label ?? ""}
          />
        }
      />
    </AppShell>
  );
}
