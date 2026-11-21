import { getTranslations } from "next-intl/server";

import { AdminCashflow } from "@/components/admin/admin-cashflow";
import { StatusBanner } from "@/components/ui/status-banner";
import { backendFetchWithSession } from "@/lib/api/server";
import { CashflowOverview } from "@/types/api";

export default async function AdminCashflowPage() {
  const t = await getTranslations("adminCashflow");
  const overview = await backendFetchWithSession<CashflowOverview>("/api/admin/cashflow/overview");
  return (
    <>
      <section className="admin-page">
        {overview ? <AdminCashflow initialOverview={overview} /> : <StatusBanner tone="error" message={t("toast.loadFailed")} />}
      </section>
    </>
  );
}
