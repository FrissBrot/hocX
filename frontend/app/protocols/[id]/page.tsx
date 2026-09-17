import { redirect } from "next/navigation";

import { ProtocolEditor } from "@/components/protocol/protocol-editor";
import { ProtocolOverview } from "@/components/protocol/protocol-builder";
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

export default async function ProtocolDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const session = await requireSession();
  const isRestricted = ["reader", "kassier"].includes(session.current_role ?? "");
  const canViewFines = ["kassier", "writer", "admin"].includes(session.current_role ?? "");
  const protocol = await backendFetchWithSession<ProtocolSummary>(`/api/protocols/${id}`);

  if (!protocol) {
    redirect("/protocols");
  }

  const participantsQuery = protocol.protocol_date ? `?as_of=${encodeURIComponent(protocol.protocol_date)}` : "";
  const [documentTemplates, templates, events, lists, elements, participants] = await Promise.all([
    backendFetchWithSession<DocumentTemplate[]>("/api/document-templates").then((v) => v ?? []),
    backendFetchWithSession<TemplateSummary[]>("/api/templates").then((v) => v ?? []),
    backendFetchWithSession<EventSummary[]>("/api/events").then((v) => v ?? []),
    backendFetchWithSession<StructuredListDefinition[]>("/api/lists").then((v) => v ?? []),
    backendFetchWithSession<ProtocolElement[]>(`/api/protocols/${id}/elements`).then((v) => v ?? []),
    backendFetchWithSession<ParticipantSummary[]>(
      `/api/templates/${protocol.template_id}/participants${participantsQuery}`
    ).then((v) => v ?? []),
  ]);
  const listReferences = Object.assign({}, ...elements.flatMap((element) =>
    element.blocks.map((block) => block.public_reference_ids?.lists ?? {})
  )) as Record<string, string>;
  const listEntries = await Promise.all(
    [...new Set(Object.values(listReferences))].map(async (publicId) => ({
      publicId,
      entries: (await backendFetchWithSession<StructuredListEntry[]>(`/api/lists/${publicId}/entries`)) ?? [],
    }))
  );
  const entriesByPublicId = Object.fromEntries(listEntries.map((item) => [item.publicId, item.entries]));
  const initialListEntries = {
    ...entriesByPublicId,
    ...Object.fromEntries(Object.entries(listReferences).map(([internalId, publicId]) => [internalId, entriesByPublicId[publicId]])),
  };
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

  const pendingTodos = (await backendFetchWithSession<TodoListItem[]>(`/api/protocols/${id}/pending-todos`)) ?? [];

  const financeAccounts = (await backendFetchWithSession<FinanceAccount[]>("/api/finance/accounts")) ?? [];
  // Pre-load transactions for finance blocks
  const accountReferences = Object.assign({}, ...elements.flatMap((element) =>
    element.blocks.map((block) => block.public_reference_ids?.finance_accounts ?? {})
  )) as Record<string, string>;
  const financeTransactionsList = await Promise.all(
    [...new Set(Object.values(accountReferences))].map(async (publicId) => ({
      publicId,
      transactions: (await backendFetchWithSession<FinanceTransaction[]>(`/api/finance/accounts/${publicId}/transactions`)) ?? [],
    }))
  );
  const transactionsByPublicId = Object.fromEntries(financeTransactionsList.map((item) => [item.publicId, item.transactions]));
  const initialFinanceTransactions = {
    ...transactionsByPublicId,
    ...Object.fromEntries(Object.entries(accountReferences).map(([internalId, publicId]) => [internalId, transactionsByPublicId[publicId]])),
  };

  return (
    <AppShell initialSession={session}>
      <section className={`panel${protocol.status !== "abgeschlossen" ? " protocol-panel-document" : ""}`}>
        {protocol.status === "abgeschlossen" && <ProtocolOverview protocol={protocol} />}
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
          accordionEnabled={session.user?.protocol_accordion_enabled ?? true}
        />
      </section>
    </AppShell>
  );
}
