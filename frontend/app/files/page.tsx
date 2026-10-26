import { MobileFiles } from "@/components/mobile/areas/mobile-files";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";

import { FilesView } from "@/components/files/files-view";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { FileOverviewItem } from "@/types/api";
import { can } from "@/lib/permissions";

export default async function FilesPage() {
  const session = await requireSession();
  const canView = can(session, "files.manage");

  if (!canView) {
    redirect("/");
  }

  const files = await backendFetchWithSession<FileOverviewItem[]>("/api/files?exclude_images=true");

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileFiles initialItems={files ?? []} />}
        desktop={
          <>
          <section className="files-page">
            <FilesView initialItems={files ?? []} />
          </section>
          </>
        }
      />
    </AppShell>
  );
}
