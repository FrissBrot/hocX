"use client";

// Vorlagen-Editor einer Sitzungsvorlage: eine Wahrheit für Protokoll-Editor, PDF und Einladung.
//
// Die Vorlage besteht aus Traktanden; jedes Traktandum enthält Bausteine (Text, Aufgaben,
// Anwesenheit …) in fester Reihenfolge. Jeder Baustein wird hier direkt konfiguriert:
// - Inhalt (Titel, Spalten, Zeilen …) im Baustein-Dialog,
// - «Im Protokoll-Editor zeigen» und «Im PDF zeigen» unabhängig voneinander, dazu Bearbeitbarkeit,
//   «Vom letzten Protokoll übernehmen» und «Titel als Untertitel» (je Vorlage gespeichert),
// - Darstellung im PDF (Variante, Ecken) je Vorlage.
// Steckt der Inhalt eines Traktandums auch in anderen Vorlagen (Bibliotheks-Baustein), fragt jede
// inhaltliche Änderung: überall aktualisieren oder nur in dieser Vorlage.
// Die Ansichten «PDF» und «Einladung» zeigen die Seitengestaltung (session-design-view.tsx).

import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { BlockEditor, type BlockEditorData } from "@/components/template/element-editor/block-editor";
import { blockFormFromBlock, blockPayload, changeElementType, newBlockForm, nextBlockId, type BehaviorField, type BlockForm } from "@/components/template/element-editor/block-form";
import { RowDesigner } from "@/components/template/element-editor/row-designer";
import { TypePickerModal } from "@/components/template/element-editor/type-picker";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { elementTypeLabels } from "@/lib/constants/element-types";
import { elementType } from "@/lib/element-types/registry";
import type { CycleConfigSummary, ElementDefinition, ElementDefinitionBlock, TemplateElement, TemplateElementBlock } from "@/types/api";

// Darstellung je Baustein-Typ (backend/app/documents/appearance.py: APPEARANCE_KIND_BY_ELEMENT_TYPE)
const APPEARANCE_KIND: Record<string, string> = {
  todo: "table",
  matrix: "table",
  fine_list: "table",
  finance_transactions: "table",
  event_list: "table",
  attendance: "attendance",
  session_date: "session_date",
  finance_balance: "finance_balance",
  form: "form",
};
const APPEARANCE_VARIANTS: Record<string, string[]> = {
  table: ["lines", "grid", "zebra", "minimal"],
  attendance: ["list", "compact", "table"],
  session_date: ["line", "box"],
  finance_balance: ["list", "tiles"],
  form: ["grid", "table"],
};
const CORNER_KINDS = new Set(["session_date", "finance_balance"]);

type Selection = { kind: "element"; id: string } | { kind: "block"; elementId: string; blockId: number } | null;
type ScopeChoice = "all" | "here";
type BlockSession = { mode: "create" | "edit"; elementId: string | null; elementTitle: string; form: BlockForm };

type Props = {
  templateId: string;
  elements: TemplateElement[];
  onElementsChange: (elements: TemplateElement[]) => void;
  onReorder: (ordered: TemplateElement[]) => Promise<boolean>;
  onOpenResponsibility: (elementId: string) => void;
  responsibilityTitle: (element: TemplateElement) => string;
  blockEditorData: BlockEditorData;
  cycleConfigs: CycleConfigSummary[];
};

function invitationVisible(config: Record<string, unknown>) {
  return config.invitation_visible !== false;
}

/** Definition-Block aus dem gelesenen Vorlagen-Block, mit den Standardwerten der Definition
 * (die Vorlagen-Übersteuerungen bleiben in der Vorlage). */
function definitionBlock(block: TemplateElementBlock): ElementDefinitionBlock {
  const defaults = block.behavior_defaults ?? {};
  return {
    id: block.id,
    title: block.title,
    description: block.description,
    block_title: block.block_title,
    default_content: block.default_content,
    copy_from_last_protocol: defaults.copy_from_last_protocol ?? false,
    title_as_subtitle: defaults.title_as_subtitle ?? true,
    element_type_id: block.element_type_id,
    render_type_id: block.render_type_id,
    is_editable: defaults.is_editable ?? true,
    allows_multiple_values: block.allows_multiple_values,
    export_visible: defaults.export_visible ?? true,
    is_visible: defaults.is_visible ?? true,
    sort_index: block.sort_index,
    render_order: block.render_order,
    configuration_json: block.configuration_json,
  } as ElementDefinitionBlock;
}

