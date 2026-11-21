import { AdminDomainOverview } from "@/components/admin/admin-domain-overview";
import { backendFetchWithSession } from "@/lib/api/server";
import { AdminDomainPage } from "@/types/api";

export default async function AdminDomainsPage() {
  const page = await backendFetchWithSession<AdminDomainPage>("/api/admin/domains?limit=50&offset=0");

  return (
    <>
      <section className="panel">
        <AdminDomainOverview initialPage={page ?? { items: [], total: 0 }} />
      </section>
    </>
  );
}
