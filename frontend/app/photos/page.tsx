import { redirect } from "next/navigation";

import { PhotosView } from "@/components/photos/photos-view";
import { AppShell } from "@/components/ui/app-shell";
import { requireSession } from "@/lib/api/server";

export default async function PhotosPage() {
  const session = await requireSession();
  const canView = ["admin", "writer"].includes(session.current_role ?? "");

  if (!canView) {
    redirect("/");
  }

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <PhotosView />
      </section>
    </AppShell>
  );
}
