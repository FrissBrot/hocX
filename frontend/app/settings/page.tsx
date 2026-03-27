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
        <div className="eyebrow">Settings</div>
        <h1>Document template library</h1>
        <p className="muted">
          Manage reusable LaTeX building parts per tenant and compose full PDF layouts that protocols can choose later.
        </p>
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
