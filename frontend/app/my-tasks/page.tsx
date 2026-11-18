import { AppShell } from "@/components/ui/app-shell";
import { TodoListView } from "@/components/todos/todo-list-view";
import { MobileTodos } from "@/components/mobile/mobile-todos";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { ParticipantSummary, TodoBlock, TodoListItem } from "@/types/api";
import { can, featureAccess } from "@/lib/permissions";

/** «Meine Aufgaben»: die eigenen Pendenzen (auch Abgaben), Fälliges zuerst. Die ganze Liste des
 * Mandanten steht unter Aufgaben › Pendenzen (/todos); mobil zeigt der Pendenzen-Tab dasselbe. */
export default async function MyTasksPage() {
  const session = await requireSession();
  const canEdit = can(session, "meetings.edit");
  const [myTodos, todoBlocks, participants] = await Promise.all([
    backendFetchWithSession<TodoListItem[]>("/api/todos/my"),
    canEdit ? backendFetchWithSession<TodoBlock[]>("/api/todos/blocks") : Promise.resolve([]),
    canEdit ? backendFetchWithSession<ParticipantSummary[]>("/api/participants?limit=500") : Promise.resolve([]),
  ]);

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileTodos allTodos={null} myTodos={myTodos ?? []} canEdit={canEdit} participants={participants ?? []} />}
        desktop={
          <section className="panel">
            <TodoListView
              personal
              allTodos={null}
              myTodos={myTodos ?? []}
              session={session}
              canEdit={canEdit}
              todoBlocks={todoBlocks ?? []}
              participants={participants ?? []}
              finesEnabled={featureAccess(session, "todo_fines") !== "none"}
            />
          </section>
        }
      />
    </AppShell>
  );
}
