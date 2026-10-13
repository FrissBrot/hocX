import { MobileDesktopOnly } from "@/components/mobile/areas/mobile-misc";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { HouseStyleSettings } from "@/components/settings/house-style-settings";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { templateTabs } from "@/components/ui/section-tabs";
import { defaultLocale, locales } from "@/i18n/locale-config.generated";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { DocumentStyle, DocumentStyleAsset } from "@/lib/documents/api";

export default async function SettingsPage() {
  const session = await requireSession();
  if (session.current_role !== "admin") {
    redirect("/");
  }
  const t = await getTranslations("nav");
  const [styles, assets, documentSettings] = await Promise.all([
    backendFetchWithSession<DocumentStyle[]>("/api/document-styles"),
    backendFetchWithSession<DocumentStyleAsset[]>("/api/document-style-assets"),
    backendFetchWithSession<{ language: string }>("/api/document-settings"),
  ]);

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileDesktopOnly navKey="documentLayouts" backHref="/templates" backNavKey="templates" />}
        desktop={
          <>
            <RouteTabs tabs={templateTabs(t)} activeHref="/settings" />
            <HouseStyleSettings
              initialStyles={styles ?? []}
              initialAssets={assets ?? []}
              initialLanguage={documentSettings?.language ?? defaultLocale}
              languages={[...locales]}
              canEdit
            />
          </>
        }
      />
    </AppShell>
  );
}
