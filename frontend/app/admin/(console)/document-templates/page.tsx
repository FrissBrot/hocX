import { AdminSystemDocumentTemplates, type AdminSystemDocumentTemplate } from "@/components/admin/admin-system-document-templates";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";

export default async function AdminDocumentTemplatesPage() {
  const session = await requireAdminSession();
  const templates = await backendFetchWithSession<AdminSystemDocumentTemplate[]>("/api/admin/document-templates");

  return (
    <>
      <section className="panel">
        <AdminSystemDocumentTemplates initialTemplates={templates ?? []} canWrite={session.admin?.role === "owner"} />
      </section>
    </>
  );
}
