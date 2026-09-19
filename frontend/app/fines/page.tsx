import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { FINANCE_TABS } from "@/components/ui/section-tabs";
import { FinesView } from "@/components/finances/fines-view";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { AttendanceFineListItem, FinanceAccount } from "@/types/api";

export default async function FinesPage() {
  const session = await requireSession();
  const hasFinance = ["reader", "admin", "writer", "kassier"].includes(session.current_role ?? "");
  const fines = await backendFetchWithSession<AttendanceFineListItem[]>("/api/fines") ?? [];
  const accounts = hasFinance ? (await backendFetchWithSession<FinanceAccount[]>("/api/finance/accounts") ?? []) : [];
  const canWrite = ["admin", "kassier"].includes(session.current_role ?? "");

  return (
    <AppShell initialSession={session}>
      <RouteTabs tabs={FINANCE_TABS} activeHref="/fines" />
      <section className="panel">
        <FinesView initialFines={fines} accounts={accounts} canWrite={canWrite} ownOnly={session.current_role === "reader"} />
      </section>
    </AppShell>
  );
}
