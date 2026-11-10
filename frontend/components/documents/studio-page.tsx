// Gemeinsamer Rahmen der Seiten im Bereich «Gestaltung»: AppShell, Bereichs-Tabs und - auf dem
// Smartphone - der Hinweis, dass die Gestaltung für grössere Bildschirme gedacht ist.

import { ReactNode } from "react";
import { getTranslations } from "next-intl/server";

import { MobileDesktopOnly } from "@/components/mobile/areas/mobile-misc";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { designAreaTabs } from "@/components/ui/section-tabs";
import type { SessionInfo } from "@/types/api";

export async function StudioPage({ session, activeHref, children }: { session: SessionInfo; activeHref: string; children: ReactNode }) {
  const t = await getTranslations("nav");
  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileDesktopOnly navKey="design" />}
        desktop={
          <>
            <RouteTabs tabs={designAreaTabs(t)} activeHref={activeHref} />
            {children}
          </>
        }
      />
    </AppShell>
  );
}
