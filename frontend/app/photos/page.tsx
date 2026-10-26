import { MobilePhotos } from "@/components/mobile/areas/mobile-misc";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";

import { PhotosView } from "@/components/photos/photos-view";
import { AppShell } from "@/components/ui/app-shell";
import { requireSession } from "@/lib/api/server";
import { can } from "@/lib/permissions";

export default async function PhotosPage() {
  const session = await requireSession();
  const canView = can(session, "files.manage");

  if (!canView) {
    redirect("/");
  }

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobilePhotos />}
        desktop={
          <>
          <section className="photos-page">
            <PhotosView />
          </section>
          </>
        }
      />
    </AppShell>
  );
}
