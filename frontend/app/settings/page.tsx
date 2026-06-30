import { DocumentTemplateManager } from "@/components/settings/document-template-manager";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { DocumentTemplate, DocumentTemplatePart } from "@/types/api";

export default async function SettingsPage() {
  const session = await requireSession();
  const [documentTemplates, documentTemplateParts] = await Promise.all([
    backendFetchWithSession<DocumentTemplate[]>("/api/document-templates"),
    backendFetchWithSession<DocumentTemplatePart[]>("/api/document-template-parts")
  ]);

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <div className="section-stack">
          <DocumentTemplateManager
            initialTemplates={documentTemplates ?? []}
            initialParts={documentTemplateParts ?? []}
          />
        </div>
      </section>
    </AppShell>
  );
}
