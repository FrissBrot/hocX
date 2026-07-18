import { AppShell } from "@/components/ui/app-shell";
import { TodoListView } from "@/components/todos/todo-list-view";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { DocumentTemplate, EventSummary, ParticipantSummary, TodoBlock, TodoListItem } from "@/types/api";

export default async function TodosPage() {
  const session = await requireSession();
  const canAdmin = ["admin", "writer"].includes(session.current_role ?? "");
  const canEdit = canAdmin;

  const [allTodos, myTodos, todoBlocks, participants, documentTemplates, events] = await Promise.all([
    canAdmin ? backendFetchWithSession<TodoListItem[]>("/api/todos") : Promise.resolve(null),
    backendFetchWithSession<TodoListItem[]>("/api/todos/my"),
    backendFetchWithSession<TodoBlock[]>("/api/todos/blocks"),
    canAdmin ? backendFetchWithSession<ParticipantSummary[]>("/api/participants?limit=500") : Promise.resolve([]),
    backendFetchWithSession<DocumentTemplate[]>("/api/document-templates"),
    canAdmin ? backendFetchWithSession<EventSummary[]>("/api/events") : Promise.resolve([]),
  ]);

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <TodoListView
          allTodos={allTodos ?? null}
          myTodos={myTodos ?? []}
          canAdmin={canAdmin}
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
