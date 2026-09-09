import { AppShell } from "@/components/ui/app-shell";
import { WordImportQueueView } from "@/components/tools/word-import-queue-view";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { WordImportDocumentSummary } from "@/lib/api/word-import";
import { TemplateSummary } from "@/types/api";

export default async function WordImportQueuePage() {
  const session = await requireSession();
  const [templates, documents, lastTemplate] = await Promise.all([
    backendFetchWithSession<TemplateSummary[]>("/api/templates"),
    backendFetchWithSession<WordImportDocumentSummary[]>("/api/tools/word-import/documents"),
    backendFetchWithSession<{ template_id: string | null }>("/api/tools/word-import/last-template"),
  ]);
  const activeTemplates = (templates ?? []).filter((template) => template.status === "active");

  return (
    <AppShell initialSession={session}>
      <div className="grid">
        <div className="page-header">
          <div>
            <h1 className="page-title">Import</h1>
            <p className="muted">
              Alte .docx-Protokolle sammeln, prüfen und importieren — jeder bestätigte Import analysiert die restlichen,
              noch offenen Dokumente in der Warteschlange automatisch neu, um deren Vorschläge zu verbessern. Bereits
              vorgenommene manuelle Korrekturen an diesen Dokumenten bleiben dabei erhalten.
            </p>
          </div>
        </div>
        <WordImportQueueView
          templates={activeTemplates}
          initialDocuments={documents ?? []}
          initialTemplateId={lastTemplate?.template_id ?? null}
        />
      </div>
    </AppShell>
  );
}
