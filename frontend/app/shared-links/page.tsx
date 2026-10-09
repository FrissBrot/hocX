import { MobileSharedLinks } from "@/components/mobile/areas/mobile-admin";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";

import { SharedLinksView } from "@/components/shared-links/shared-links-view";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { ShareLink } from "@/types/api";

export default async function SharedLinksPage() {
  const session = await requireSession();
  const canView = ["admin", "writer"].includes(session.current_role ?? "");

  if (!canView) {
    redirect("/");
  }

  const links = await backendFetchWithSession<ShareLink[]>("/api/share-links");

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileSharedLinks initialLinks={links ?? []} />}
        desktop={
          <>
          <section className="panel">
            <SharedLinksView initialLinks={links ?? []} />
          </section>
          </>
        }
      />
    </AppShell>
  );
}
