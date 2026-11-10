import { getTranslations } from "next-intl/server";

import { AdminCashflow } from "@/components/admin/admin-cashflow";
import { AdminShell } from "@/components/ui/admin-shell";
import { StatusBanner } from "@/components/ui/status-banner";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { CashflowOverview } from "@/types/api";

export default async function AdminCashflowPage() {
  const session = await requireAdminSession();
  const t = await getTranslations("adminCashflow");
  const overview = await backendFetchWithSession<CashflowOverview>("/api/admin/cashflow/overview");
  return (
    <AdminShell session={session}>
      <section className="admin-page">
        {overview ? <AdminCashflow initialOverview={overview} /> : <StatusBanner tone="error" message={t("toast.loadFailed")} />}
      </section>
    </AdminShell>
  );
}
