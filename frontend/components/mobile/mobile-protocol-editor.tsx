"use client";

import { useRouter } from "next/navigation";
import type { Route } from "next";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { MobileIcon } from "@/components/mobile/mobile-icons";
import { useMobileSession } from "@/components/mobile/mobile-shell";
import { MobileAvatar, MobileCheck, MobileChip, MobileSegmented } from "@/components/mobile/mobile-ui";
import { dateParts } from "@/components/mobile/mobile-utils";
import { attendanceFineConfig, syncAttendanceFine } from "@/components/protocol/attendance-fines";
import { ChartBlockRenderer } from "@/components/protocol/chart-block-renderer";
import {
  formatFinanceAmount,
  protocolAttendanceParticipants,
  tallyAttendance,
  TODO_STATUS,
  trimSectionName,
  visibleBlockTitle,
} from "@/components/protocol/protocol-editor-shared";
import { protocolStatusLabel } from "@/components/protocol/protocol-status";
import { ActionMenu } from "@/components/ui/action-menu";
import { Modal } from "@/components/ui/modal";
import { RichTextEditor } from "@/components/ui/rich-text-editor";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { ApiError, browserApiFetch } from "@/lib/api/client";
import { usePdfExport } from "@/lib/hooks/use-pdf-export";
import { useProtocolCollaboration } from "@/lib/hooks/use-protocol-collaboration";
import type {
  AttendanceFine,
  FinanceAccount,
  FinanceTransaction,
  ParticipantSummary,
  ProtocolElement,
  ProtocolElementBlock,
  ProtocolImage,
  ProtocolSummary,
  ProtocolTodo,
  TodoListItem,
} from "@/types/api";

// Mobiler Protokoll-Editor nach dem Design "hocX Mobile": Abschnitte untereinander, Text,
// Anwesenheit, Todos und Bilder direkt bearbeitbar, alle uebrigen Blocktypen lesend bzw. mit
// Hinweis auf den Computer. Speichert ueber dieselben Endpunkte wie der Desktop-Editor und
// meldet Aenderungen ueber denselben Kollaborationskanal, damit offene Desktop-Editoren live
// mitlaufen.

const STATUS_FLOW = ["geplant", "vorbereitet", "durchgeführt", "abgeschlossen"] as const;
const ATTENDANCE_STATUSES = ["present", "late", "excused", "absent"] as const;
type AttendanceStatus = (typeof ATTENDANCE_STATUSES)[number];
// Blocktypen, die mobil bearbeitet oder sinnvoll gelesen werden koennen; alles andere zeigt
// einen Hinweis auf die Desktop-Ansicht (Matrix, Formulare, Terminlisten ...).
const MOBILE_BLOCK_TYPES = new Set(["text", "static_text", "attendance", "todo", "image", "finance_balance", "finance_transactions", "chart", "session_date"]);

type Sheet =
  | { kind: "text"; blockId: string; sectionName: string }
  | { kind: "attendance"; blockId: string }
  | { kind: "notes" }
  | { kind: "todos"; blockId: string | null; sectionName: string }
  | { kind: "status" }
  | { kind: "photo"; blockId: string };

type SaveState = "idle" | "saving" | "saved" | "error";

function blockConfig(block: ProtocolElementBlock): Record<string, unknown> {
  return block.configuration_snapshot_json ?? {};
}

function attendanceEntries(block: ProtocolElementBlock): Array<Record<string, unknown>> {
  const entries = blockConfig(block).attendance_entries;
  return Array.isArray(entries) ? (entries as Array<Record<string, unknown>>) : [];
}

