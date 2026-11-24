import { redirect } from "next/navigation";

import { ProtocolEditor } from "@/components/protocol/protocol-editor";
import { LazyMobileProtocolEditor as MobileProtocolEditor } from "@/components/mobile/mobile-protocol-editor-lazy";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchAllPagesWithSession, backendFetchWithSession, requireSession } from "@/lib/api/server";
import {
  AttendanceFine,
  AttendanceFineListItem,
  EventSummary,
  FinanceAccount,
  FinanceTransaction,
  ParticipantSummary,
  ProtocolElement,
  ProtocolAgendaItem,
  ProtocolImage,
  ProtocolSummary,
  ProtocolTodo,
  StructuredListDefinition,
  StructuredListEntry,
  TemplateSummary,
  TodoListItem,
} from "@/types/api";
import { can, featureAccess } from "@/lib/permissions";
import { collectReferencedIds, selectInitialEvents, slimParticipantDirectory } from "@/lib/protocol/initial-editor-data";

export default async function ProtocolDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  // Alles, was nur die Protokoll-ID braucht, startet sofort parallel (vorher ~7 Stufen
  // nacheinander). Nur die Listeneinträge und Kontobuchungen hängen an den Elementen, die
  // Vorlagenteilnehmer am Protokoll. Aufgaben und Bilder aller Blöcke kommen gebündelt in je
  // einer Anfrage statt einer je Block.
  const sessionPromise = requireSession();
  const protocolPromise = backendFetchWithSession<ProtocolSummary>(`/api/protocols/${id}`);
  const elementsPromise = backendFetchWithSession<ProtocolElement[]>(`/api/protocols/${id}/elements`).then((v) => v ?? []);
  const templatesPromise = backendFetchWithSession<TemplateSummary[]>("/api/templates").then((v) => v ?? []);
  const eventsPromise = backendFetchAllPagesWithSession<EventSummary>("/api/events");
  const listsPromise = backendFetchWithSession<StructuredListDefinition[]>("/api/lists").then((v) => v ?? []);
  // Alle Teilnehmer, damit gespeicherte Auswahlen ausserhalb der Vorlage mit Namen statt "X ausgewaehlt" erscheinen.
  const participantDirectoryPromise = backendFetchWithSession<ParticipantSummary[]>("/api/participants?include_former=true&limit=2000").then((v) => v ?? []);
  const todosPromise = backendFetchWithSession<Record<string, ProtocolTodo[]>>(`/api/protocols/${id}/block-todos`).then((v) => v ?? {});
  const imagesPromise = backendFetchWithSession<Record<string, ProtocolImage[]>>(`/api/protocols/${id}/block-images`).then((v) => v ?? {});
  const pendingTodosPromise = backendFetchWithSession<TodoListItem[]>(`/api/protocols/${id}/pending-todos`).then((v) => v ?? []);
  const financeAccountsPromise = backendFetchWithSession<FinanceAccount[]>("/api/finance/accounts").then((v) => v ?? []);
  // Früher erst nach der Hydration im Editor geladen (Performance-Audit Protokoll-Editor). null =
  // nicht verfügbar: der Editor lädt dann selbst nach (wie bisher, Fehler bleiben still).
  const agendaItemsPromise = backendFetchWithSession<ProtocolAgendaItem[]>(`/api/protocols/${id}/agenda-items`);
  const scrollPositionPromise = backendFetchWithSession<{ element_id: string | null }>(`/api/protocols/${id}/scroll-position`);
  // Bussen nur mit reports.personal (wie im Editor); die Sitzung kommt ohnehin zuerst
  const finesAllowedPromise = sessionPromise.then((loaded) => can(loaded, "reports.personal")).catch(() => false);
  const protocolFinesPromise = finesAllowedPromise.then((allowed) =>
    allowed ? backendFetchWithSession<AttendanceFine[]>(`/api/protocols/${id}/fines`) : null
  );
  const pendingFinesPromise = finesAllowedPromise.then((allowed) =>
    allowed ? backendFetchWithSession<AttendanceFineListItem[]>(`/api/protocols/${id}/pending-fines`) : null
  );
  const participantsPromise = protocolPromise.then((loaded) =>
    loaded
      ? backendFetchWithSession<ParticipantSummary[]>(`/api/templates/${loaded.template_id}/participants`).then((v) => v ?? [])
      : []
  );
  const listEntriesPromise = elementsPromise.then(async (elements) => {
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
    return {
      ...entriesByPublicId,
      ...Object.fromEntries(Object.entries(listReferences).map(([internalId, publicId]) => [internalId, entriesByPublicId[publicId]])),
    };
  });
  // Pre-load transactions for finance blocks
  const financeTransactionsPromise = elementsPromise.then(async (elements) => {
    const accountReferences = Object.assign({}, ...elements.flatMap((element) =>
      element.blocks.map((block) => block.public_reference_ids?.finance_accounts ?? {})
    )) as Record<string, string>;
    const financeTransactionsList = await Promise.all(
      [...new Set(Object.values(accountReferences))].map(async (publicId) => ({
        publicId,
        transactions: (await backendFetchWithSession<FinanceTransaction[]>(`/api/finance/accounts/${publicId}/transactions?limit=200`)) ?? [],
      }))
    );
    const transactionsByPublicId = Object.fromEntries(financeTransactionsList.map((item) => [item.publicId, item.transactions]));
    return {
      ...transactionsByPublicId,
      ...Object.fromEntries(Object.entries(accountReferences).map(([internalId, publicId]) => [internalId, transactionsByPublicId[publicId]])),
    };
  });

  // Sitzung zuerst: ohne Anmeldung leitet requireSession() weiter, bevor ein fehlendes Protokoll zählt.
  const session = await sessionPromise;
  const isRestricted = !can(session, "meetings.edit");
  const canViewFines = can(session, "reports.personal");
  const protocol = await protocolPromise;

  if (!protocol) {
    redirect("/protocols");
  }

  const [
    templates,
    events,
    lists,
    elements,
    participants,
    participantDirectory,
    initialTodos,
    initialImages,
    pendingTodos,
    financeAccounts,
    initialListEntries,
    initialFinanceTransactions,
    agendaItems,
    scrollPosition,
    protocolFines,
    pendingFines,
  ] = await Promise.all([
    templatesPromise,
    eventsPromise,
    listsPromise,
    elementsPromise,
    participantsPromise,
    participantDirectoryPromise,
    todosPromise,
    imagesPromise,
    pendingTodosPromise,
    financeAccountsPromise,
    listEntriesPromise,
    financeTransactionsPromise,
    agendaItemsPromise,
    scrollPositionPromise,
    protocolFinesPromise,
    pendingFinesPromise,
  ]);

  // Nur, was der Editor zum ersten Darstellen braucht, in die Seite (L5): Termine, die das
  // Protokoll anzeigen kann, und Namen verwiesener Personen. Ältere Termine lädt der Editor
  // danach nach (eventsComplete=false), siehe lib/protocol/initial-editor-data.ts.
  const referencedIds = collectReferencedIds(elements, initialTodos, pendingTodos, initialListEntries, initialFinanceTransactions, agendaItems, protocolFines, pendingFines);
  // Gestern (UTC): auch auf einem Server in einer anderen Zeitzone nie nach dem Schweizer «heute»
  const today = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10);
  const initialEvents = selectInitialEvents(events, { elements, protocolDate: protocol.protocol_date, today, referencedIds });
  const directory = slimParticipantDirectory(participantDirectory, collectReferencedIds([...referencedIds], initialEvents.events));

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={
          <MobileProtocolEditor
            protocol={protocol}
            initialElements={elements}
            initialTodos={initialTodos}
            initialImages={initialImages}
            availableParticipants={participants}
            availableAccounts={financeAccounts}
            initialFinanceTransactions={initialFinanceTransactions}
            initialPendingTodos={pendingTodos}
            forceReadOnly={isRestricted}
            canManageFines={can(session, "fines.manage")}
          />
        }
        desktop={
          <section className="panel protocol-panel-document">
            <ProtocolEditor
              protocol={protocol}
              initialElements={elements}
              initialTodos={initialTodos}
              initialImages={initialImages}
              availableParticipants={participants}
              participantDirectory={directory}
              availableEvents={initialEvents.events}
              eventsComplete={initialEvents.complete}
              availableLists={lists}
              initialListEntries={initialListEntries}
              availableTemplates={templates}
              availableAccounts={financeAccounts}
              initialFinanceTransactions={initialFinanceTransactions}
              initialPendingTodos={pendingTodos}
              forceReadOnly={isRestricted}
              canManageFinances={can(session, "fines.manage")}
              todoFines={{
                visible: can(session, "finances.read") && featureAccess(session, "todo_fines") !== "none",
                manage: can(session, "fines.manage") && featureAccess(session, "todo_fines") === "full",
                currency: session.current_tenant?.finance_currency ?? "CHF",
              }}
              canViewFines={canViewFines}
              canCollectSubmissions={can(session, "submissions.manage") && can(session, "meetings.edit")}
              canApprove={can(session, "meetings.approve")}
              initialAgendaItems={agendaItems}
              initialScrollPosition={scrollPosition}
              initialProtocolFines={protocolFines}
              initialPendingFines={pendingFines}
            />
          </section>
        }
      />
    </AppShell>
  );
}
