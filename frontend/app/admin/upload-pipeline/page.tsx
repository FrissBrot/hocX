import { AdminUploadPipelineStatus } from "@/components/admin/admin-upload-pipeline-status";
import { AdminShell } from "@/components/ui/admin-shell";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { AdminTenantPage, UploadPipelineOverview } from "@/types/api";

export default async function AdminUploadPipelinePage() {
  const session = await requireAdminSession();
  const [overview, tenants] = await Promise.all([
    backendFetchWithSession<UploadPipelineOverview>("/api/admin/upload-pipeline-status"),
    // No limit param -> full (unpaginated) list, needed here for the tenant filter dropdown.
    backendFetchWithSession<AdminTenantPage>("/api/admin/tenants"),
  ]);

  return (
    <AdminShell session={session}>
      <section className="panel">
        <AdminUploadPipelineStatus
          initialOverview={overview ?? { summary: [], files: { items: [], total: 0 }, abgabebox_quarantine: [] }}
          tenants={tenants?.items ?? []}
        />
      </section>
    </AdminShell>
  );
}
