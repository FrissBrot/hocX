import { ProtocolEditor } from "@/components/protocol/protocol-editor";
import { ProtocolOverview } from "@/components/protocol/protocol-builder";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetch } from "@/lib/api/client";
import { ProtocolElement, ProtocolImage, ProtocolSummary, ProtocolTodo } from "@/types/api";

export default async function ProtocolDetailPage({ params }: { params: { id: string } }) {
  const protocol = await backendFetch<ProtocolSummary>(`/api/protocols/${params.id}`);

  if (!protocol) {
    return (
      <AppShell>
        <section className="panel">
          <div className="eyebrow">Protocol Detail</div>
          <h1>Protocol not found</h1>
          <p className="muted">The requested protocol could not be loaded from the backend.</p>
        </section>
      </AppShell>
    );
  }

  const elements = (await backendFetch<ProtocolElement[]>(`/api/protocols/${params.id}/elements`)) ?? [];
  const todoElements = elements.filter((element) => element.element_type_code === "todo");
  const todoLists = await Promise.all(
    todoElements.map(async (element) => ({
      protocolElementId: element.id,
      todos: (await backendFetch<ProtocolTodo[]>(`/api/protocol-elements/${element.id}/todos`)) ?? []
    }))
  );
  const initialTodos = Object.fromEntries(todoLists.map((item) => [item.protocolElementId, item.todos]));
  const imageElements = elements.filter((element) => element.element_type_code === "image");
  const imageLists = await Promise.all(
    imageElements.map(async (element) => ({
      protocolElementId: element.id,
      images: (await backendFetch<ProtocolImage[]>(`/api/protocol-elements/${element.id}/images`)) ?? []
    }))
  );
  const initialImages = Object.fromEntries(imageLists.map((item) => [item.protocolElementId, item.images]));

  return (
    <AppShell>
      <section className="panel">
        <div className="eyebrow">Protocol Detail</div>
        <h1>{protocol.title ?? protocol.protocol_number}</h1>
        <p className="muted">This editor now renders real protocol blocks and starts the autosave flow for text and todos.</p>
        <ProtocolOverview protocol={protocol} />
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
