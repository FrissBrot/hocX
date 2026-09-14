import { redirect } from "next/navigation";

import { PhotosView } from "@/components/photos/photos-view";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { FileOverviewItem } from "@/types/api";

export default async function PhotosPage() {
  const session = await requireSession();
  const canView = ["admin", "writer"].includes(session.current_role ?? "");

  if (!canView) {
    redirect("/");
  }

  // Fetched here (matching PhotosView's own default filters/sort) so the first page of
  // photos - and the <img> requests for their thumbnails - are already in the server-rendered
  // HTML instead of only starting after the client mounts and fires its own request.
  const photos = await backendFetchWithSession<FileOverviewItem[]>(
    "/api/files?only_images=true&sort_by=group_date&sort_dir=desc"
  );

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <PhotosView initialItems={photos ?? []} />
      </section>
    </AppShell>
  );
}
