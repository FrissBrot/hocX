import { redirect } from "next/navigation";

import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { FINANCE_TABS } from "@/components/ui/section-tabs";
import { FinancesView } from "@/components/finances/finances-view";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { FinanceAccount } from "@/types/api";

export default async function FinancesPage() {
  const session = await requireSession();
  const hasFinanceRole = ["reader", "admin", "writer", "kassier"].includes(session.current_role ?? "");
  const hasFinanceFeature = session.current_tenant?.enabled_features?.includes("finance") ?? false;
  if (!hasFinanceRole || !hasFinanceFeature) redirect("/");

  const accounts = await backendFetchWithSession<FinanceAccount[]>("/api/finance/accounts") ?? [];

  return (
    <AppShell initialSession={session}>
      <RouteTabs tabs={FINANCE_TABS} activeHref="/finances" />
      <FinancesView
        initialAccounts={accounts}
        canWrite={["admin", "kassier"].includes(session.current_role ?? "")}
      />
    </AppShell>
  );
}
