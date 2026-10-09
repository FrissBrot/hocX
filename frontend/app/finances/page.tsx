import { MobileFinances } from "@/components/mobile/areas/mobile-finances";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { financeTabs } from "@/components/ui/section-tabs";
import { FinancesView } from "@/components/finances/finances-view";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { FinanceAccount } from "@/types/api";

export default async function FinancesPage() {
  const session = await requireSession();
  const t = await getTranslations("nav");
  const hasFinanceRole = ["reader", "admin", "writer", "kassier"].includes(session.current_role ?? "");
  const hasFinanceFeature = session.current_tenant?.enabled_features?.includes("finance") ?? false;
  if (!hasFinanceRole || !hasFinanceFeature) redirect("/");

  const accounts = await backendFetchWithSession<FinanceAccount[]>("/api/finance/accounts") ?? [];

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileFinances initialAccounts={accounts} canWrite={["admin", "kassier"].includes(session.current_role ?? "")} />}
        desktop={
          <>
          <RouteTabs tabs={financeTabs(t)} activeHref="/finances" />
          <FinancesView
            initialAccounts={accounts}
            canWrite={["admin", "kassier"].includes(session.current_role ?? "")}
          />
          </>
        }
      />
    </AppShell>
  );
}
