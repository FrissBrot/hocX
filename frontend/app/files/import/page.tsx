import { redirect } from "next/navigation";

import { FileImportView } from "@/components/file-import/file-import-view";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import type { CloudProvider, ImportJob } from "@/lib/files/file-import";
import { can } from "@/lib/permissions";

export default async function FileImportPage() {
  const session = await requireSession();
  if (!can(session, "files.import")) {
    redirect("/files");
  }
  const [jobs, providers] = await Promise.all([
    backendFetchWithSession<ImportJob[]>("/api/cloud-import/jobs"),
    backendFetchWithSession<CloudProvider[]>("/api/cloud-import/providers"),
  ]);
  return (
    <AppShell initialSession={session}>
      <section className="file-import-shell">
        <FileImportView initialJobs={jobs ?? []} providers={providers ?? []} />
      </section>
    </AppShell>
  );
}