export function MobileProtocolEditor({
  protocol,
  initialElements,
  initialTodos,
  initialImages,
  availableParticipants,
  availableAccounts,
  initialFinanceTransactions,
  initialPendingTodos,
  forceReadOnly,
}: {
  protocol: ProtocolSummary;
  initialElements: ProtocolElement[];
  initialTodos: Record<string, ProtocolTodo[]>;
  initialImages: Record<string, ProtocolImage[]>;
  availableParticipants: ParticipantSummary[];
  availableAccounts: FinanceAccount[];
  initialFinanceTransactions: Record<string, FinanceTransaction[]>;
  initialPendingTodos: TodoListItem[];
  forceReadOnly: boolean;
}) {
  const t = useTranslations("mobile");
  const tProtocols = useTranslations("protocols");
  const locale = useLocale();
  const router = useRouter();
  const showToast = useToast();
  const confirm = useConfirm();
  const session = useMobileSession();
  const collab = useProtocolCollaboration(protocol.id);
  const { busyByProtocol, openOrGeneratePdf } = usePdfExport();

  const [elements, setElements] = useState(initialElements);
  const [todosByBlock, setTodosByBlock] = useState(initialTodos);
  const [imagesByBlock, setImagesByBlock] = useState(initialImages);
  const [pendingTodos, setPendingTodos] = useState(initialPendingTodos);
  const [status, setStatus] = useState(protocol.status);
  const [sessionNotes, setSessionNotes] = useState(protocol.session_notes ?? "");
  const [fines, setFines] = useState<AttendanceFine[]>([]);
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [activeSection, setActiveSection] = useState(0);
  const sectionRefs = useRef<Array<HTMLElement | null>>([]);
  const chipRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const isReadOnly = forceReadOnly || status === "abgeschlossen";
  const forceEditable = !forceReadOnly && (status === "geplant" || status === "durchgeführt");
  const trackChangesActive = status === "geplant" && (protocol.track_changes_enabled ?? false);

  const sections = useMemo(
    () =>
      elements
        .filter((element) => element.is_visible_snapshot)
        .map((element) => ({ element, blocks: element.blocks.filter((block) => block.is_visible_snapshot) }))
        .filter((section) => section.blocks.length > 0),
    [elements]
  );
  const allBlocks = useMemo(() => sections.flatMap((section) => section.blocks), [sections]);
  const attendanceBlock = allBlocks.find((block) => block.element_type_code === "attendance") ?? null;
  const todoBlockIds = allBlocks.filter((block) => block.element_type_code === "todo").map((block) => block.id);
  const protocolTodos = todoBlockIds.flatMap((id) => todosByBlock[id] ?? []);
  const openTodoCount = protocolTodos.filter((todo) => todo.todo_status_code !== "done" && todo.todo_status_code !== "cancelled").length;

  const blockEditable = useCallback(
    (block: ProtocolElementBlock) => !isReadOnly && !collab.isLockedByOther(`block-${block.id}`) && (forceEditable || block.is_editable_snapshot),
    [isReadOnly, forceEditable, collab]
  );

  const updateBlock = useCallback((blockId: string, update: (block: ProtocolElementBlock) => ProtocolElementBlock) => {
    setElements((current) =>
      current.map((element) => ({ ...element, blocks: element.blocks.map((block) => (block.id === blockId ? update(block) : block)) }))
    );
  }, []);

  const markSaved = useCallback(() => {
    setSaveState("saved");
  }, []);

  // Offene Bussen dieses Protokolls (fuer Hinweise in der Anwesenheit und die Bussen-Logik).
  useEffect(() => {
    browserApiFetch<AttendanceFine[]>(`/api/protocols/${protocol.id}/fines`)
      .then((list) => setFines(list ?? []))
      .catch(() => {});
  }, [protocol.id]);

  // Live-Aenderungen anderer Bearbeiter (gleiches Format wie im Desktop-Editor).
  useEffect(
    () =>
      collab.onFieldUpdate(({ field_key, patch }) => {
        if (!field_key.startsWith("block-")) return;
        if (field_key.endsWith("-todos") && Array.isArray(patch)) {
          setTodosByBlock((current) => ({ ...current, [field_key.slice(6, -6)]: patch as ProtocolTodo[] }));
          return;
        }
        if (field_key.endsWith("-images") && Array.isArray(patch)) {
          setImagesByBlock((current) => ({ ...current, [field_key.slice(6, -7)]: patch as ProtocolImage[] }));
          return;
        }
        const blockId = field_key.slice(6).split("-cell-")[0];
        if (blockId && patch && typeof patch === "object") updateBlock(blockId, (block) => ({ ...block, ...(patch as Partial<ProtocolElementBlock>) }));
      }),
    [collab.onFieldUpdate, updateBlock]
  );

  useEffect(
    () =>
      collab.onStatusChanged(({ status: next, display_name }) => {
        setStatus(next);
        showToast(t("editor.statusChangedBy", { name: display_name, status: protocolStatusLabel(next, tProtocols) }), "info");
      }),
    [collab.onStatusChanged, showToast, t, tProtocols]
  );

  // Scroll-Spy: aktiver Abschnitt = letzter, dessen Oberkante die Chipleiste passiert hat.
  useEffect(() => {
    function onScroll() {
      const threshold = 150;
      let active = 0;
      sectionRefs.current.forEach((element, index) => {
        if (element && element.getBoundingClientRect().top <= threshold) active = index;
      });
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) active = sections.length - 1;
      setActiveSection((current) => (current === active ? current : active));
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [sections.length]);

  useEffect(() => {
    chipRefs.current[activeSection]?.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
  }, [activeSection]);

  async function setTodoDone(blockId: string | null, todo: ProtocolTodo | TodoListItem, done: boolean) {
    const statusId = done ? TODO_STATUS.done : TODO_STATUS.open;
    const code = done ? "done" : "open";
    setSaveState("saving");
    try {
      const updated = await browserApiFetch<ProtocolTodo>(`/api/protocol-todos/${todo.id}`, { method: "PATCH", body: JSON.stringify({ todo_status_id: statusId }) });
      if (blockId) {
        const next = (todosByBlock[blockId] ?? []).map((item) => (item.id === todo.id ? { ...item, ...updated, todo_status_code: updated?.todo_status_code ?? code } : item));
        setTodosByBlock((current) => ({ ...current, [blockId]: next }));
        collab.sendFieldUpdate(`block-${blockId}-todos`, next);
      } else {
        setPendingTodos((current) => current.map((item) => (item.id === todo.id ? { ...item, todo_status_id: statusId, todo_status_code: code } : item)));
      }
      markSaved();
    } catch (error) {
      setSaveState("error");
      showToast(error instanceof Error ? error.message : tProtocols("editor.todoSaveFailed"), "error");
    }
  }

  async function uploadPhoto(blockId: string, file: File) {
    setSheet(null);
    setSaveState("saving");
    try {
      const body = new FormData();
      body.append("file", file);
      const created = await browserApiFetch<ProtocolImage>(`/api/protocol-element-blocks/${blockId}/images`, { method: "POST", body });
      const next = [...(imagesByBlock[blockId] ?? []), created].sort((a, b) => a.sort_index - b.sort_index);
      setImagesByBlock((current) => ({ ...current, [blockId]: next }));
      collab.sendFieldUpdate(`block-${blockId}-images`, next);
      markSaved();
      showToast(created.duplicate_warning || t("editor.photoAdded"), created.duplicate_warning ? "info" : "success");
    } catch (error) {
      setSaveState("error");
      showToast(error instanceof Error ? error.message : tProtocols("editor.imageUploadFailed"), "error");
    }
  }

  const nextStatus = STATUS_FLOW[STATUS_FLOW.indexOf(status as (typeof STATUS_FLOW)[number]) + 1] ?? null;
  const ctaLabel =
    status === "geplant"
      ? tProtocols("editor.workflowFinishPreparation")
      : status === "vorbereitet"
        ? tProtocols("editor.workflowFinishSession")
        : status === "durchgeführt"
          ? tProtocols("editor.workflowFinishProtocol")
          : null;
  const canAdvance = !forceReadOnly && !!nextStatus && !!ctaLabel;

  async function advanceStatus() {
    if (!nextStatus) return;
    if (collab.hasOtherActiveEditors && !(await confirm({ message: t("editor.othersEditingConfirm"), confirmLabel: ctaLabel ?? "" }))) return;
    try {
      await browserApiFetch(`/api/protocols/${protocol.id}`, { method: "PATCH", body: JSON.stringify({ status: nextStatus }) });
      setStatus(nextStatus);
      collab.sendStatusChanged(nextStatus);
      showToast(t("editor.statusAdvanced", { status: protocolStatusLabel(nextStatus, tProtocols) }), "success");
      setSheet(null);
      router.refresh();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("editor.statusFailed"), "error");
    }
  }

  const presenceNames = collab.otherPresence.map((entry) => entry.display_name);
  const editingText = sheet?.kind === "text" ? allBlocks.find((block) => block.id === sheet.blockId) ?? null : null;
  const attendanceSheetBlock = sheet?.kind === "attendance" ? allBlocks.find((block) => block.id === sheet.blockId) ?? null : null;

  return (
    <div className="mobile-editor">
      <header className="mobile-editor-topbar">
        <button type="button" className="mobile-editor-back" onClick={() => (window.history.length > 1 ? router.back() : router.push("/" as Route))}>
          <MobileIcon name="chevronLeft" size={22} strokeWidth={2.2} />
          {t("editor.back")}
        </button>
        <div className="mobile-editor-topbar-center">
          <span className="mobile-editor-number">{protocol.protocol_number}</span>
          <span className={`mobile-editor-status mobile-editor-status-${STATUS_FLOW.indexOf(status as (typeof STATUS_FLOW)[number])}`}>
            {protocolStatusLabel(status, tProtocols)}
          </span>
        </div>
        <div className="mobile-editor-topbar-end">
          <ActionMenu
            ariaLabel={t("editor.more")}
            items={[
              { label: t("editor.exportPdf"), onClick: () => void openOrGeneratePdf(protocol) },
              { label: t("editor.statusTitle"), onClick: () => setSheet({ kind: "status" }) },
            ]}
          />
        </div>
      </header>

      <div className="mobile-editor-head">
        <h1 className="mobile-editor-title">{protocol.title || protocol.protocol_number}</h1>
        {protocol.protocol_date ? <div className="mobile-muted-sm">{dateParts.long(protocol.protocol_date, locale)}</div> : null}
        {presenceNames.length > 0 || saveState !== "idle" ? (
        <div className="mobile-editor-presence">
          <span className="mobile-inline-person">
            {presenceNames.length > 0 ? (
              <>
                <span className="mobile-avatar-stack">
                  {session?.user?.display_name ? <MobileAvatar name={session.user.display_name} size="xs" /> : null}
                  {presenceNames.slice(0, 2).map((name) => (
                    <MobileAvatar key={name} name={name} size="xs" />
                  ))}
                </span>
                <span className="mobile-muted-sm">{t("editor.coEditing", { name: presenceNames[0], count: presenceNames.length })}</span>
              </>
            ) : null}
          </span>
          {saveState !== "idle" ? (
            <span className={`mobile-editor-save mobile-editor-save-${saveState}`}>
              {saveState === "saved" ? <MobileIcon name="check" size={14} strokeWidth={2.4} /> : null}
              {saveState === "saving" ? t("editor.saving") : saveState === "saved" ? t("editor.saved") : t("editor.saveError")}
            </span>
          ) : null}
        </div>
        ) : null}
        {isReadOnly ? <p className="mobile-editor-readonly">{forceReadOnly ? t("editor.readOnlyRole") : t("editor.readOnlyDone")}</p> : null}
      </div>

      {sections.length > 0 ? (
        <nav className="mobile-editor-strip" aria-label={t("editor.sections")}>
          {sections.map((section, index) => (
            <button
              key={section.element.id}
              ref={(node) => {
                chipRefs.current[index] = node;
              }}
              type="button"
              className={`mobile-editor-chip${activeSection === index ? " mobile-editor-chip-active" : ""}`}
              aria-current={activeSection === index ? "true" : undefined}
              onClick={() => sectionRefs.current[index]?.scrollIntoView({ behavior: "smooth", block: "start" })}
            >
              <span className="mobile-editor-chip-num">{index + 1}</span>
              {trimSectionName(section.element.section_name_snapshot)}
            </button>
          ))}
        </nav>
      ) : null}

      {sections.map((section, index) => {
        const sectionName = trimSectionName(section.element.section_name_snapshot);
        return (
          <section
            key={section.element.id}
            ref={(node) => {
              sectionRefs.current[index] = node;
            }}
            className="mobile-editor-section"
          >
            <div className="mobile-editor-section-title">
              {index + 1}. {sectionName}
            </div>
            {section.blocks.map((block) => (
              <MobileBlock
                key={block.id}
                block={block}
                editable={blockEditable(block)}
                lockedBy={collab.isLockedByOther(`block-${block.id}`)?.display_name ?? null}
                todos={todosByBlock[block.id] ?? []}
                images={imagesByBlock[block.id] ?? []}
                participants={availableParticipants}
                protocol={{ ...protocol, status }}
                accounts={availableAccounts}
                transactions={initialFinanceTransactions}
                onEditText={() => setSheet({ kind: "text", blockId: block.id, sectionName })}
                onOpenAttendance={() => setSheet({ kind: "attendance", blockId: block.id })}
                onToggleTodo={(todo, done) => void setTodoDone(block.id, todo, done)}
                onAddTodo={() => setSheet({ kind: "todos", blockId: block.id, sectionName })}
                onAddPhoto={() => setSheet({ kind: "photo", blockId: block.id })}
              />
            ))}
          </section>
        );
      })}
      {sections.length === 0 ? <div className="mobile-editor-empty">{t("editor.emptyProtocol")}</div> : null}

      <div className="mobile-editor-end">
        <span className="mobile-muted-sm">{t("editor.endOfProtocol")}</span>
        {canAdvance ? (
          <button type="button" className="button-secondary mobile-button-block" onClick={() => setSheet({ kind: "status" })}>
            {ctaLabel}
          </button>
        ) : null}
      </div>

      <nav className="mobile-editor-bottombar" aria-label={t("editor.tools")}>
        <button type="button" className="mobile-editor-tool" onClick={() => setSheet({ kind: "notes" })}>
          <MobileIcon name="document" size={23} strokeWidth={1.9} />
          <span>{t("editor.notes")}</span>
        </button>
        <button
          type="button"
          className="mobile-editor-tool"
          onClick={() => setSheet({ kind: "todos", blockId: null, sectionName: trimSectionName(sections[activeSection]?.element.section_name_snapshot ?? "") })}
        >
          <span className="mobile-tab-icon">
            <MobileIcon name="todos" size={23} strokeWidth={1.9} />
            {openTodoCount > 0 ? <span className="mobile-tab-badge mobile-tab-badge-neutral">{openTodoCount}</span> : null}
          </span>
          <span>{t("tabs.todos")}</span>
        </button>
        <button
          type="button"
          className="mobile-editor-tool"
          disabled={!attendanceBlock}
          onClick={() => attendanceBlock && setSheet({ kind: "attendance", blockId: attendanceBlock.id })}
        >
          <MobileIcon name="people" size={23} strokeWidth={1.9} />
          <span>{tProtocols("blockTypeAttendance")}</span>
        </button>
        <button type="button" className="mobile-editor-tool" onClick={() => setSheet({ kind: "status" })}>
          <MobileIcon name="check" size={23} strokeWidth={1.9} />
          <span>{t("editor.status")}</span>
        </button>
      </nav>

      {sheet?.kind === "text" && editingText ? (
        <TextSheet
          block={editingText}
          sectionName={sheet.sectionName}
          editable={blockEditable(editingText)}
          trackChangesActive={trackChangesActive}
          collab={collab}
          onClose={() => setSheet(null)}
          onSaving={() => setSaveState("saving")}
          onSaved={(patch) => {
            updateBlock(editingText.id, (block) => ({ ...block, ...patch }));
            markSaved();
          }}
          onError={() => setSaveState("error")}
        />
      ) : null}
      {sheet?.kind === "attendance" && attendanceSheetBlock ? (
        <AttendanceSheet
          block={attendanceSheetBlock}
          protocol={{ ...protocol, status }}
          participants={availableParticipants}
          editable={blockEditable(attendanceSheetBlock)}
          fines={fines}
          setFines={setFines}
          collab={collab}
          onBlockChange={(config) => updateBlock(attendanceSheetBlock.id, (block) => ({ ...block, configuration_snapshot_json: config }))}
          onSaving={() => setSaveState("saving")}
          onSaved={markSaved}
          onClose={() => setSheet(null)}
        />
      ) : null}
      {sheet?.kind === "notes" ? (
        <NotesSheet
          protocolId={protocol.id}
          value={sessionNotes}
          editable={!forceReadOnly}
          onSaved={setSessionNotes}
          onClose={() => setSheet(null)}
        />
      ) : null}
      {sheet?.kind === "todos" ? (
        <TodosSheet
          protocolId={protocol.id}
          targetBlockId={sheet.blockId}
          sectionName={sheet.sectionName}
          editable={!isReadOnly}
          todos={protocolTodos}
          pendingTodos={pendingTodos}
          todoBlockOf={(todoId) => todoBlockIds.find((id) => (todosByBlock[id] ?? []).some((todo) => todo.id === todoId)) ?? null}
          onToggle={(blockId, todo, done) => void setTodoDone(blockId, todo, done)}
          onCreated={async (blockId) => {
            const [fresh, freshElements] = await Promise.all([
              browserApiFetch<ProtocolTodo[]>(`/api/protocol-element-blocks/${blockId}/todos`),
              todoBlockIds.includes(blockId) ? Promise.resolve(null) : browserApiFetch<ProtocolElement[]>(`/api/protocols/${protocol.id}/elements`),
            ]);
            if (freshElements) setElements(freshElements);
            setTodosByBlock((current) => ({ ...current, [blockId]: fresh ?? [] }));
            collab.sendFieldUpdate(`block-${blockId}-todos`, fresh ?? []);
            markSaved();
          }}
          onClose={() => setSheet(null)}
        />
      ) : null}
      {sheet?.kind === "status" ? (
        <Modal open size="sheet" title={t("editor.statusTitle")} onClose={() => setSheet(null)} className="mobile-sheet"
          footer={
            <div className="mobile-sheet-footer mobile-sheet-footer-stack">
              {canAdvance ? (
                <button type="button" className="button-primary mobile-button-block" onClick={() => void advanceStatus()}>
                  {ctaLabel}
                </button>
              ) : null}
              <button type="button" className="button-secondary mobile-button-block" disabled={!!busyByProtocol[protocol.id]} onClick={() => void openOrGeneratePdf(protocol)}>
                {t("editor.exportPdf")}
              </button>
            </div>
          }
        >
          <div className="grid mobile-sheet-body">
            <ol className="mobile-status-steps">
              {STATUS_FLOW.map((step, index) => {
                const current = STATUS_FLOW.indexOf(status as (typeof STATUS_FLOW)[number]);
                const state = index < current ? "done" : index === current ? "current" : "todo";
                return (
                  <li key={step} className={`mobile-status-step mobile-status-step-${state}`}>
                    <span className="mobile-status-step-dot">{state === "done" ? <MobileIcon name="check" size={14} strokeWidth={3} /> : index + 1}</span>
                    <span className="mobile-status-step-label">{protocolStatusLabel(step, tProtocols)}</span>
                  </li>
                );
              })}
            </ol>
            <div className="mobile-field-block">
              <div className="mobile-eyebrow">{t("editor.activeNow")}</div>
              {[session?.user?.display_name ?? null, ...presenceNames].filter((name): name is string => !!name).map((name, index) => (
                <span key={`${name}-${index}`} className="mobile-inline-person">
                  <MobileAvatar name={name} size="sm" />
                  {index === 0 ? t("editor.you", { name }) : name}
                </span>
              ))}
            </div>
          </div>
        </Modal>
      ) : null}
      {sheet?.kind === "photo" ? <PhotoSheet onPick={(file) => void uploadPhoto(sheet.blockId, file)} onClose={() => setSheet(null)} /> : null}
    </div>
  );
}

