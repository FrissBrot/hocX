import { AdminPlanPricing } from "@/components/admin/admin-plan-pricing";
import { AdminShell } from "@/components/ui/admin-shell";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { AdminFeature, AdminPlan } from "@/types/api";

export default async function AdminPlansPage() {
  const session = await requireAdminSession();
  const [plans, features] = await Promise.all([
    backendFetchWithSession<AdminPlan[]>("/api/admin/plans"),
    backendFetchWithSession<AdminFeature[]>("/api/admin/features"),
  ]);

  return (
    <AdminShell session={session}>
      <section className="panel">
        <AdminPlanPricing initialPlans={plans ?? []} initialFeatures={features ?? []} />
      </section>
    </AdminShell>
  );
}
