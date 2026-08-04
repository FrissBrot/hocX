import Link from "next/link";
import { AppShell } from "@/components/ui/app-shell";
import { requireSession } from "@/lib/api/server";

export default async function ToolsPage() {
  const session = await requireSession();

  return (
    <AppShell initialSession={session}>
      <div className="grid">
        <div className="page-header">
          <div>
            <h1 className="page-title">Tools</h1>
            <p className="muted">Zusatzwerkzeuge für einmalige oder seltene Aufgaben.</p>
          </div>
        </div>

        <Link href="/tools/word-import" className="card" style={{ display: "block", textDecoration: "none" }}>
          <h2 style={{ margin: "0 0 0.35rem" }}>Word-Protokoll-Import</h2>
          <p className="muted" style={{ margin: 0 }}>
            Ein altes .docx-Protokoll einlesen und als neues Protokoll mit Texten, Anwesenheit und Anlass-Verknüpfung anlegen.
          </p>
        </Link>
      </div>
    </AppShell>
  );
}
