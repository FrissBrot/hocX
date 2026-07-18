import { ProtocolEditor } from "@/components/protocol/protocol-editor";
import { ProtocolOverview } from "@/components/protocol/protocol-builder";
import { ProtocolExportPanel } from "@/components/protocol/protocol-export-panel";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import {
  DocumentTemplate,
  EventSummary,
  FinanceAccount,
  FinanceTransaction,
  ParticipantSummary,
  ProtocolElement,
  ProtocolImage,
  ProtocolSummary,
  ProtocolTodo,
  StructuredListDefinition,
  StructuredListEntry,
  TemplateSummary,
  TodoListItem,
} from "@/types/api";

export default async function ProtocolDetailPage({ params }: { params: { id: string } }) {
  const session = await requireSession();
  const isRestricted = ["reader", "kassier"].includes(session.current_role ?? "");
  const canViewFines = ["kassier", "writer", "admin"].includes(session.current_role ?? "");
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
  const templates = (await backendFetchWithSession<TemplateSummary[]>("/api/templates")) ?? [];
  const events = (await backendFetchWithSession<EventSummary[]>("/api/events")) ?? [];
  const lists = (await backendFetchWithSession<StructuredListDefinition[]>("/api/lists")) ?? [];
  const elements = (await backendFetchWithSession<ProtocolElement[]>(`/api/protocols/${params.id}/elements`)) ?? [];
  const participants =
    (await backendFetchWithSession<ParticipantSummary[]>(`/api/templates/${protocol.template_id}/participants`)) ?? [];
  const linkedListIds = Array.from(
    new Set(
      elements.flatMap((element) =>
        element.blocks.flatMap((block) => {
          const cfg = (block.configuration_snapshot_json as Record<string, unknown> | null) ?? {};
          const ids: number[] = [];
          const linkedId = Number(cfg.linked_list_id ?? 0);
          if (linkedId > 0) ids.push(linkedId);
          const autoSrc = cfg.auto_source as Record<string, unknown> | null | undefined;
          const autoListId = Number(autoSrc?.list_id ?? 0);
          if (autoListId > 0) ids.push(autoListId);
          return ids;
        })
      )
    )
  );
  const listEntries = await Promise.all(
    linkedListIds.map(async (listId) => ({
      listId,
      entries: (await backendFetchWithSession<StructuredListEntry[]>(`/api/lists/${listId}/entries`)) ?? [],
    }))
  );
  const initialListEntries = Object.fromEntries(listEntries.map((item) => [item.listId, item.entries]));
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

  const pendingTodos = (await backendFetchWithSession<TodoListItem[]>(`/api/protocols/${params.id}/pending-todos`)) ?? [];
  const latestExport = (await backendFetchWithSession(`/api/protocols/${params.id}/exports/latest`)) ?? { protocol_id: Number(params.id), export_format: "none", status: "missing" };

  const financeAccounts = (await backendFetchWithSession<FinanceAccount[]>("/api/finance/accounts")) ?? [];
  // Pre-load transactions for finance blocks
  const financeBlockAccountIds = Array.from(new Set(
    elements.flatMap((element) =>
      element.blocks
        .filter((b) => b.element_type_code === "finance_balance" || b.element_type_code === "finance_transactions")
        .map((b) => Number((b.configuration_snapshot_json as Record<string, unknown>)?.finance_account_id ?? 0))
        .filter((id) => id > 0)
    )
  ));
  const financeTransactionsList = await Promise.all(
    financeBlockAccountIds.map(async (accountId) => ({
      accountId,
      transactions: (await backendFetchWithSession<FinanceTransaction[]>(`/api/finance/accounts/${accountId}/transactions`)) ?? [],
    }))
  );
  const initialFinanceTransactions = Object.fromEntries(financeTransactionsList.map((item) => [item.accountId, item.transactions]));

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <ProtocolOverview protocol={protocol} />
        <ProtocolExportPanel
          protocol={protocol}
          initialLatestExport={latestExport as any}
        />
        <ProtocolEditor
          protocol={protocol}
          initialElements={elements}
          initialTodos={initialTodos}
          initialImages={initialImages}
          availableParticipants={participants}
          availableEvents={events}
          availableLists={lists}
          initialListEntries={initialListEntries}
          availableTemplates={templates}
          availableAccounts={financeAccounts}
          initialFinanceTransactions={initialFinanceTransactions}
          initialPendingTodos={pendingTodos}
          documentTemplates={documentTemplates}
          forceReadOnly={isRestricted}
          canViewFines={canViewFines}
        />
      </section>
    </AppShell>
  );
}
