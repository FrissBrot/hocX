import { MobileFines } from "@/components/mobile/areas/mobile-finances";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { financeTabs } from "@/components/ui/section-tabs";
import { FinesView } from "@/components/finances/fines-view";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { AttendanceFineListItem, FinanceAccount } from "@/types/api";
import { can } from "@/lib/permissions";

export default async function FinesPage() {
  const session = await requireSession();
  const t = await getTranslations("nav");
  // Eigene Bussen sieht jedes Konto (ohne reports.personal nur die eigenen, siehe GET /api/fines);
  // entscheidend hier ist allein, ob der Mandant Finanzen gebucht hat (Direktzugriffsschutz zum
  // Nav-Link in app-shell-nav.ts).
  const hasFinanceFeature = session.current_tenant?.enabled_features?.includes("finance") ?? false;
  if (!hasFinanceFeature) redirect("/");
  const hasFinance = can(session, "finances.read");
  const fines = await backendFetchWithSession<AttendanceFineListItem[]>("/api/fines") ?? [];
  const accounts = hasFinance ? (await backendFetchWithSession<FinanceAccount[]>("/api/finance/accounts") ?? []) : [];
  const canWrite = can(session, "finances.manage");

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileFines initialFines={fines} accounts={accounts} canWrite={canWrite} ownOnly={!can(session, "reports.personal")} />}
        desktop={
          <>
          <RouteTabs tabs={financeTabs(t)} activeHref="/fines" />
          <section className="panel">
            <FinesView initialFines={fines} accounts={accounts} canWrite={canWrite} ownOnly={!can(session, "reports.personal")} />
          </section>
          </>
        }
      />
    </AppShell>
  );
}
