import { redirect } from "next/navigation";

import { AppShell } from "@/components/ui/app-shell";
import { WordImportWizard } from "@/components/tools/word-import-wizard";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { WordImportDocumentDetail } from "@/lib/api/word-import";
import { ParticipantSummary, TemplateSummary } from "@/types/api";

export default async function WordImportDocumentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const documentId = id;

  const session = await requireSession();
  const [document, templates, participants] = await Promise.all([
    backendFetchWithSession<WordImportDocumentDetail>(`/api/tools/word-import/documents/${documentId}`),
    backendFetchWithSession<TemplateSummary[]>("/api/templates"),
    backendFetchWithSession<ParticipantSummary[]>("/api/participants"),
  ]);

  if (!document) {
    redirect("/tools/import");
  }

  const activeTemplates = (templates ?? []).filter((template) => template.status === "active");
  const activeParticipants = (participants ?? []).filter((participant) => participant.is_active);

  return (
    <AppShell initialSession={session}>
      <div className="grid">
        <div className="page-header">
          <div>
            <h1 className="page-title">{document.display_name}</h1>
            <p className="muted">Vorschläge prüfen und als neues Protokoll übernehmen.</p>
          </div>
        </div>
        <WordImportWizard templates={activeTemplates} participants={activeParticipants} documentId={documentId} />
      </div>
    </AppShell>
  );
}
