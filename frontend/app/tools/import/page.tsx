import { AppShell } from "@/components/ui/app-shell";
import { WordImportQueueView } from "@/components/tools/word-import-queue-view";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { WordImportDocumentSummary } from "@/lib/api/word-import";
import { ParticipantSummary, TemplateSummary } from "@/types/api";

export default async function WordImportQueuePage() {
  const session = await requireSession();
  const [templates, participants, documents] = await Promise.all([
    backendFetchWithSession<TemplateSummary[]>("/api/templates"),
    backendFetchWithSession<ParticipantSummary[]>("/api/participants"),
    backendFetchWithSession<WordImportDocumentSummary[]>("/api/tools/word-import/documents"),
  ]);
  const activeTemplates = (templates ?? []).filter((template) => template.status === "active");
  const activeParticipants = (participants ?? []).filter((participant) => participant.is_active);

  return (
    <AppShell initialSession={session}>
      <div className="grid">
        <div className="page-header">
          <div>
            <h1 className="page-title">Import</h1>
            <p className="muted">
              Alte .docx-Protokolle sammeln, prüfen und importieren — jeder bestätigte Import verbessert die Vorschläge für
              die restlichen Dokumente in der Warteschlange.
            </p>
          </div>
        </div>
        <WordImportQueueView templates={activeTemplates} participants={activeParticipants} initialDocuments={documents ?? []} />
      </div>
    </AppShell>
  );
}
