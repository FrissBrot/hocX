import { MobileDesktopOnly } from "@/components/mobile/areas/mobile-misc";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { DocumentTemplateManager } from "@/components/settings/document-template-manager";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { templateTabs } from "@/components/ui/section-tabs";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { DocumentTemplate, DocumentTemplatePart } from "@/types/api";

export default async function SettingsPage() {
  const session = await requireSession();
  if (session.current_role !== "admin") {
    redirect("/");
  }
  const t = await getTranslations("nav");
  const [documentTemplates, documentTemplateParts] = await Promise.all([
    backendFetchWithSession<DocumentTemplate[]>("/api/document-templates"),
    backendFetchWithSession<DocumentTemplatePart[]>("/api/document-template-parts")
  ]);

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileDesktopOnly navKey="documentLayouts" backHref="/templates" backNavKey="templates" />}
        desktop={
          <>
          <RouteTabs tabs={templateTabs(t)} activeHref="/settings" />
          <section className="panel">
            <div className="section-stack">
              <DocumentTemplateManager
                initialTemplates={documentTemplates ?? []}
                initialParts={documentTemplateParts ?? []}
                tenantId={session.current_tenant?.id ?? null}
              />
            </div>
          </section>
          </>
        }
      />
    </AppShell>
  );
}
