import { AdminDomainOverview } from "@/components/admin/admin-domain-overview";
import { AdminShell } from "@/components/ui/admin-shell";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { AdminDomainPage } from "@/types/api";

export default async function AdminDomainsPage() {
  const session = await requireAdminSession();
  const page = await backendFetchWithSession<AdminDomainPage>("/api/admin/domains?limit=50&offset=0");

  return (
    <AdminShell session={session}>
      <section className="panel">
        <AdminDomainOverview initialPage={page ?? { items: [], total: 0 }} />
      </section>
    </AdminShell>
  );
}
