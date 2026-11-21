import { AdminAccountManagement } from "@/components/admin/admin-account-management";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { PlatformAdminSummary } from "@/types/api";

export default async function AdminAccountsPage() {
  const session = await requireAdminSession();
  const admins = await backendFetchWithSession<PlatformAdminSummary[]>("/api/admin/admins");

  return (
    <>
      <section className="panel">
        <AdminAccountManagement initialAdmins={admins ?? []} currentAdminId={session.admin?.id ?? ""} />
      </section>
    </>
  );
}
