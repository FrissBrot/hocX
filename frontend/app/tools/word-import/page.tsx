import { AppShell } from "@/components/ui/app-shell";
import { WordImportWizard } from "@/components/tools/word-import-wizard";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { ParticipantSummary, TemplateSummary } from "@/types/api";

export default async function WordImportPage() {
  const session = await requireSession();
  const [templates, participants] = await Promise.all([
    backendFetchWithSession<TemplateSummary[]>("/api/templates"),
    backendFetchWithSession<ParticipantSummary[]>("/api/participants"),
  ]);
  const activeTemplates = (templates ?? []).filter((template) => template.status === "active");
  const activeParticipants = (participants ?? []).filter((participant) => participant.is_active);

  return (
    <AppShell initialSession={session}>
      <div className="grid">
        <div className="page-header">
          <div>
            <h1 className="page-title">Word-Protokoll-Import</h1>
            <p className="muted">Ein altes .docx-Protokoll einlesen, Vorschläge prüfen und als neues Protokoll übernehmen.</p>
          </div>
        </div>
        <WordImportWizard templates={activeTemplates} participants={activeParticipants} />
      </div>
    </AppShell>
  );
}
