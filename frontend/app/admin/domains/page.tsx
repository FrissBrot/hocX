import { AdminDomainOverview } from "@/components/admin/admin-domain-overview";
import { AdminShell } from "@/components/ui/admin-shell";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { AdminDomainSummary } from "@/types/api";

export default async function AdminDomainsPage() {
  const session = await requireAdminSession();
  const domains = await backendFetchWithSession<AdminDomainSummary[]>("/api/admin/domains");

  return (
    <AdminShell session={session}>
      <section className="panel">
        <AdminDomainOverview initialDomains={domains ?? []} />
      </section>
    </AdminShell>
  );
}
