// Gemeinsamer Rahmen der Seiten im Bereich «Vorlagen»: AppShell, Bereichs-Tabs und - auf dem
// Smartphone - der Hinweis, dass die Gestaltung für grössere Bildschirme gedacht ist.

import { ReactNode } from "react";
import { getTranslations } from "next-intl/server";

import { MobileDesktopOnly } from "@/components/mobile/areas/mobile-misc";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { templateAreaTabs } from "@/components/ui/section-tabs";
import type { SessionInfo } from "@/types/api";

export async function StudioPage({ session, activeHref, children }: { session: SessionInfo; activeHref: string; children: ReactNode }) {
  const t = await getTranslations("nav");
  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileDesktopOnly navKey="documentStudio" />}
        desktop={
          <>
            <RouteTabs tabs={templateAreaTabs(t, session.current_role === "admin")} activeHref={activeHref} />
            {children}
          </>
        }
      />
    </AppShell>
  );
}
