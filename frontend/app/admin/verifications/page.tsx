import { AdminVerificationRequests, type AdminVerificationRequest } from "@/components/admin/admin-identity-verification";
import { AdminShell } from "@/components/ui/admin-shell";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";

export default async function AdminVerificationsPage() {
  const session = await requireAdminSession();
  const requests = await backendFetchWithSession<AdminVerificationRequest[]>("/api/admin/identity-verification-requests?status=pending");

  return (
    <AdminShell session={session}>
      <section className="panel">
        <AdminVerificationRequests initialRequests={requests ?? []} />
      </section>
    </AdminShell>
  );
}
