import { ProtocolEditor } from "@/components/protocol/protocol-editor";
import { ProtocolOverview } from "@/components/protocol/protocol-builder";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { DocumentTemplate, ProtocolElement, ProtocolImage, ProtocolSummary, ProtocolTodo } from "@/types/api";

export default async function ProtocolDetailPage({ params }: { params: { id: string } }) {
  const session = await requireSession();
  const protocol = await backendFetchWithSession<ProtocolSummary>(`/api/protocols/${params.id}`);

  if (!protocol) {
    return (
      <AppShell initialSession={session}>
        <section className="panel">
          <div className="eyebrow">Protocol Detail</div>
          <h1>Protocol not found</h1>
          <p className="muted">The requested protocol could not be loaded from the backend.</p>
        </section>
      </AppShell>
    );
  }

  const documentTemplates = (await backendFetchWithSession<DocumentTemplate[]>("/api/document-templates")) ?? [];
  const elements = (await backendFetchWithSession<ProtocolElement[]>(`/api/protocols/${params.id}/elements`)) ?? [];
  const todoBlocks = elements.flatMap((element) => element.blocks.filter((block) => block.element_type_code === "todo"));
  const todoLists = await Promise.all(
    todoBlocks.map(async (block) => ({
      protocolElementBlockId: block.id,
      todos: (await backendFetchWithSession<ProtocolTodo[]>(`/api/protocol-element-blocks/${block.id}/todos`)) ?? []
    }))
  );
  const initialTodos = Object.fromEntries(todoLists.map((item) => [item.protocolElementBlockId, item.todos]));
  const imageBlocks = elements.flatMap((element) => element.blocks.filter((block) => block.element_type_code === "image"));
  const imageLists = await Promise.all(
    imageBlocks.map(async (block) => ({
      protocolElementBlockId: block.id,
      images: (await backendFetchWithSession<ProtocolImage[]>(`/api/protocol-element-blocks/${block.id}/images`)) ?? []
    }))
  );
  const initialImages = Object.fromEntries(imageLists.map((item) => [item.protocolElementBlockId, item.images]));
  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <div className="eyebrow">Protocol Detail</div>
        <h1>{protocol.title ?? protocol.protocol_number}</h1>
        <p className="muted">This editor now renders real protocol blocks and starts the autosave flow for text and todos.</p>
        <ProtocolOverview protocol={protocol} documentTemplates={documentTemplates} />
        <ProtocolEditor
          protocol={protocol}
          initialElements={elements}
          initialTodos={initialTodos}
          initialImages={initialImages}
        />
      </section>
    </AppShell>
  );
}
