import { SongbookList } from "@/components/songbooks/songbook-list";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { SongbookSummary } from "@/types/api";

export default async function SongbooksPage() {
  const session = await requireSession();
  const books = (await backendFetchWithSession<SongbookSummary[]>("/api/songbooks")) ?? [];

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <SongbookList initialBooks={books} />
      </section>
    </AppShell>
  );
}
