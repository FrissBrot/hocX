import { MobileDesktopOnly } from "@/components/mobile/areas/mobile-misc";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { getTranslations } from "next-intl/server";

import { AppShell } from "@/components/ui/app-shell";
import { WordImportWizard } from "@/components/tools/word-import-wizard";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { ParticipantSummary, TemplateSummary } from "@/types/api";

export default async function WordImportPage() {
  const t = await getTranslations("tools.wordImport");
  const session = await requireSession();
  const [templates, participants] = await Promise.all([
    backendFetchWithSession<TemplateSummary[]>("/api/templates"),
    backendFetchWithSession<ParticipantSummary[]>("/api/participants"),
  ]);
  const activeTemplates = (templates ?? []).filter((template) => template.status === "active");
  const activeParticipants = (participants ?? []).filter((participant) => participant.is_active);

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileDesktopOnly navKey="import" />}
        desktop={
          <>
          <div className="grid">
            <div className="page-header">
              <div>
                <h1 className="page-title">{t("pageTitle")}</h1>
                <p className="muted">{t("pageIntro")}</p>
              </div>
            </div>
            <WordImportWizard templates={activeTemplates} participants={activeParticipants} />
          </div>
          </>
        }
      />
    </AppShell>
  );
}
