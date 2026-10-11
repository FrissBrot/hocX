import { AdminJobStatus } from "@/components/admin/admin-job-status";
import { AdminShell } from "@/components/ui/admin-shell";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { JobStatusOverview } from "@/types/api";

export default async function AdminJobsPage() {
  const session = await requireAdminSession();
  const overview = await backendFetchWithSession<JobStatusOverview>("/api/admin/jobs");

  return (
    <AdminShell session={session}>
      <section className="panel">
        <AdminJobStatus initialOverview={overview ?? { items: [], generated_at: new Date().toISOString() }} />
      </section>
    </AdminShell>
  );
}
