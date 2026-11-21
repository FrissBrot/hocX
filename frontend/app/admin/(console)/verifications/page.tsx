import { AdminVerificationRequests, type AdminVerificationRequest } from "@/components/admin/admin-identity-verification";
import { backendFetchWithSession } from "@/lib/api/server";

export default async function AdminVerificationsPage() {
  const requests = await backendFetchWithSession<AdminVerificationRequest[]>("/api/admin/identity-verification-requests?status=pending");

  return (
    <>
      <section className="panel">
        <AdminVerificationRequests initialRequests={requests ?? []} />
      </section>
    </>
  );
}
