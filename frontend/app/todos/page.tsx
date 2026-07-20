import { AppShell } from "@/components/ui/app-shell";
import { TodoListView } from "@/components/todos/todo-list-view";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { DocumentTemplate, EventSummary, ParticipantSummary, TodoBlock, TodoListItem } from "@/types/api";

export default async function TodosPage() {
  const session = await requireSession();
  const canEdit = ["admin", "writer"].includes(session.current_role ?? "");

  // Every role sees all tenant todos now (backend scopes restricted readers server-side);
  // participant/event lookups are only needed for the writer/admin edit & assignment UI.
  const [allTodos, myTodos, todoBlocks, participants, documentTemplates, events] = await Promise.all([
    backendFetchWithSession<TodoListItem[]>("/api/todos"),
    backendFetchWithSession<TodoListItem[]>("/api/todos/my"),
    backendFetchWithSession<TodoBlock[]>("/api/todos/blocks"),
    canEdit ? backendFetchWithSession<ParticipantSummary[]>("/api/participants?limit=500") : Promise.resolve([]),
    backendFetchWithSession<DocumentTemplate[]>("/api/document-templates"),
    canEdit ? backendFetchWithSession<EventSummary[]>("/api/events") : Promise.resolve([]),
  ]);

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <TodoListView
          allTodos={allTodos ?? null}
          myTodos={myTodos ?? []}
          canEdit={canEdit}
          todoBlocks={todoBlocks ?? []}
          participants={participants ?? []}
          documentTemplates={documentTemplates ?? []}
          events={events ?? []}
        />
      </section>
    </AppShell>
  );
}
