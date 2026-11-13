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
import { can, featureAccess } from "@/lib/permissions";

export default async function FinancesPage() {
  const session = await requireSession();
  const t = await getTranslations("nav");
  const hasFinanceRole = can(session, "finances.read");
  const hasFinanceFeature = featureAccess(session, "finance") !== "none";
  if (!hasFinanceRole || !hasFinanceFeature) redirect("/");

  const accounts = await backendFetchWithSession<FinanceAccount[]>("/api/finance/accounts") ?? [];
  // Eine Währung je Verein, gesetzt in den Mandanten-Einstellungen
  const currency = session.current_tenant?.finance_currency ?? accounts[0]?.currency_label ?? "";

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        // can() berücksichtigt den Nur-Lesen-Zustand nach einem Downgrade schon (finances.manage ist
        // keine Lese-Berechtigung des Features «finance»): canWrite ist dann false.
        mobile={<MobileFinances initialAccounts={accounts} currency={currency} canWrite={can(session, "finances.manage")} readOnly={featureAccess(session, "finance") === "read_only"} />}
        desktop={
          <>
          <RouteTabs tabs={financeTabs(t)} activeHref="/finances" />
          <FinancesView
            initialAccounts={accounts}
            currency={currency}
            canWrite={can(session, "finances.manage")}
            readOnly={featureAccess(session, "finance") === "read_only"}
          />
          </>
        }
      />
    </AppShell>
  );
}
