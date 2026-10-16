"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { DataTable } from "@/components/ui/data-table";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { elementTypeLabels } from "@/lib/constants/element-types";
import { useTagConfig } from "@/lib/hooks/use-tag-config";
import type { CycleConfigSummary, ElementDefinition, ElementDefinitionBlock, EventSummary, ParticipantSummary, StructuredListDefinition, StructuredListEntry } from "@/types/api";

import { BlockEditor, SettingsSection, type BlockEditorData } from "./element-editor/block-editor";
import { blockFormFromBlock, blockPayload, changeElementType, newBlockForm, nextBlockId, type BlockForm } from "./element-editor/block-form";
import { RowDesigner } from "./element-editor/row-designer";
import { TypePickerModal } from "./element-editor/type-picker";

type ElementDefinitionManagerProps = {
  initialDefinitions: ElementDefinition[];
  knownEventTags: string[];
  availableParticipants?: ParticipantSummary[];
  availableEvents?: EventSummary[];
  availableLists?: StructuredListDefinition[];
  availableAccounts?: { id: string; name: string; currency_label: string }[];
  tenantId: string | null;
  autoOpenCreate?: boolean;
};

/** Offener Block-Dialog: neues Element, neuer Block in einem Element oder bestehender Block. */
type BlockSession =
  | { mode: "create"; newElement: boolean; elementTitle: string; form: BlockForm }
  | { mode: "edit"; blockId: number; form: BlockForm };

function sortedBlocks(blocks: ElementDefinitionBlock[]) {
  return [...blocks].sort((left, right) => left.sort_index - right.sort_index);
}

function resequence(blocks: ElementDefinitionBlock[]) {
  return blocks.map((block, index) => ({ ...block, sort_index: (index + 1) * 10, render_order: (index + 1) * 10 }));
}

