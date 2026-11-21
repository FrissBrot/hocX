import { AdminJobStatus } from "@/components/admin/admin-job-status";
import { backendFetchWithSession } from "@/lib/api/server";
import { JobStatusOverview } from "@/types/api";

export default async function AdminJobsPage() {
  const overview = await backendFetchWithSession<JobStatusOverview>("/api/admin/jobs");

  return (
    <>
      <section className="panel">
        <AdminJobStatus initialOverview={overview ?? { items: [], generated_at: new Date().toISOString() }} />
      </section>
    </>
  );
}