function resequence(blocks: ElementDefinitionBlock[]) {
  return blocks.map((block, index) => ({ ...block, sort_index: (index + 1) * 10, render_order: (index + 1) * 10 }));
}

export function SessionTemplateWorkspace({ templateId, elements, onElementsChange, onReorder, onOpenResponsibility, responsibilityTitle, blockEditorData, cycleConfigs }: Props) {
  const t = useTranslations("templates.studio");
  const tTypes = useTranslations("templates");
  const tEditor = useTranslations("templates.elementEditor");
  const typeLabels = elementTypeLabels(tTypes);
  const showToast = useToast();
  const confirm = useConfirm();
  const [selection, setSelection] = useState<Selection>(null);
  const [library, setLibrary] = useState<ElementDefinition[]>([]);
  const [librarySearch, setLibrarySearch] = useState("");
  const [session, setSession] = useState<BlockSession | null>(null);
  const [typePickerOpen, setTypePickerOpen] = useState(false);
  const [designer, setDesigner] = useState<{ kind: "form" | "matrix"; rowId?: string } | null>(null);
  const [scopeQuestion, setScopeQuestion] = useState<{ element: TemplateElement; resolve: (choice: ScopeChoice | null) => void } | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [busy, setBusy] = useState(false);

  const ordered = useMemo(() => [...elements].sort((left, right) => left.sort_index - right.sort_index), [elements]);
  const selectedElement = selection ? ordered.find((item) => item.id === (selection.kind === "element" ? selection.id : selection.elementId)) ?? null : null;
  const selectedBlock = selection?.kind === "block" && selectedElement ? selectedElement.blocks.find((block) => block.id === selection.blockId) ?? null : null;

  useEffect(() => {
    browserApiFetch<ElementDefinition[]>("/api/element-definitions?library=true")
      .then((rows) => setLibrary(rows ?? []))
      .catch(() => setLibrary([]));
  }, []);
  useEffect(() => {
    if (selectedElement && selection?.kind === "element") setRenameDraft(selectedElement.title);
    // Nur beim Wechsel der Auswahl übernehmen, nicht bei jeder Antwort
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection]);

  async function reload() {
    const rows = await browserApiFetch<TemplateElement[]>(`/api/templates/${templateId}/elements`);
    onElementsChange(rows ?? []);
    return rows ?? [];
  }

  function replaceElement(updated: TemplateElement) {
    onElementsChange(elements.map((item) => (item.id === updated.id ? updated : item)));
  }

  /** Inhalt ändern: bei geteiltem Inhalt fragen, ob überall oder nur hier. Gibt die ID der zu
   * ändernden Elementdefinition zurück (nach «nur hier» die eigene Kopie) oder null bei Abbruch. */
  async function definitionForChange(element: TemplateElement): Promise<string | null> {
    const shared = (element.definition_usage_count ?? 1) > 1;
    if (!shared) return element.element_definition_id;
    const choice = await new Promise<ScopeChoice | null>((resolve) => setScopeQuestion({ element, resolve }));
    setScopeQuestion(null);
    if (choice === null) return null;
    if (choice === "all") return element.element_definition_id;
    const detached = await browserApiFetch<TemplateElement>(`/api/template-elements/${element.id}/detach`, { method: "POST" });
    replaceElement(detached);
    return detached.element_definition_id;
  }

  async function saveDefinition(element: TemplateElement, patch: { title?: string; blocks?: ElementDefinitionBlock[] }, success: string) {
    setBusy(true);
    try {
      const definitionId = await definitionForChange(element);
      if (!definitionId) return false;
      await browserApiFetch<ElementDefinition>(`/api/element-definitions/${definitionId}`, {
        method: "PATCH",
        body: JSON.stringify(patch.blocks ? { ...patch, blocks: resequence(patch.blocks) } : patch),
      });
      await reload();
      showToast(success, "success");
      return true;
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.saveFailed"), "error");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function setBehavior(element: TemplateElement, block: TemplateElementBlock, field: BehaviorField, value: boolean) {
    try {
      const updated = await browserApiFetch<TemplateElement>(`/api/template-elements/${element.id}/behavior`, {
        method: "PATCH",
        body: JSON.stringify({ scope: "block", block_id: block.id, [field]: value }),
      });
      replaceElement(updated);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.saveFailed"), "error");
    }
  }

  async function patchElementConfig(element: TemplateElement, configuration: Record<string, unknown>) {
    try {
      const updated = await browserApiFetch<TemplateElement>(`/api/template-elements/${element.id}`, {
        method: "PATCH",
        body: JSON.stringify({ configuration_json: configuration }),
      });
      replaceElement(updated);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.saveFailed"), "error");
    }
  }

  function blockAppearance(element: TemplateElement, block: TemplateElementBlock): { kind: string | null; variant: string; corners: string } {
    const kind = APPEARANCE_KIND[elementType(block.element_type_id).code] ?? null;
    const stored = ((element.configuration_json.block_appearance as Record<string, Record<string, { variant?: string | null; corners?: string | null }>> | undefined) ?? {})[String(block.id)] ?? {};
    const entry = kind ? stored[kind] ?? {} : {};
    return { kind, variant: entry.variant ?? "", corners: entry.corners ?? "" };
  }

  async function setAppearance(element: TemplateElement, block: TemplateElementBlock, next: { variant: string; corners: string }) {
    const kind = APPEARANCE_KIND[elementType(block.element_type_id).code];
    if (!kind) return;
    const all = { ...((element.configuration_json.block_appearance as Record<string, unknown>) ?? {}) };
    const value = { variant: next.variant || null, corners: next.corners || null };
    if (!value.variant && !value.corners) delete all[String(block.id)];
    else all[String(block.id)] = { [kind]: value };
    await patchElementConfig(element, { ...element.configuration_json, block_appearance: all });
  }

  // ── Traktanden ────────────────────────────────────────────────────────────

  function startNewElement() {
    setSession({ mode: "create", elementId: null, elementTitle: "", form: newBlockForm(1, 1, 10) });
    setTypePickerOpen(true);
  }

  function startNewBlock(element: TemplateElement) {
    const blocks = element.blocks.map(definitionBlock);
    setSession({ mode: "create", elementId: element.id, elementTitle: element.title, form: newBlockForm(1, nextBlockId(blocks), (blocks.length + 1) * 10) });
    setTypePickerOpen(true);
  }

  function startEditBlock(element: TemplateElement, block: TemplateElementBlock) {
    setSession({ mode: "edit", elementId: element.id, elementTitle: element.title, form: blockFormFromBlock(definitionBlock(block)) });
  }

  async function addFromLibrary(definition: ElementDefinition) {
    try {
      const nextSort = ordered.reduce((max, item) => Math.max(max, item.sort_index), 0) + 10;
      await browserApiFetch<TemplateElement>(`/api/templates/${templateId}/elements`, {
        method: "POST",
        body: JSON.stringify({ element_definition_id: definition.id, sort_index: nextSort }),
      });
      const rows = await reload();
      const created = rows.find((row) => row.element_definition_id === definition.id && !elements.some((item) => item.id === row.id));
      if (created) setSelection({ kind: "element", id: created.id });
      showToast(t("toast.elementAdded", { title: definition.title }), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.saveFailed"), "error");
    }
  }

  async function submitSession(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || busy) return;
    const payload = blockPayload(session.form);
    if (session.elementId === null) {
      // Neues Traktandum mit seinem ersten Baustein (nur in dieser Vorlage)
      setBusy(true);
      try {
        const definition = await browserApiFetch<ElementDefinition>("/api/element-definitions", {
          method: "POST",
          body: JSON.stringify({ title: session.elementTitle.trim(), description: null, is_active: true, is_library: false, blocks: [{ ...payload, sort_index: 10, render_order: 10 }] }),
        });
        const nextSort = ordered.reduce((max, item) => Math.max(max, item.sort_index), 0) + 10;
        const created = await browserApiFetch<TemplateElement>(`/api/templates/${templateId}/elements`, {
          method: "POST",
          body: JSON.stringify({ element_definition_id: definition.id, sort_index: nextSort }),
        });
        await reload();
        setSelection({ kind: "element", id: created.id });
        showToast(t("toast.elementAdded", { title: definition.title }), "success");
        closeSession();
      } catch (error) {
        showToast(error instanceof Error ? error.message : t("toast.saveFailed"), "error");
      } finally {
        setBusy(false);
      }
      return;
    }
    const element = elements.find((item) => item.id === session.elementId);
    if (!element) return;
    const blocks = [...element.blocks].sort((left, right) => left.sort_index - right.sort_index).map(definitionBlock);
    const next = session.mode === "create" ? [...blocks, payload] : blocks.map((block) => (block.id === payload.id ? payload : block));
    const ok = await saveDefinition(element, { blocks: next }, session.mode === "create" ? t("toast.blockAdded") : t("toast.blockSaved"));
    if (ok) {
      if (session.mode === "create") setSelection({ kind: "block", elementId: element.id, blockId: payload.id });
      closeSession();
    }
  }

  function closeSession() {
    setSession(null);
    setTypePickerOpen(false);
    setDesigner(null);
  }

  async function removeBlock(element: TemplateElement, block: TemplateElementBlock) {
    if (element.blocks.length <= 1) {
      await removeElement(element);
      return;
    }
    const ok = await confirm({ message: t("confirm.removeBlock"), tone: "danger", confirmLabel: t("remove") });
    if (!ok) return;
    const next = element.blocks.filter((entry) => entry.id !== block.id).sort((left, right) => left.sort_index - right.sort_index).map(definitionBlock);
    if (await saveDefinition(element, { blocks: next }, t("toast.blockRemoved"))) setSelection({ kind: "element", id: element.id });
  }

  async function moveBlock(element: TemplateElement, block: TemplateElementBlock, delta: -1 | 1) {
    const blocks = [...element.blocks].sort((left, right) => left.sort_index - right.sort_index);
    const index = blocks.findIndex((entry) => entry.id === block.id);
    const target = index + delta;
    if (index < 0 || target < 0 || target >= blocks.length) return;
    const next = [...blocks];
    next.splice(index, 1);
    next.splice(target, 0, block);
    await saveDefinition(element, { blocks: next.map(definitionBlock) }, t("toast.orderSaved"));
  }

  async function moveElement(element: TemplateElement, delta: -1 | 1) {
    const index = ordered.findIndex((entry) => entry.id === element.id);
    const target = index + delta;
    if (index < 0 || target < 0 || target >= ordered.length) return;
    const next = [...ordered];
    next.splice(index, 1);
    next.splice(target, 0, element);
    await onReorder(next);
  }

  async function removeElement(element: TemplateElement) {
    const ok = await confirm({ title: t("confirm.removeElementTitle"), message: t("confirm.removeElement", { title: element.title }), tone: "danger", confirmLabel: t("remove") });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/template-elements/${element.id}`, { method: "DELETE" });
      onElementsChange(elements.filter((item) => item.id !== element.id));
      setSelection(null);
      showToast(t("toast.elementRemoved"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.saveFailed"), "error");
    }
  }

  async function renameElement(element: TemplateElement) {
    const title = renameDraft.trim();
    if (!title || title === element.title) return;
    await saveDefinition(element, { title }, t("toast.renamed"));
  }

  async function saveToLibrary(element: TemplateElement) {
    try {
      await browserApiFetch<ElementDefinition>(`/api/element-definitions/${element.element_definition_id}`, { method: "PATCH", body: JSON.stringify({ is_library: true }) });
      await reload();
      const rows = await browserApiFetch<ElementDefinition[]>("/api/element-definitions?library=true");
      setLibrary(rows ?? []);
      showToast(t("toast.savedToLibrary", { title: element.title }), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.saveFailed"), "error");
    }
  }

  async function detach(element: TemplateElement) {
    try {
      const updated = await browserApiFetch<TemplateElement>(`/api/template-elements/${element.id}/detach`, { method: "POST" });
      replaceElement(updated);
      showToast(t("toast.detached"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toast.saveFailed"), "error");
    }
  }

  const filteredLibrary = library.filter((definition) => !librarySearch.trim() || definition.title.toLowerCase().includes(librarySearch.trim().toLowerCase()));
  const blockName = (block: TemplateElementBlock) => block.block_title?.trim() || block.title?.trim() || typeLabels[block.element_type_id] || "";

  // ── Darstellung ───────────────────────────────────────────────────────────

  function visibilityBadges(block: TemplateElementBlock): ReactNode {
    return (
      <>
        {!block.is_visible && <Badge variant="neutral">{t("badge.notInEditor")}</Badge>}
        {!block.export_visible && <Badge variant="neutral">{t("badge.notInPdf")}</Badge>}
        {!block.is_editable && <Badge variant="info">{t("badge.readOnly")}</Badge>}
      </>
    );
  }

  return (
    <div className="session-studio-workspace">
      <aside className="session-studio-left" aria-label={t("catalog.title")}>
        <div className="session-studio-panel-scroll">
          <section className="session-studio-section">
            <h2 className="studio-palette-title">{t("catalog.newTitle")}</h2>
            <button type="button" className="button-primary" onClick={startNewElement}>
              {t("catalog.newElement")}
            </button>
            {selectedElement ? (
              <button type="button" className="button-secondary button-ghost" onClick={() => startNewBlock(selectedElement)}>
                {t("catalog.addBlockTo", { title: selectedElement.title })}
              </button>
            ) : (
              <p className="field-help">{t("catalog.selectHint")}</p>
            )}
          </section>
          <section className="session-studio-section">
            <h2 className="studio-palette-title">{t("catalog.libraryTitle")}</h2>
            <p className="field-help">{t("catalog.libraryHelp")}</p>
            <SearchInput value={librarySearch} onChange={setLibrarySearch} placeholder={t("catalog.search")} />
            <div className="session-studio-library-list">
              {filteredLibrary.length === 0 ? <p className="muted">{t("catalog.libraryEmpty")}</p> : null}
              {filteredLibrary.map((definition) => (
                <button key={definition.id} type="button" className="session-studio-library-item" onClick={() => void addFromLibrary(definition)} title={t("catalog.addFromLibrary", { title: definition.title })}>
                  <strong>{definition.title}</strong>
                  <span className="muted">{definition.blocks.map((block) => typeLabels[block.element_type_id]).filter(Boolean).join(" · ")}</span>
                </button>
              ))}
            </div>
          </section>
        </div>
      </aside>

      <main className="session-studio-center" aria-label={t("center.title")} onClick={() => setSelection(null)}>
        <p className="studio-canvas-hint">{t("center.hint")}</p>
        {ordered.length === 0 ? (
          <EmptyState title={t("center.emptyTitle")} description={t("center.emptyDescription")} />
        ) : (
          <ol className="session-studio-elements">
            {ordered.map((element, index) => {
              const selected = selection?.kind === "element" && selection.id === element.id;
              const blocks = [...element.blocks].sort((left, right) => left.sort_index - right.sort_index);
              return (
                <li key={element.id} className={selected ? "session-studio-element session-studio-element-selected" : "session-studio-element"}>
                  <button
                    type="button"
                    className="session-studio-element-head"
                    aria-pressed={selected}
                    onClick={(event) => {
                      event.stopPropagation();
                      setSelection({ kind: "element", id: element.id });
                    }}
                  >
                    <span className="session-studio-number">{index + 1}</span>
                    <span className="session-studio-element-title">{responsibilityTitle(element)}</span>
                    <span className="session-studio-element-badges">
                      {!invitationVisible(element.configuration_json) && <Badge variant="neutral">{t("badge.notInInvitation")}</Badge>}
                      {(element.definition_usage_count ?? 1) > 1 && <Badge variant="violet">{t("badge.shared", { count: element.definition_usage_count ?? 1 })}</Badge>}
                    </span>
                  </button>
                  <ul className="session-studio-blocks">
                    {blocks.map((block) => {
                      const blockSelected = selection?.kind === "block" && selection.blockId === block.id && selection.elementId === element.id;
                      const hiddenEverywhere = !block.is_visible && !block.export_visible;
                      return (
                        <li key={block.id}>
                          <button
                            type="button"
                            className={[
                              "session-studio-block",
                              blockSelected ? "session-studio-block-selected" : "",
                              !block.is_visible ? "session-studio-block-hidden" : "",
                              hiddenEverywhere ? "session-studio-block-nowhere" : "",
                            ].join(" ")}
                            aria-pressed={blockSelected}
                            onClick={(event) => {
                              event.stopPropagation();
                              setSelection({ kind: "block", elementId: element.id, blockId: block.id });
                            }}
                            onDoubleClick={(event) => {
                              event.stopPropagation();
                              startEditBlock(element, block);
                            }}
                          >
                            <span className="session-studio-block-type">{typeLabels[block.element_type_id]}</span>
                            <span className="session-studio-block-title">{blockName(block)}</span>
                            <span className="session-studio-block-badges">{visibilityBadges(block)}</span>
                          </button>
                        </li>
                      );
                    })}
                    <li>
                      <button
                        type="button"
                        className="session-studio-add-block"
                        onClick={(event) => {
                          event.stopPropagation();
                          startNewBlock(element);
                        }}
                      >
                        {t("center.addBlock")}
                      </button>
                    </li>
                  </ul>
                </li>
              );
            })}
          </ol>
        )}
      </main>

      <aside className="session-studio-right" aria-label={t("props.title")}>
        <div className="session-studio-panel-scroll">
          {!selectedElement ? (
            <div className="session-studio-section">
              <h2 className="studio-palette-title">{t("props.title")}</h2>
              <p className="muted">{t("props.empty")}</p>
            </div>
          ) : selectedBlock ? (
            <BlockProperties
              element={selectedElement}
              block={selectedBlock}
              typeLabel={typeLabels[selectedBlock.element_type_id] ?? ""}
              name={blockName(selectedBlock)}
              appearance={blockAppearance(selectedElement, selectedBlock)}
              onEdit={() => startEditBlock(selectedElement, selectedBlock)}
              onBehavior={(field, value) => void setBehavior(selectedElement, selectedBlock, field, value)}
              onAppearance={(next) => void setAppearance(selectedElement, selectedBlock, next)}
              onMove={(delta) => void moveBlock(selectedElement, selectedBlock, delta)}
              onRemove={() => void removeBlock(selectedElement, selectedBlock)}
              onBack={() => setSelection({ kind: "element", id: selectedElement.id })}
            />
          ) : (
            <div className="session-studio-section">
              <h2 className="studio-palette-title">{t("props.elementTitle")}</h2>
              <label className="field-stack">
                <span className="field-label">{t("props.name")}</span>
                <input value={renameDraft} onChange={(event) => setRenameDraft(event.target.value)} onBlur={() => void renameElement(selectedElement)} onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }} />
                <span className="field-help">{tEditor("cycleTokens.inline", { tokens: "{cycle_name}, {cycle_year_start}, {cycle_year_end}" })}</span>
              </label>
              <label className="studio-inline-check">
                <input type="checkbox" checked={invitationVisible(selectedElement.configuration_json)} onChange={(event) => void patchElementConfig(selectedElement, { ...selectedElement.configuration_json, invitation_visible: event.target.checked })} />
                <span>{t("props.inInvitation")}</span>
              </label>
              <span className="field-help">{t("props.inInvitationHelp")}</span>
              <div className="session-studio-actions">
                <button type="button" className="button-secondary" onClick={() => onOpenResponsibility(selectedElement.id)}>
                  {t("props.responsible")}
                </button>
                <button type="button" className="button-secondary" onClick={() => startNewBlock(selectedElement)}>
                  {t("props.addBlock")}
                </button>
              </div>
              <div className="session-studio-actions">
                <button type="button" className="button-icon-soft" aria-label={t("props.moveUp")} onClick={() => void moveElement(selectedElement, -1)}>↑</button>
                <button type="button" className="button-icon-soft" aria-label={t("props.moveDown")} onClick={() => void moveElement(selectedElement, 1)}>↓</button>
              </div>
              <div className="session-studio-section">
                <span className="field-label">{t("props.reuse")}</span>
                {selectedElement.definition_is_library ? (
                  <>
                    <p className="field-help">{t("props.libraryInfo", { count: selectedElement.definition_usage_count ?? 1 })}</p>
                    {(selectedElement.definition_usage_count ?? 1) > 1 ? (
                      <button type="button" className="button-secondary" onClick={() => void detach(selectedElement)}>
                        {t("props.detach")}
                      </button>
                    ) : null}
                  </>
                ) : (
                  <>
                    <p className="field-help">{t("props.singleInfo")}</p>
                    <button type="button" className="button-secondary" onClick={() => void saveToLibrary(selectedElement)}>
                      {t("props.saveToLibrary")}
                    </button>
                  </>
                )}
              </div>
              <button type="button" className="button-danger" onClick={() => void removeElement(selectedElement)}>
                {t("props.removeElement")}
              </button>
            </div>
          )}
        </div>
      </aside>

      <Modal
        open={Boolean(session) && !typePickerOpen}
        onClose={closeSession}
        title={session?.mode === "edit" ? t("dialog.editTitle", { name: session.form.title.trim() || session.form.block_title.trim() || typeLabels[session.form.element_type_id] || "" }) : session?.elementId === null ? t("dialog.newElementTitle") : t("dialog.newBlockTitle")}
        description={session?.elementId === null ? t("dialog.newElementDescription") : t("dialog.blockDescription", { title: session?.elementTitle ?? "" })}
        className="element-create-modal"
        size="wide"
      >
        {session ? (
          <ModalSaveForm className="grid element-create-form" onSubmit={submitSession}>
            <BlockEditor
              mode={session.mode}
              form={session.form}
              onChange={(form) => setSession((current) => (current ? { ...current, form } : current))}
              data={blockEditorData}
              onChooseType={() => setTypePickerOpen(true)}
              onOpenDesigner={(kind, rowId) => setDesigner({ kind, rowId })}
              elementTitle={session.elementTitle}
              onElementTitleChange={session.elementId === null ? (title) => setSession((current) => (current ? { ...current, elementTitle: title } : current)) : undefined}
              showHelp={false}
              hideBehavior
            />
            <div className="modal-actions element-create-footer">
              <button type="button" className="button-ghost" onClick={closeSession}>{t("cancel")}</button>
              <button data-modal-save type="submit" className="button-primary" disabled={busy || (session.elementId === null && !session.elementTitle.trim())}>
                {session.mode === "edit" ? t("save") : session.elementId === null ? t("dialog.createElement") : t("dialog.createBlock")}
              </button>
            </div>
          </ModalSaveForm>
        ) : null}
      </Modal>

      <TypePickerModal
        open={Boolean(session) && typePickerOpen}
        activeTypeId={session?.form.element_type_id ?? 1}
        onPick={(typeId) => {
          if (session) setSession({ ...session, form: changeElementType(session.form, typeId, session.mode) });
          setTypePickerOpen(false);
        }}
        onClose={() => {
          setTypePickerOpen(false);
          if (session?.mode === "create" && !session.form.title && !session.elementTitle) closeSession();
        }}
      />

      {session && designer ? (
        <RowDesigner
          open
          kind={designer.kind}
          form={session.form}
          data={blockEditorData}
          cycleConfigs={cycleConfigs}
          initialRowId={designer.rowId}
          onApply={(next) => {
            setSession((current) => (current ? { ...current, form: next } : current));
            setDesigner(null);
          }}
          onCancel={() => setDesigner(null)}
        />
      ) : null}

      <Modal open={Boolean(scopeQuestion)} onClose={() => scopeQuestion?.resolve(null)} title={t("scope.title")}>
        {scopeQuestion ? (
          <div className="grid">
            <p>{t("scope.message", { title: scopeQuestion.element.title, count: scopeQuestion.element.definition_usage_count ?? 2 })}</p>
            <div className="modal-actions">
              <button type="button" className="button-ghost" onClick={() => scopeQuestion.resolve(null)}>{t("cancel")}</button>
              <button type="button" className="button-secondary" onClick={() => scopeQuestion.resolve("here")}>{t("scope.here")}</button>
              <button type="button" className="button-primary" onClick={() => scopeQuestion.resolve("all")}>{t("scope.all")}</button>
            </div>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}

function BlockProperties({
  element,
  block,
  typeLabel,
  name,
  appearance,
  onEdit,
  onBehavior,
  onAppearance,
  onMove,
  onRemove,
  onBack,
}: {
  element: TemplateElement;
  block: TemplateElementBlock;
  typeLabel: string;
  name: string;
  appearance: { kind: string | null; variant: string; corners: string };
  onEdit: () => void;
  onBehavior: (field: BehaviorField, value: boolean) => void;
  onAppearance: (next: { variant: string; corners: string }) => void;
  onMove: (delta: -1 | 1) => void;
  onRemove: () => void;
  onBack: () => void;
}) {
  const t = useTranslations("templates.studio");
  const tStudio = useTranslations("documentStudio");
  const info = elementType(block.element_type_id);
  const switches: { field: BehaviorField; shown: boolean }[] = [
    { field: "is_visible", shown: true },
    { field: "export_visible", shown: true },
    { field: "is_editable", shown: true },
    { field: "copy_from_last_protocol", shown: info.carryOver },
  ];
  return (
    <div className="session-studio-section">
      <button type="button" className="button-ghost session-studio-back" onClick={onBack}>
        {t("props.backTo", { title: element.title })}
      </button>
      <h2 className="studio-palette-title">{typeLabel}</h2>
      <p className="session-studio-block-name">{name}</p>
      <button type="button" className="button-primary" onClick={onEdit}>
        {t("props.editContent")}
      </button>
      <fieldset className="studio-fieldset">
        <legend>{t("props.visibility")}</legend>
        {switches.filter((entry) => entry.shown).map(({ field }) => (
          <label key={field} className="studio-inline-check">
            <input type="checkbox" checked={Boolean(block[field])} onChange={(event) => onBehavior(field, event.target.checked)} />
            <span>
              {t(`switch.${field}.label`)}
              <span className="field-help">{t(`switch.${field}.help`)}</span>
            </span>
          </label>
        ))}
      </fieldset>
      {appearance.kind ? (
        <fieldset className="studio-fieldset">
          <legend>{t("props.appearance")}</legend>
          <label className="field-stack">
            <span className="field-label">{t("props.variant")}</span>
            <select value={appearance.variant} onChange={(event) => onAppearance({ variant: event.target.value, corners: appearance.corners })}>
              <option value="">{t("props.inherit")}</option>
              {(APPEARANCE_VARIANTS[appearance.kind] ?? []).map((variant) => (
                <option key={variant} value={variant}>
                  {tStudio(`appearance.variant.${appearance.kind}.${variant}`)}
                </option>
              ))}
            </select>
          </label>
          {CORNER_KINDS.has(appearance.kind) ? (
            <label className="field-stack">
              <span className="field-label">{t("props.corners")}</span>
              <select value={appearance.corners} onChange={(event) => onAppearance({ variant: appearance.variant, corners: event.target.value })}>
                <option value="">{t("props.inherit")}</option>
                <option value="square">{tStudio("appearance.corners.square")}</option>
                <option value="rounded">{tStudio("appearance.corners.rounded")}</option>
              </select>
            </label>
          ) : null}
          <span className="field-help">{t("props.appearanceHelp")}</span>
        </fieldset>
      ) : null}
      <div className="session-studio-actions">
        <button type="button" className="button-icon-soft" aria-label={t("props.moveUp")} onClick={() => onMove(-1)}>↑</button>
        <button type="button" className="button-icon-soft" aria-label={t("props.moveDown")} onClick={() => onMove(1)}>↓</button>
        <button type="button" className="button-danger" onClick={onRemove}>
          {t("props.removeBlock")}
        </button>
      </div>
    </div>
  );
}
