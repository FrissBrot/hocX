import { redirect } from "next/navigation";

import { AppShell } from "@/components/ui/app-shell";
import { FinancesView } from "@/components/finances/finances-view";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { FinanceAccount } from "@/types/api";

export default async function FinancesPage() {
  const session = await requireSession();
  const hasFinance = session.user?.is_superadmin || ["admin", "writer", "kassier"].includes(session.current_role ?? "");
  if (!hasFinance) redirect("/");

  const accounts = await backendFetchWithSession<FinanceAccount[]>("/api/finance/accounts") ?? [];

  return (
    <AppShell initialSession={session}>
      <div className="grid">
        <FinancesView initialAccounts={accounts} />
      </div>
    </AppShell>
  );
}
