import { ProtocolEditor } from "@/components/protocol/protocol-editor";
import { AppShell } from "@/components/ui/app-shell";

export default function ProtocolDetailPage({ params }: { params: { id: string } }) {
  return (
    <AppShell>
      <section className="panel">
        <div className="eyebrow">Protocol Editor</div>
        <h1>Protocol #{params.id}</h1>
        <p className="muted">This starter uses block-based editing so autosave can later persist per element.</p>
        <ProtocolEditor />
      </section>
    </AppShell>
  );
}

