import { AdminPlanPricing } from "@/components/admin/admin-plan-pricing";
import { backendFetchWithSession } from "@/lib/api/server";
import { AdminFeature, AdminPlan, AdminStoragePackage } from "@/types/api";

export default async function AdminPlansPage() {
  const [plans, features, storagePackages] = await Promise.all([
    backendFetchWithSession<AdminPlan[]>("/api/admin/plans"),
    backendFetchWithSession<AdminFeature[]>("/api/admin/features"),
    backendFetchWithSession<AdminStoragePackage[]>("/api/admin/storage-packages"),
  ]);

  return (
    <>
      <AdminPlanPricing initialPlans={plans ?? []} initialFeatures={features ?? []} initialStoragePackages={storagePackages ?? []} />
    </>
  );
}