function MobileBlock({
  block,
  editable,
  lockedBy,
  todos,
  images,
  participants,
  protocol,
  accounts,
  transactions,
  onEditText,
  onOpenAttendance,
  onToggleTodo,
  onAddTodo,
  onAddPhoto,
}: {
  block: ProtocolElementBlock;
  editable: boolean;
  lockedBy: string | null;
  todos: ProtocolTodo[];
  images: ProtocolImage[];
  participants: ParticipantSummary[];
  protocol: ProtocolSummary;
  accounts: FinanceAccount[];
  transactions: Record<string, FinanceTransaction[]>;
  onEditText: () => void;
  onOpenAttendance: () => void;
  onToggleTodo: (todo: ProtocolTodo, done: boolean) => void;
  onAddTodo: () => void;
  onAddPhoto: () => void;
}) {
  const t = useTranslations("mobile");
  const tProtocols = useTranslations("protocols");
  const locale = useLocale();
  const type = block.element_type_code ?? "unknown";
  const typeLabels: Record<string, string> = {
    text: tProtocols("blockTypeText"), static_text: tProtocols("blockTypeText"), todo: tProtocols("blockTypeTodo"), image: tProtocols("blockTypeImage"),
    attendance: tProtocols("blockTypeAttendance"), finance_balance: tProtocols("blockTypeFinanceBalance"),
    finance_transactions: tProtocols("blockTypeFinanceTransactions"), chart: tProtocols("blockTypeChart"),
    session_date: tProtocols("blockTypeSessionDate"), matrix: tProtocols("blockTypeMatrix"), form: tProtocols("blockTypeForm"),
    bullet_list: tProtocols("blockTypeBulletList"), event_list: tProtocols("eventsLabel"), fine_list: tProtocols("blockTypeFineList"),
    entry_exit: tProtocols("blockTypeEntryExit"), session_notes: tProtocols("blockTypeSessionNotes"), display: tProtocols("blockTypeDisplay"),
  };
  const title = visibleBlockTitle(block);
  const label = (
    <div className="mobile-block-label">
      <span>{title && title !== typeLabels[type] ? `${typeLabels[type] ?? type} · ${title}` : typeLabels[type] ?? title ?? type}</span>
      {lockedBy ? <span className="mobile-block-lock">{t("editor.lockedBy", { name: lockedBy })}</span> : null}
    </div>
  );

  if (!MOBILE_BLOCK_TYPES.has(type)) {
    return (
      <div className="mobile-block">
        {label}
        <div className="mobile-block-desktop">{t("editor.desktopOnlyBlock")}</div>
      </div>
    );
  }

  if (type === "text" || type === "static_text") {
    const content = type === "static_text" ? block.display_compiled_text ?? block.text_content ?? "" : block.text_content ?? "";
    const canEdit = type === "text" && editable;
    return (
      <div className="mobile-block">
        {label}
        <div
          className={`mobile-block-text${canEdit ? " mobile-block-text-editable" : ""}`}
          role={canEdit ? "button" : undefined}
          tabIndex={canEdit ? 0 : undefined}
          onClick={canEdit ? onEditText : undefined}
          onKeyDown={canEdit ? (event) => (event.key === "Enter" || event.key === " ") && (event.preventDefault(), onEditText()) : undefined}
        >
          {content.trim() ? <RichTextEditor value={content} onChange={() => {}} readOnly /> : <span className="mobile-muted">{canEdit ? t("editor.tapToWrite") : "—"}</span>}
        </div>
      </div>
    );
  }

  if (type === "attendance") {
    const entries = attendanceEntries(block);
    const roster = protocolAttendanceParticipants(participants, entries, protocol);
    const tally = tallyAttendance(roster, entries);
    const namesFor = (status: string) =>
      roster.filter((participant) => entries.some((entry) => String(entry.participant_id) === participant.id && entry.status === status)).map((participant) => participant.display_name);
    const excusedNames = namesFor("excused");
    const absentNames = namesFor("absent");
    return (
      <div className="mobile-block">
        {label}
        <button type="button" className="mobile-attendance-card" onClick={onOpenAttendance}>
          <span className="mobile-attendance-tally">
            <span className="mobile-attendance-stat mobile-attendance-stat-present"><strong>{tally.present + tally.late}</strong>{t("editor.attPresent")}</span>
            <span className="mobile-attendance-stat mobile-attendance-stat-excused"><strong>{tally.excused}</strong>{t("editor.attExcused")}</span>
            <span className="mobile-attendance-stat mobile-attendance-stat-absent"><strong>{tally.absent}</strong>{t("editor.attAbsent")}</span>
          </span>
          <span className="mobile-attendance-names">
            <span><span className="mobile-muted">{tProtocols("attendance.excused")}: </span>{excusedNames.join(", ") || "—"}</span>
            <span><span className="mobile-muted">{tProtocols("attendance.absent")}: </span>{absentNames.join(", ") || "—"}</span>
          </span>
          <span className="mobile-attendance-action">
            {editable ? t("editor.recordAttendance") : t("editor.showAttendance")}
            <MobileIcon name="chevronRight" size={16} strokeWidth={2.2} />
          </span>
        </button>
      </div>
    );
  }

  if (type === "todo") {
    return (
      <div className="mobile-block">
        {label}
        <div className="mobile-block-todos">
          {todos.map((todo) => {
            const done = todo.todo_status_code === "done" || todo.todo_status_code === "cancelled";
            return (
              <div key={todo.id} className="mobile-todo-row">
                <MobileCheck checked={done} square disabled={!editable} label={t("todos.toggleDone")} onToggle={() => onToggleTodo(todo, !done)} />
                <div className="mobile-todo-row-main">
                  <span className={`mobile-todo-row-title${done ? " mobile-todo-row-title-done" : ""}`}>{todo.task}</span>
                  <span className="mobile-todo-row-meta">{todo.assigned_participant_name || t("editor.unassigned")}</span>
                </div>
              </div>
            );
          })}
          {editable ? (
            <button type="button" className="mobile-block-add" onClick={onAddTodo}>
              <MobileIcon name="plus" size={20} strokeWidth={2.4} />
              {t("editor.addTodo")}
            </button>
          ) : todos.length === 0 ? (
            <div className="mobile-muted-sm mobile-block-todos-empty">—</div>
          ) : null}
        </div>
      </div>
    );
  }

  if (type === "image") {
    return (
      <div className="mobile-block">
        {label}
        <div className="mobile-photo-grid">
          {images.map((image) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img key={image.id} className="mobile-photo" src={image.content_url} alt={image.caption || image.title || image.original_name} loading="lazy" />
          ))}
          {editable ? (
            <button type="button" className="mobile-photo-add" onClick={onAddPhoto}>
              <MobileIcon name="plus" size={24} strokeWidth={2} />
              {t("editor.addPhoto")}
            </button>
          ) : null}
        </div>
      </div>
    );
  }

  if (type === "finance_balance" || type === "finance_transactions") {
    const config = blockConfig(block);
    const storedId = config.finance_account_id ? String(config.finance_account_id) : null;
    const accountId = storedId ? block.public_reference_ids?.finance_accounts?.[storedId] ?? storedId : null;
    const account = accountId ? accounts.find((item) => item.id === accountId) ?? null : null;
    if (!account) {
      return (
        <div className="mobile-block">
          {label}
          <div className="mobile-muted-sm">{tProtocols("noAccountSelected")}</div>
        </div>
      );
    }
    if (type === "finance_balance") {
      return (
        <div className="mobile-block">
          {label}
          <div className="mobile-finance-balance">
            <div className="mobile-eyebrow">{account.name}</div>
            <div className={`mobile-finance-amount${account.balance < 0 ? " mobile-text-danger" : ""}`}>{formatFinanceAmount(account.balance, account.currency_label)}</div>
          </div>
        </div>
      );
    }
    const list = (transactions[accountId!] ?? []).slice(0, Number(config.finance_last_n ?? 10) || 10);
    return (
      <div className="mobile-block">
        {label}
        {list.length === 0 ? <div className="mobile-muted-sm">{tProtocols("noTransactionsInRange")}</div> : null}
        <div className="mobile-finance-list">
          {list.map((tx) => (
            <div key={tx.id} className="mobile-finance-row">
              <span className="mobile-finance-row-text">
                {tx.description}
                <small>{dateParts.dayMonth(tx.transaction_date, locale)}</small>
              </span>
              <span className={tx.amount < 0 ? "mobile-text-danger" : "mobile-finance-positive"}>
                {tx.amount > 0 ? "+ " : ""}
                {formatFinanceAmount(tx.amount, account.currency_label)}
              </span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (type === "chart") {
    return (
      <div className="mobile-block">
        {label}
        <div className="mobile-chart">
          <ChartBlockRenderer config={blockConfig(block) as { chart_type?: string; cycle_key?: string }} editable={false} onSave={() => {}} />
        </div>
      </div>
    );
  }

  // session_date: Datum der naechsten Sitzung (Anzeige)
  const nextDate = String(blockConfig(block).selected_date ?? "");
  return (
    <div className="mobile-block">
      {label}
      <div className="mobile-block-plain">{nextDate ? dateParts.long(nextDate, locale) : "—"}</div>
    </div>
  );
}

type Collab = ReturnType<typeof useProtocolCollaboration>;

function TextSheet({
  block,
  sectionName,
  editable,
  trackChangesActive,
  collab,
  onClose,
  onSaving,
  onSaved,
  onError,
}: {
  block: ProtocolElementBlock;
  sectionName: string;
  editable: boolean;
  trackChangesActive: boolean;
  collab: Collab;
  onClose: () => void;
  onSaving: () => void;
  onSaved: (patch: Partial<ProtocolElementBlock>) => void;
  onError: () => void;
}) {
  const t = useTranslations("mobile");
  const tProtocols = useTranslations("protocols");
  const showToast = useToast();
  const [draft, setDraft] = useState(block.text_content ?? "");
  const [saving, setSaving] = useState(false);
  const baseline = useRef(block.text_content ?? "");
  const fieldKey = `block-${block.id}`;

  // Sperre waehrend des Bearbeitens, damit andere den Block solange nur lesen (wie Desktop).
  useEffect(() => {
    if (!editable) return;
    collab.lockField(fieldKey);
    return () => collab.unlockField(fieldKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fieldKey, editable]);

  async function save() {
    if (!editable || draft === baseline.current) {
      onClose();
      return;
    }
    setSaving(true);
    onSaving();
    try {
      const result = await browserApiFetch<{ tracked_dirty: boolean; tracked_baseline_content: string | null }>(`/api/protocol-element-blocks/${block.id}/text`, {
        method: "PUT",
        body: JSON.stringify({ content: draft, expected_content: baseline.current }),
      });
      const patch = { text_content: draft, tracked_dirty: result.tracked_dirty, tracked_baseline_content: result.tracked_baseline_content };
      onSaved(patch);
      collab.sendFieldUpdate(fieldKey, patch);
      onClose();
    } catch (error) {
      onError();
      if (error instanceof ApiError && error.kind === "conflict") {
        showToast(t("editor.textConflict"), "error");
      } else {
        showToast(error instanceof Error ? error.message : tProtocols("editor.textSaveFailed"), "error");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open
      size="sheet"
      title={t("editor.textTitle", { section: sectionName })}
      onClose={onClose}
      className="mobile-sheet mobile-sheet-tall"
      footer={
        <div className="modal-actions mobile-sheet-footer">
          <button type="button" className="button-ghost" onClick={onClose}>
            {t("common.cancel")}
          </button>
          {editable ? (
            <button type="button" className="button-primary" data-modal-save disabled={saving} onClick={() => void save()}>
              {t("editor.done")}
            </button>
          ) : null}
        </div>
      }
    >
      <div className="mobile-text-editor">
        <RichTextEditor
          value={draft}
          onChange={setDraft}
          readOnly={!editable}
          placeholder={tProtocols("textPlaceholderMarkdownHint")}
          trackedBaseline={trackChangesActive && block.tracked_dirty ? block.tracked_baseline_content : undefined}
        />
      </div>
    </Modal>
  );
}

function AttendanceSheet({
  block,
  protocol,
  participants,
  editable,
  fines,
  setFines,
  collab,
  onBlockChange,
  onSaving,
  onSaved,
  onClose,
}: {
  block: ProtocolElementBlock;
  protocol: ProtocolSummary;
  participants: ParticipantSummary[];
  editable: boolean;
  fines: AttendanceFine[];
  setFines: React.Dispatch<React.SetStateAction<AttendanceFine[]>>;
  collab: Collab;
  onBlockChange: (config: Record<string, unknown>) => void;
  onSaving: () => void;
  onSaved: () => void;
  onClose: () => void;
}) {
  const t = useTranslations("mobile");
  const tProtocols = useTranslations("protocols");
  const showToast = useToast();
  const entries = attendanceEntries(block);
  const roster = protocolAttendanceParticipants(participants, entries, protocol);
  const tally = tallyAttendance(roster, entries);
  const fineConfig = attendanceFineConfig(blockConfig(block));
  const fieldKey = `block-${block.id}`;
  const shortLabels: Record<AttendanceStatus, string> = {
    present: t("editor.attShortPresent"),
    late: t("editor.attShortLate"),
    excused: t("editor.attShortExcused"),
    absent: t("editor.attShortAbsent"),
  };

  async function setAttendance(participant: ParticipantSummary, status: AttendanceStatus) {
    const previousEntries = attendanceEntries(block);
    const previousStatus = previousEntries.find((entry) => String(entry.participant_id) === participant.id)?.status ?? null;
    if (previousStatus === status) return;
    onBlockChange({
      ...blockConfig(block),
      attendance_entries: [
        ...previousEntries.filter((entry) => String(entry.participant_id) !== participant.id),
        { participant_id: participant.id, participant_name: participant.display_name, status },
      ],
    });
    onSaving();
    collab.lockField(fieldKey);
    try {
      const updated = await browserApiFetch<ProtocolElementBlock>(`/api/protocol-element-blocks/${block.id}/attendance/${participant.id}`, {
        method: "POST",
        body: JSON.stringify({ status }),
      });
      onBlockChange(updated.configuration_snapshot_json);
      collab.sendFieldUpdate(fieldKey, { configuration_snapshot_json: updated.configuration_snapshot_json });
      await syncAttendanceFine({
        protocolId: protocol.id,
        participant,
        status,
        config: fineConfig,
        fines,
        onRemoved: (fineId) => setFines((current) => current.filter((fine) => fine.id !== fineId)),
        onCreated: (created) => setFines((current) => [...current.filter((fine) => !(fine.participant_id === participant.id && fine.status === "pending")), created]),
      });
      onSaved();
    } catch (error) {
      onBlockChange({ ...blockConfig(block), attendance_entries: previousEntries });
      showToast(error instanceof Error ? t("editor.attendanceFailed", { message: error.message }) : t("editor.attendanceFailedGeneric"), "error");
    } finally {
      collab.unlockField(fieldKey);
    }
  }

  async function allPresent() {
    for (const participant of roster) {
      const current = entries.find((entry) => String(entry.participant_id) === participant.id)?.status;
      if (!current) await setAttendance(participant, "present");
    }
  }

  return (
    <Modal
      open
      size="sheet"
      title={tProtocols("blockTypeAttendance")}
      description={t("editor.attSummary", { present: tally.present + tally.late, excused: tally.excused, absent: tally.absent })}
      onClose={onClose}
      className="mobile-sheet mobile-sheet-tall"
    >
      {editable ? (
        <div className="mobile-tag-wrap">
          <MobileChip active={false} onClick={() => void allPresent()}>
            {t("editor.attRestPresent")}
          </MobileChip>
        </div>
      ) : null}
      <div className="mobile-sheet-list">
        {roster.map((participant) => {
          const current = (entries.find((entry) => String(entry.participant_id) === participant.id)?.status as AttendanceStatus | undefined) ?? null;
          const fine = fineConfig.enabled ? fines.find((item) => item.participant_id === participant.id && item.status === "pending") : null;
          return (
            <div key={participant.id} className="mobile-attendance-row">
              <MobileAvatar name={participant.display_name} size="md" />
              <span className="mobile-attendance-row-text">
                <span className="mobile-ellipsis">{participant.display_name}</span>
                {fine ? <small className="mobile-text-danger">{t("editor.fineNote", { amount: fine.amount.toFixed(2) })}</small> : null}
              </span>
              <div className="mobile-attendance-options">
                <MobileSegmented<AttendanceStatus>
                  ariaLabel={participant.display_name}
                  value={(current ?? "") as AttendanceStatus}
                  onChange={(status) => editable && void setAttendance(participant, status)}
                  options={ATTENDANCE_STATUSES.map((status) => ({ value: status, label: shortLabels[status] }))}
                />
              </div>
            </div>
          );
        })}
      </div>
    </Modal>
  );
}

function NotesSheet({
  protocolId,
  value,
  editable,
  onSaved,
  onClose,
}: {
  protocolId: string;
  value: string;
  editable: boolean;
  onSaved: (value: string) => void;
  onClose: () => void;
}) {
  const t = useTranslations("mobile");
  const showToast = useToast();
  const [draft, setDraft] = useState(value);
  const [state, setState] = useState<"saved" | "saving" | "error">("saved");
  const serverValue = useRef(value);
  const timer = useRef<number | null>(null);

  const flush = useCallback(
    async (next: string) => {
      try {
        const updated = await browserApiFetch<ProtocolSummary>(`/api/protocols/${protocolId}`, {
          method: "PATCH",
          body: JSON.stringify({ session_notes: next, expected_session_notes: serverValue.current }),
        });
        serverValue.current = updated?.session_notes ?? next;
        onSaved(serverValue.current);
        setState("saved");
      } catch (error) {
        setState("error");
        showToast(error instanceof ApiError && error.kind === "conflict" ? t("editor.notesConflict") : error instanceof Error ? error.message : t("editor.saveError"), "error");
      }
    },
    [protocolId, onSaved, showToast, t]
  );

  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
    },
    []
  );

  function change(next: string) {
    setDraft(next);
    setState("saving");
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void flush(next), 800);
  }

  function close() {
    if (timer.current && state === "saving") {
      window.clearTimeout(timer.current);
      void flush(draft);
    }
    onClose();
  }

  return (
    <Modal
      open
      size="sheet"
      title={t("editor.notesTitle")}
      description={state === "saving" ? t("editor.saving") : state === "error" ? t("editor.saveError") : t("editor.autoSaved")}
      onClose={close}
      className="mobile-sheet"
    >
      <div className="grid mobile-sheet-body">
        <textarea
          className="mobile-notes-input"
          value={draft}
          readOnly={!editable}
          placeholder={t("editor.notesPlaceholder")}
          aria-label={t("editor.notesTitle")}
          onChange={(event) => change(event.target.value)}
        />
        <p className="mobile-hint-box">{t("editor.notesHint")}</p>
      </div>
    </Modal>
  );
}

function TodosSheet({
  protocolId,
  targetBlockId,
  sectionName,
  editable,
  todos,
  pendingTodos,
  todoBlockOf,
  onToggle,
  onCreated,
  onClose,
}: {
  protocolId: string;
  targetBlockId: string | null;
  sectionName: string;
  editable: boolean;
  todos: ProtocolTodo[];
  pendingTodos: TodoListItem[];
  todoBlockOf: (todoId: string) => string | null;
  onToggle: (blockId: string | null, todo: ProtocolTodo | TodoListItem, done: boolean) => void;
  onCreated: (blockId: string) => Promise<void>;
  onClose: () => void;
}) {
  const t = useTranslations("mobile");
  const tProtocols = useTranslations("protocols");
  const showToast = useToast();
  const session = useMobileSession();
  const [task, setTask] = useState("");
  const [assignToMe, setAssignToMe] = useState(false);
  const [creating, setCreating] = useState(false);
  const valid = task.trim().length > 0;
  const isDone = (todo: { todo_status_code: string | null }) => todo.todo_status_code === "done" || todo.todo_status_code === "cancelled";

  async function create() {
    if (!valid || creating) return;
    setCreating(true);
    try {
      let blockId: string;
      let todoId: string;
      if (targetBlockId) {
        const created = await browserApiFetch<ProtocolTodo>(`/api/protocol-element-blocks/${targetBlockId}/todos`, {
          method: "POST",
          body: JSON.stringify({ task: task.trim(), tags: [], todo_status_id: TODO_STATUS.open, created_by: null }),
        });
        blockId = targetBlockId;
        todoId = created.id;
      } else {
        const result = await browserApiFetch<{ block_id: string; todo_id: string }>(`/api/protocols/${protocolId}/quick-todos`, {
          method: "POST",
          body: JSON.stringify({ task: task.trim(), tag: sectionName || tProtocols("blockTypeSessionNotes") }),
        });
        blockId = result.block_id;
        todoId = result.todo_id;
      }
      if (assignToMe && session?.user?.id) {
        await browserApiFetch(`/api/protocol-todos/${todoId}`, { method: "PATCH", body: JSON.stringify({ assigned_user_id: session.user.id }) });
      }
      await onCreated(blockId);
      setTask("");
      showToast(t("editor.todoCreated"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : tProtocols("editor.todoCreateFailed"), "error");
    } finally {
      setCreating(false);
    }
  }

  return (
    <Modal open size="sheet" title={t("tabs.todos")} onClose={onClose} className="mobile-sheet mobile-sheet-tall">
      {editable ? (
        <div className="grid mobile-sheet-body">
          <input value={task} onChange={(event) => setTask(event.target.value)} placeholder={t("editor.newTodoPlaceholder")} aria-label={t("editor.newTodoPlaceholder")} />
          <div className="mobile-tag-wrap">
            <MobileChip
              active={assignToMe}
              onClick={() => setAssignToMe((value) => !value)}
              leading={session?.user?.display_name ? <MobileAvatar name={session.user.display_name} size="xs" /> : undefined}
            >
              {t("todos.assignToMe")}
            </MobileChip>
            {sectionName && !targetBlockId ? <span className="mobile-section-tag">{t("editor.sectionTag", { section: sectionName })}</span> : null}
          </div>
          <button type="button" className="button-primary mobile-button-block" disabled={!valid || creating} onClick={() => void create()}>
            {t("todos.create")}
          </button>
        </div>
      ) : null}
      <div className="mobile-picker-header">{t("editor.inThisProtocol")}</div>
      <div className="mobile-sheet-list">
        {todos.length === 0 ? <div className="mobile-card-empty">{t("dashboard.noTodos")}</div> : null}
        {todos.map((todo) => (
          <div key={todo.id} className="mobile-todo-row">
            <MobileCheck checked={isDone(todo)} square disabled={!editable} label={t("todos.toggleDone")} onToggle={() => onToggle(todoBlockOf(todo.id), todo, !isDone(todo))} />
            <div className="mobile-todo-row-main">
              <span className={`mobile-todo-row-title${isDone(todo) ? " mobile-todo-row-title-done" : ""}`}>{todo.task}</span>
              <span className="mobile-todo-row-meta">{todo.assigned_participant_name || t("editor.unassigned")}</span>
            </div>
          </div>
        ))}
      </div>
      {pendingTodos.length > 0 ? (
        <>
          <div className="mobile-picker-header">{t("editor.pendingFromEarlier")}</div>
          <div className="mobile-sheet-list">
            {pendingTodos.map((todo) => (
              <div key={todo.id} className="mobile-todo-row">
                <MobileCheck checked={isDone(todo)} disabled={!editable} label={t("todos.toggleDone")} onToggle={() => onToggle(null, todo, !isDone(todo))} />
                <div className="mobile-todo-row-main">
                  <span className={`mobile-todo-row-title${isDone(todo) ? " mobile-todo-row-title-done" : ""}`}>{todo.task}</span>
                  <span className="mobile-todo-row-meta">
                    {todo.resolved_due_label || todo.resolved_due_date || ""} {todo.protocol_number ?? ""}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </>
      ) : null}
    </Modal>
  );
}

function PhotoSheet({ onPick, onClose }: { onPick: (file: File) => void; onClose: () => void }) {
  const t = useTranslations("mobile");
  const cameraRef = useRef<HTMLInputElement>(null);
  const libraryRef = useRef<HTMLInputElement>(null);
  const pick = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) onPick(file);
  };
  return (
    <Modal open size="sheet" title={t("editor.addPhoto")} onClose={onClose} className="mobile-sheet">
      <div className="grid mobile-sheet-body">
        <input ref={cameraRef} type="file" accept="image/*" capture="environment" hidden onChange={pick} />
        <input ref={libraryRef} type="file" accept="image/*" hidden onChange={pick} />
        <button type="button" className="button-secondary mobile-button-block" onClick={() => cameraRef.current?.click()}>
          {t("editor.takePhoto")}
        </button>
        <button type="button" className="button-secondary mobile-button-block" onClick={() => libraryRef.current?.click()}>
          {t("editor.chooseFromLibrary")}
        </button>
      </div>
    </Modal>
  );
}
