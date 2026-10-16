import { AppShell } from "@/components/ui/app-shell";
import { TodoListView } from "@/components/todos/todo-list-view";
import { MobileTodos } from "@/components/mobile/mobile-todos";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { ParticipantSummary, TodoBlock, TodoListItem } from "@/types/api";

export default async function TodosPage() {
  const session = await requireSession();
  const canEdit = ["admin", "writer"].includes(session.current_role ?? "");

  // Every role sees all tenant todos now (backend scopes restricted readers server-side);
  // participant lookups are only needed for the writer/admin edit & assignment UI.
  const [allTodos, myTodos, todoBlocks, participants] = await Promise.all([
    backendFetchWithSession<TodoListItem[]>("/api/todos"),
    backendFetchWithSession<TodoListItem[]>("/api/todos/my"),
    backendFetchWithSession<TodoBlock[]>("/api/todos/blocks"),
    canEdit ? backendFetchWithSession<ParticipantSummary[]>("/api/participants?limit=500") : Promise.resolve([]),
  ]);

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileTodos allTodos={allTodos ?? null} myTodos={myTodos ?? []} canEdit={canEdit} participants={participants ?? []} />}
        desktop={
          <section className="panel">
            <TodoListView
              allTodos={allTodos ?? null}
              myTodos={myTodos ?? []}
              canEdit={canEdit}
              todoBlocks={todoBlocks ?? []}
              participants={participants ?? []}
            />
          </section>
        }
      />
    </AppShell>
  );
}
