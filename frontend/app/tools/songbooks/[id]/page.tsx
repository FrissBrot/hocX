import { redirect } from "next/navigation";

import { SongbookEditor } from "@/components/songbooks/songbook-editor";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { Songbook } from "@/types/api";

export default async function SongbookPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const session = await requireSession();
  const book = await backendFetchWithSession<Songbook>(`/api/songbooks/${id}`);
  if (!book) redirect("/tools/songbooks");

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <SongbookEditor initialBook={book} />
      </section>
    </AppShell>
  );
}