export function ElementDefinitionManager({
  initialDefinitions,
  knownEventTags,
  availableParticipants,
  availableEvents,
  availableLists,
  availableAccounts = [],
  tenantId,
  autoOpenCreate = false,
}: ElementDefinitionManagerProps) {
  const t = useTranslations("templates.elementEditor");
  const tTypes = useTranslations("templates");
  const typeLabels = elementTypeLabels(tTypes);
  const { tagConfig } = useTagConfig();
  const showToast = useToast();
  const confirm = useConfirm();
  const [definitions, setDefinitions] = useState(initialDefinitions);
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [definitionTitle, setDefinitionTitle] = useState("");
  const [session, setSession] = useState<BlockSession | null>(null);
  const [showHelp, setShowHelp] = useState(false);
  const [typePickerOpen, setTypePickerOpen] = useState(false);
  const [designer, setDesigner] = useState<{ kind: "form" | "matrix"; rowId?: string } | null>(null);
  const [duplicatingId, setDuplicatingId] = useState<string | null>(null);
  const [draggedBlockId, setDraggedBlockId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [cycleConfigs, setCycleConfigs] = useState<CycleConfigSummary[]>([]);
  const [listEntries, setListEntries] = useState<Record<string, StructuredListEntry[]>>({});

  const selected = useMemo(() => definitions.find((definition) => definition.id === selectedId) ?? null, [definitions, selectedId]);
  const filteredDefinitions = useMemo(
    () => definitions.filter((definition) => !search || `${definition.title} ${definition.description ?? ""}`.toLowerCase().includes(search.toLowerCase())),
    [definitions, search]
  );

  // Zyklen erst laden, wenn ein Block-Dialog offen ist (Terminfilter, Matrix-Automodus).
  const sessionOpen = Boolean(session);
  useEffect(() => {
    if (!sessionOpen || cycleConfigs.length) return;
    let cancelled = false;
    browserApiFetch<CycleConfigSummary[]>("/api/cycle-configs")
      .then((rows) => { if (!cancelled) setCycleConfigs(rows ?? []); })
      .catch(() => { if (!cancelled) setCycleConfigs([]); });
    return () => { cancelled = true; };
  }, [sessionOpen, cycleConfigs.length]);

  // Sprung aus der Vorlagenbearbeitung direkt in die Neuanlage eines Elements.
  useEffect(() => {
    if (autoOpenCreate) startNewElement();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoOpenCreate]);

  // Einträge der Listen laden, auf die «Zeile aus Liste» schon verweist (Auswahl beim Öffnen).
  const referencedListIds = [...new Set(
    ((session?.form.config.rows ?? []) as Array<{ row_type: string; row_config: Record<string, unknown> }>)
      .filter((row) => row.row_type === "list_entry" && typeof row.row_config.linked_list_id === "string")
      .map((row) => row.row_config.linked_list_id as string)
  )].sort().join(",");
  useEffect(() => {
    for (const listId of referencedListIds.split(",").filter(Boolean)) ensureListEntries(listId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [referencedListIds]);

  function ensureListEntries(listId: string) {
    if (!listId || listEntries[listId]) return;
    browserApiFetch<StructuredListEntry[]>(`/api/lists/${listId}/entries`)
      .then((entries) => setListEntries((current) => ({ ...current, [listId]: entries ?? [] })))
      .catch((error) => showToast(error instanceof Error ? error.message : t("toast.listEntriesFailed"), "error"));
  }

  const data: BlockEditorData = {
    participants: availableParticipants ?? [],
    events: availableEvents ?? [],
    lists: availableLists ?? [],
    listEntries,
    ensureListEntries,
    knownEventTags,
    tagConfig,
    accounts: availableAccounts,
    cycleConfigs,
  };

  function replaceDefinition(updated: ElementDefinition) {
    setDefinitions((current) => current.map((definition) => (definition.id === updated.id ? updated : definition)));
  }

  function openDefinition(definition: ElementDefinition) {
    setSelectedId(definition.id);
    setDefinitionTitle(definition.title);
  }

  function startNewElement() {
    setSession({ mode: "create", newElement: true, elementTitle: "", form: newBlockForm(1, 1, 10) });
    setTypePickerOpen(true);
  }

  function startNewBlock() {
    if (!selected) return;
    setSession({ mode: "create", newElement: false, elementTitle: selected.title, form: newBlockForm(1, nextBlockId(selected.blocks), (selected.blocks.length + 1) * 10) });
    setTypePickerOpen(true);
  }

  function startEditBlock(block: ElementDefinitionBlock) {
    setSession({ mode: "edit", blockId: block.id, form: blockFormFromBlock(block) });
  }

  function closeSession() {
    setSession(null);
    setShowHelp(false);
    setTypePickerOpen(false);
    setDesigner(null);
  }

  async function saveBlocks(definition: ElementDefinition, blocks: ElementDefinitionBlock[], message: string) {
    try {
      const updated = await browserApiFetch<ElementDefinition>(`/api/element-definitions/${definition.id}`, {
        method: "PATCH",
        body: JSON.stringify({ blocks: resequence(blocks) }),
      });
      replaceDefinition(updated);
      showToast(message, "success");
      return updated;
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.blockSaveFailed"), "error");
      return null;
    }
  }

  async function persistSession(current: BlockSession): Promise<boolean> {
    const payload = blockPayload(current.form);
    if (current.mode === "create" && current.newElement) {
      try {
        const created = await browserApiFetch<ElementDefinition>("/api/element-definitions", {
          method: "POST",
          body: JSON.stringify({
            tenant_id: tenantId,
            title: current.elementTitle,
            description: null,
            is_active: true,
            blocks: [{ ...payload, sort_index: 10, render_order: 10 }],
          }),
        });
        setDefinitions((list) => [created, ...list]);
        openDefinition(created);
        showToast(t("toast.elementCreated", { title: created.title }), "success");
        return true;
      } catch (error) {
        showToast(error instanceof Error ? error.message : t("toast.elementCreateFailed"), "error");
        return false;
      }
    }
    if (!selected) return false;
    const blocks = sortedBlocks(selected.blocks);
    const next = current.mode === "create"
      ? [...blocks, payload]
      : blocks.map((block) => (block.id === current.blockId ? payload : block));
    const updated = await saveBlocks(selected, next, current.mode === "create" ? t("toast.blockAdded") : t("toast.blockSaved"));
    return Boolean(updated);
  }

  async function submitSession(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || saving) return;
    setSaving(true);
    const ok = await persistSession(session);
    setSaving(false);
    if (ok) closeSession();
  }

  async function saveDefinitionTitle(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    try {
      const updated = await browserApiFetch<ElementDefinition>(`/api/element-definitions/${selected.id}`, {
        method: "PATCH",
        body: JSON.stringify({ title: definitionTitle }),
      });
      replaceDefinition(updated);
      showToast(t("toast.elementSaved", { title: updated.title }), "success");
      setSelectedId(null);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.elementSaveFailed"), "error");
    }
  }

  async function duplicateDefinition(definition: ElementDefinition) {
    if (duplicatingId) return;
    setDuplicatingId(definition.id);
    try {
      const created = await browserApiFetch<ElementDefinition>("/api/element-definitions", {
        method: "POST",
        body: JSON.stringify({
          title: t("copyTitle", { title: definition.title }),
          description: definition.description,
          is_active: definition.is_active,
          blocks: definition.blocks,
        }),
      });
      setDefinitions((current) => [created, ...current]);
      openDefinition(created);
      showToast(t("toast.elementDuplicated", { title: created.title }), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.elementDuplicateFailed"), "error");
    } finally {
      setDuplicatingId(null);
    }
  }

  async function deleteDefinition(definition: ElementDefinition) {
    const ok = await confirm({ message: t("confirm.deleteElement"), tone: "danger", confirmLabel: t("delete") });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/element-definitions/${definition.id}`, { method: "DELETE" });
      setDefinitions((current) => current.filter((entry) => entry.id !== definition.id));
      if (selectedId === definition.id) setSelectedId(null);
      showToast(t("toast.elementDeleted", { title: definition.title }), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.elementDeleteFailed"), "error");
    }
  }

  async function deleteBlock(block: ElementDefinitionBlock) {
    if (!selected) return;
    const ok = await confirm({ message: t("confirm.deleteBlock"), tone: "danger", confirmLabel: t("delete") });
    if (!ok) return;
    await saveBlocks(selected, sortedBlocks(selected.blocks).filter((entry) => entry.id !== block.id), t("toast.blockDeleted"));
  }

  async function reorderBlocks(sourceId: number, targetId: number) {
    if (!selected || sourceId === targetId) return;
    const blocks = sortedBlocks(selected.blocks);
    const from = blocks.findIndex((block) => block.id === sourceId);
    const to = blocks.findIndex((block) => block.id === targetId);
    if (from < 0 || to < 0) return;
    const [moved] = blocks.splice(from, 1);
    blocks.splice(to, 0, moved);
    await saveBlocks(selected, blocks, t("toast.blockOrderSaved"));
  }

  function updateForm(form: BlockForm) {
    setSession((current) => (current ? { ...current, form } : current));
  }

  async function applyDesigner(next: BlockForm) {
    if (!session) return;
    const updated = { ...session, form: next };
    setSession(updated);
    // Beim Bearbeiten speichert «Übernehmen» sofort, beim Anlegen erst das Formular.
    if (updated.mode === "edit") {
      const ok = await persistSession(updated);
      if (!ok) return;
    }
    setDesigner(null);
  }

  const blockName = (block: ElementDefinitionBlock) =>
    String(block.title ?? "").trim() || String(block.block_title ?? "").trim() || t("blockList.unnamed");

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("page.title")}</h1>
          <p className="muted">{t("page.intro1")}</p>
          <p className="muted">{t("page.intro2")}</p>
        </div>
        <button type="button" className="button-primary" onClick={startNewElement}>{t("page.newElement")}</button>
      </div>

      <div className="list-filter-row">
        <div />
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder={t("page.search")} />
        </div>
      </div>

      <DataTable className="data-table-lg" columns={[t("page.colElement"), t("page.colBlocks"), t("page.colActions")]}>
        {filteredDefinitions.map((definition) => (
          <tr key={definition.id} className={`table-row-clickable${selectedId === definition.id ? " table-row-active" : ""}`} onClick={() => openDefinition(definition)}>
            <td><strong>{definition.title}</strong></td>
            <td>{t("page.blockCount", { count: definition.blocks.length })}</td>
            <td>
              <div className="table-actions">
                <button
                  type="button"
                  className="button-secondary button-ghost"
                  disabled={duplicatingId !== null}
                  onClick={(event) => { event.stopPropagation(); void duplicateDefinition(definition); }}
                >
                  {duplicatingId === definition.id ? t("page.duplicating") : t("page.duplicate")}
                </button>
                <button type="button" className="button-secondary button-danger" onClick={(event) => { event.stopPropagation(); void deleteDefinition(definition); }}>
                  {t("delete")}
                </button>
              </div>
            </td>
          </tr>
        ))}
      </DataTable>

      <Modal
        open={Boolean(selected) && !session}
        onClose={() => setSelectedId(null)}
        title={selected ? t("definition.titleNamed", { name: selected.title }) : t("definition.title")}
        description={t("definition.description")}
        size="wide"
      >
        {selected ? (
          <div className="section-stack">
            <ModalSaveForm id="element-definition-form" className="grid" onSubmit={saveDefinitionTitle}>
              <SettingsSection title={t("element.title")} description={t("element.description")}>
                <label className="field-stack">
                  <span className="field-label">{t("element.titleLabel")}</span>
                  <input value={definitionTitle} onChange={(event) => setDefinitionTitle(event.target.value)} required />
                  <span className="field-help">{t("cycleTokens.inline", { tokens: "{cycle_name}, {cycle_year_start}, {cycle_year_end}" })}</span>
                </label>
              </SettingsSection>
            </ModalSaveForm>

            <SettingsSection
              title={t("blockList.title", { name: selected.title })}
              description={t("blockList.description")}
              actions={<button type="button" className="button-secondary" onClick={startNewBlock}>{t("blockList.newBlock")}</button>}
            >
              <DataTable columns={[t("blockList.colBlock"), t("blockList.colType"), t("blockList.colHeading"), t("blockList.colOrder"), t("page.colActions")]}>
                {sortedBlocks(selected.blocks).map((block) => (
                  <tr
                    key={block.id}
                    draggable
                    className={`table-row-clickable${draggedBlockId === block.id ? " table-row-dragging" : ""}`}
                    onClick={() => startEditBlock(block)}
                    onDragStart={() => setDraggedBlockId(block.id)}
                    onDragEnd={() => setDraggedBlockId(null)}
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={(event) => {
                      event.preventDefault();
                      const sourceId = draggedBlockId;
                      setDraggedBlockId(null);
                      if (sourceId) void reorderBlocks(sourceId, block.id);
                    }}
                  >
                    <td><strong>{blockName(block)}</strong></td>
                    <td>{typeLabels[block.element_type_id] ?? t("blockList.unknownType")}</td>
                    <td>{block.block_title?.trim() || <span className="muted">{t("blockList.noHeading")}</span>}</td>
                    <td><span className="pill">{t("blockList.drag")}</span></td>
                    <td>
                      <div className="table-actions">
                        <button type="button" className="button-secondary button-ghost" onClick={(event) => { event.stopPropagation(); startEditBlock(block); }}>
                          {t("blockList.edit")}
                        </button>
                        <button type="button" className="button-secondary button-danger" onClick={(event) => { event.stopPropagation(); void deleteBlock(block); }}>
                          {t("delete")}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </DataTable>
            </SettingsSection>
            <div className="modal-actions">
              <button type="button" className="button-ghost" onClick={() => setSelectedId(null)}>{t("cancel")}</button>
              <button data-modal-save type="submit" form="element-definition-form" className="button-primary">{t("save")}</button>
            </div>
          </div>
        ) : null}
      </Modal>

      <Modal
        open={Boolean(session) && !typePickerOpen}
        onClose={closeSession}
        title={
          session?.mode === "edit"
            ? t("blockDialog.editTitle", { name: session.form.title.trim() || session.form.block_title.trim() || typeLabels[session.form.element_type_id] || "" })
            : session?.mode === "create" && session.newElement
            ? t("blockDialog.createElementTitle")
            : t("blockDialog.createBlockTitle")
        }
        description={session?.mode === "edit" ? t("blockDialog.editDescription") : t("blockDialog.createDescription")}
        className="element-create-modal"
        size="wide"
        headerActions={
          <button type="button" className="button-ghost" aria-pressed={showHelp} onClick={() => setShowHelp((current) => !current)}>
            {t("help.toggle")}
          </button>
        }
      >
        {session ? (
          <ModalSaveForm className="grid element-create-form" onSubmit={submitSession}>
            <BlockEditor
              mode={session.mode}
              form={session.form}
              onChange={updateForm}
              data={data}
              onChooseType={() => setTypePickerOpen(true)}
              onOpenDesigner={(kind, rowId) => setDesigner({ kind, rowId })}
              elementTitle={session.mode === "create" ? session.elementTitle : selected?.title ?? ""}
              onElementTitleChange={
                session.mode === "create" && session.newElement
                  ? (title) => setSession((current) => (current && current.mode === "create" ? { ...current, elementTitle: title } : current))
                  : undefined
              }
              showHelp={showHelp}
            />
            <div className="modal-actions element-create-footer">
              {session.mode === "create" && session.newElement ? <p className="muted">{t("blockDialog.createFooterNote")}</p> : null}
              <button type="button" className="button-ghost" onClick={closeSession}>{t("cancel")}</button>
              <button
                data-modal-save
                type="submit"
                className="button-primary"
                disabled={saving || (session.mode === "create" && session.newElement && !session.elementTitle.trim())}
              >
                {session.mode === "edit" ? t("save") : session.newElement ? t("blockDialog.createElementTitle") : t("blockDialog.createBlockTitle")}
              </button>
            </div>
          </ModalSaveForm>
        ) : null}
      </Modal>

      <TypePickerModal
        open={Boolean(session) && typePickerOpen}
        activeTypeId={session?.form.element_type_id ?? 1}
        onPick={(typeId) => {
          if (session) updateForm(changeElementType(session.form, typeId, session.mode));
          setTypePickerOpen(false);
        }}
        onClose={() => {
          setTypePickerOpen(false);
          // Neuanlage ohne gewählten Typ abgebrochen: Dialog ganz schliessen.
          if (session?.mode === "create" && session.newElement && !session.elementTitle && !session.form.title) closeSession();
        }}
      />

      {session && designer ? (
        <RowDesigner
          open
          kind={designer.kind}
          form={session.form}
          data={data}
          cycleConfigs={cycleConfigs}
          initialRowId={designer.rowId}
          onApply={(next) => { void applyDesigner(next); }}
          onCancel={() => setDesigner(null)}
        />
      ) : null}
    </div>
  );
}
