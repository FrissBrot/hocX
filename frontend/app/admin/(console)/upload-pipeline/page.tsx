import { AdminUploadPipelineStatus } from "@/components/admin/admin-upload-pipeline-status";
import { backendFetchWithSession } from "@/lib/api/server";
import { UploadPipelineOverview } from "@/types/api";

export default async function AdminUploadPipelinePage() {
  // Mandantenfilter per Remote-Picker (1.5.1) - keine ganze Mandantenliste mehr.
  const overview = await backendFetchWithSession<UploadPipelineOverview>("/api/admin/upload-pipeline-status");
  return (
    <section className="panel">
      <AdminUploadPipelineStatus initialOverview={overview ?? { summary: [], files: { items: [], total: 0 }, abgabebox_quarantine: [] }} />
    </section>
  );
}
