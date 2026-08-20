import { redirect } from "next/navigation";

import { StorageUsageView } from "@/components/storage/storage-usage-view";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { StorageUsageRead } from "@/types/api";

export default async function StoragePage() {
  const session = await requireSession();
  if (session.current_role !== "admin") {
    redirect("/");
  }

  const usage = await backendFetchWithSession<StorageUsageRead>("/api/storage/usage");

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <StorageUsageView usage={usage ?? null} />
      </section>
    </AppShell>
  );
}
