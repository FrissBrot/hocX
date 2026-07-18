import { AdminAccountManagement } from "@/components/admin/admin-account-management";
import { AdminShell } from "@/components/ui/admin-shell";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { PlatformAdminSummary } from "@/types/api";

export default async function AdminAccountsPage() {
  const session = await requireAdminSession();
  const admins = await backendFetchWithSession<PlatformAdminSummary[]>("/api/admin/admins");

  return (
    <AdminShell session={session}>
      <section className="panel">
        <AdminAccountManagement initialAdmins={admins ?? []} currentAdminId={session.admin?.id ?? 0} />
      </section>
    </AdminShell>
  );
}
