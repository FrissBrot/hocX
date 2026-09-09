import { redirect } from "next/navigation";

import { FilesView } from "@/components/files/files-view";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { FileOverviewItem } from "@/types/api";

export default async function PhotosPage() {
  const session = await requireSession();
  const canView = ["admin", "writer"].includes(session.current_role ?? "");

  if (!canView) {
    redirect("/");
  }

  const photos = await backendFetchWithSession<FileOverviewItem[]>("/api/files?only_images=true");

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <FilesView mode="photos" initialItems={photos ?? []} />
      </section>
    </AppShell>
  );
}
