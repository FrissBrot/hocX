import { getTranslations } from "next-intl/server";

import { AppShell } from "@/components/ui/app-shell";
import { WordImportQueueView } from "@/components/tools/word-import-queue-view";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { WordImportDocumentSummary } from "@/lib/api/word-import";
import { TemplateSummary } from "@/types/api";

export default async function WordImportQueuePage() {
  const t = await getTranslations("tools.wordImport.queueView");
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
            <h1 className="page-title">{t("pageTitle")}</h1>
            <p className="muted">
              {t("pageIntro")}
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
