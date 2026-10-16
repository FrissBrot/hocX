import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { ResponsiveView } from "@/components/mobile/responsive-view";
import { DocumentVerificationSettings, type DocumentVerificationState } from "@/components/settings/document-verification-settings";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { documentStudioTabs } from "@/components/ui/section-tabs";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";

export default async function DocumentVerificationPage() {
  const session = await requireSession();
  if (session.current_role !== "admin") {
    redirect("/");
  }
  const t = await getTranslations("nav");
  const state = await backendFetchWithSession<DocumentVerificationState>("/api/document-verification");
  const content = state ? <DocumentVerificationSettings initialState={state} /> : null;

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={content}
        desktop={
          <>
            <RouteTabs tabs={documentStudioTabs(t, true)} activeHref="/settings/verification" />
            {content}
          </>
        }
      />
    </AppShell>
  );
}
