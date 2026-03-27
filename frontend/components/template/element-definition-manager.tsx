"use client";

import { FormEvent, useMemo, useState } from "react";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { ElementDefinition, ElementDefinitionBlock } from "@/types/api";

type ElementDefinitionManagerProps = {
  initialDefinitions: ElementDefinition[];
};

type DefinitionFormState = {
  title: string;
  description: string;
  is_active: boolean;
};

type BlockFormState = {
  id: string;
  title: string;
  description: string;
  block_title: string;
  default_content: string;
  element_type_id: string;
  render_type_id: string;
  is_editable: boolean;
  allows_multiple_values: boolean;
  export_visible: boolean;
  is_visible: boolean;
  sort_index: string;
  render_order: string;
  latex_template: string;
};

const initialDefinitionForm: DefinitionFormState = {
  title: "",
  description: "",
  is_active: true
};

const initialBlockForm: BlockFormState = {
  id: "1",
  title: "",
  description: "",
  block_title: "",
  default_content: "",
  element_type_id: "1",
  render_type_id: "2",
  is_editable: true,
  allows_multiple_values: false,
  export_visible: true,
  is_visible: true,
  sort_index: "10",
  render_order: "10",
  latex_template: ""
};

const elementTypeOptions = [
  { value: "1", label: "Text", description: "Editable text content" },
  { value: "2", label: "Todo", description: "Checklist or task list" },
  { value: "3", label: "Image", description: "Image upload area" },
  { value: "4", label: "Display", description: "Read-only computed snapshot" },
  { value: "5", label: "Static text", description: "Fixed text that editors cannot change later" }
];

const renderTypeOptions = [
  { value: "1", label: "Heading", description: "Heading-like output" },
  { value: "2", label: "Paragraph", description: "Standard paragraph content" },
  { value: "3", label: "Todo list", description: "Task list rendering" },
  { value: "4", label: "Image", description: "Image rendering" },
  { value: "5", label: "Key-value", description: "Compact key-value display" },
  { value: "6", label: "Plain text", description: "Simple unformatted output" },
  { value: "7", label: "Raw LaTeX", description: "Advanced custom export fragment" }
];

function optionLabel(options: { value: string; label: string }[], value: number | string) {
  return options.find((option) => option.value === String(value))?.label ?? `Unknown (${value})`;
}

function optionDescription(
  options: { value: string; label: string; description?: string }[],
  value: number | string
) {
  return options.find((option) => option.value === String(value))?.description ?? "";
}

function definitionFormFromDefinition(definition: ElementDefinition): DefinitionFormState {
  return {
    title: definition.title,
    description: definition.description ?? "",
    is_active: definition.is_active
  };
}

function blockFormFromBlock(block: ElementDefinitionBlock): BlockFormState {
  return {
    id: String(block.id),
    title: block.title,
    description: block.description ?? "",
    block_title: block.block_title ?? "",
    default_content: block.default_content ?? "",
    element_type_id: String(block.element_type_id),
    render_type_id: String(block.render_type_id),
    is_editable: block.is_editable,
    allows_multiple_values: block.allows_multiple_values,
    export_visible: block.export_visible,
    is_visible: block.is_visible,
    sort_index: String(block.sort_index),
    render_order: String(block.render_order ?? block.sort_index),
    latex_template: block.latex_template ?? ""
  };
}

function blockPayload(form: BlockFormState): ElementDefinitionBlock {
  return {
    id: Number(form.id),
    title: form.title,
    description: form.description || null,
    block_title: form.block_title || null,
    default_content: form.default_content || null,
    element_type_id: Number(form.element_type_id),
    render_type_id: Number(form.render_type_id),
    is_editable: form.is_editable,
    allows_multiple_values: form.allows_multiple_values,
    export_visible: form.export_visible,
    is_visible: form.is_visible,
    sort_index: Number(form.sort_index),
    render_order: Number(form.render_order),
    latex_template: form.latex_template || null,
    configuration_json: {}
  };
}

function nextBlockId(blocks: ElementDefinitionBlock[]) {
  return String(Math.max(0, ...blocks.map((block) => block.id)) + 1);
}

export function ElementDefinitionManager({ initialDefinitions }: ElementDefinitionManagerProps) {
  const [definitions, setDefinitions] = useState(initialDefinitions);
  const [selectedDefinitionId, setSelectedDefinitionId] = useState<number | null>(initialDefinitions[0]?.id ?? null);
  const [definitionForm, setDefinitionForm] = useState<DefinitionFormState>(
    initialDefinitions[0] ? definitionFormFromDefinition(initialDefinitions[0]) : initialDefinitionForm
  );
  const [createDefinitionForm, setCreateDefinitionForm] = useState(initialDefinitionForm);
  const [createBlockForm, setCreateBlockForm] = useState<BlockFormState>({
    ...initialBlockForm,
    id: nextBlockId(initialDefinitions[0]?.blocks ?? [])
  });
  const [selectedBlockId, setSelectedBlockId] = useState<number | null>(initialDefinitions[0]?.blocks[0]?.id ?? null);
  const [blockForm, setBlockForm] = useState<BlockFormState>(
    initialDefinitions[0]?.blocks[0] ? blockFormFromBlock(initialDefinitions[0].blocks[0]) : initialBlockForm
  );
  const [showCreateDefinition, setShowCreateDefinition] = useState(false);
  const [showCreateBlock, setShowCreateBlock] = useState(false);
  const [showDetailModal, setShowDetailModal] = useState(false);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("Ready");
  const [statusTone, setStatusTone] = useState<"neutral" | "success" | "error">("neutral");

  const filteredDefinitions = useMemo(
    () =>
      definitions.filter((definition) => {
        const haystack = `${definition.title} ${definition.description ?? ""}`.toLowerCase();
        return !search || haystack.includes(search.toLowerCase());
      }),
    [definitions, search]
  );

  const selectedDefinition = useMemo(
    () => definitions.find((definition) => definition.id === selectedDefinitionId) ?? null,
    [definitions, selectedDefinitionId]
  );
  const selectedBlock = useMemo(
    () => selectedDefinition?.blocks.find((block) => block.id === selectedBlockId) ?? null,
    [selectedDefinition, selectedBlockId]
  );

  function selectDefinition(definition: ElementDefinition) {
    setSelectedDefinitionId(definition.id);
    setDefinitionForm(definitionFormFromDefinition(definition));
    const firstBlock = definition.blocks[0] ?? null;
    setSelectedBlockId(firstBlock?.id ?? null);
    setBlockForm(firstBlock ? blockFormFromBlock(firstBlock) : { ...initialBlockForm, id: nextBlockId(definition.blocks) });
    setCreateBlockForm({ ...initialBlockForm, id: nextBlockId(definition.blocks) });
    setShowDetailModal(true);
  }

  function replaceDefinition(updated: ElementDefinition) {
    setDefinitions((current) =>
      current.map((definition) => (definition.id === updated.id ? updated : definition))
    );
  }

  async function createDefinition(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("Creating element...");
    setStatusTone("neutral");
    try {
      const created = await browserApiFetch<ElementDefinition>("/api/element-definitions", {
        method: "POST",
        body: JSON.stringify({
          tenant_id: 1,
          title: createDefinitionForm.title,
          description: createDefinitionForm.description || null,
          is_active: createDefinitionForm.is_active,
          blocks: []
        })
      });
      setDefinitions((current) => [created, ...current]);
      setCreateDefinitionForm(initialDefinitionForm);
      setShowCreateDefinition(false);
      selectDefinition(created);
      setStatus(`Created element #${created.id}`);
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Element creation failed");
      setStatusTone("error");
    }
  }

  async function saveDefinition(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedDefinition) return;
    setStatus(`Saving element #${selectedDefinition.id}...`);
    setStatusTone("neutral");
    try {
      const updated = await browserApiFetch<ElementDefinition>(`/api/element-definitions/${selectedDefinition.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: definitionForm.title,
          description: definitionForm.description || null,
          is_active: definitionForm.is_active,
          blocks: selectedDefinition.blocks
        })
      });
      replaceDefinition(updated);
      setStatus(`Saved element #${updated.id}`);
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Element save failed");
      setStatusTone("error");
    }
  }

  async function deleteDefinition(definitionId: number) {
    setStatus(`Deleting element #${definitionId}...`);
    setStatusTone("neutral");
    try {
      await browserApiFetch(`/api/element-definitions/${definitionId}`, { method: "DELETE" });
      const nextDefinitions = definitions.filter((definition) => definition.id !== definitionId);
      setDefinitions(nextDefinitions);
      if (nextDefinitions[0]) {
        selectDefinition(nextDefinitions[0]);
      } else {
        setSelectedDefinitionId(null);
        setSelectedBlockId(null);
        setDefinitionForm(initialDefinitionForm);
        setBlockForm(initialBlockForm);
      }
      setStatus(`Deleted element #${definitionId}`);
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Element deletion failed");
      setStatusTone("error");
    }
  }

  async function saveBlocks(nextBlocks: ElementDefinitionBlock[], message: string) {
    if (!selectedDefinition) return;
    try {
      const updated = await browserApiFetch<ElementDefinition>(`/api/element-definitions/${selectedDefinition.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          blocks: nextBlocks
        })
      });
      replaceDefinition(updated);
      setStatus(message);
      setStatusTone("success");
      const selected = updated.blocks.find((block) => block.id === selectedBlockId) ?? updated.blocks[0] ?? null;
      setSelectedBlockId(selected?.id ?? null);
      setBlockForm(selected ? blockFormFromBlock(selected) : { ...initialBlockForm, id: nextBlockId(updated.blocks) });
      setCreateBlockForm({ ...initialBlockForm, id: nextBlockId(updated.blocks) });
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Block update failed");
      setStatusTone("error");
    }
  }

  async function createBlock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedDefinition) return;
    setStatus("Adding block to element...");
    setStatusTone("neutral");
    const nextBlocks = [...selectedDefinition.blocks, blockPayload(createBlockForm)].sort((left, right) => left.sort_index - right.sort_index);
    await saveBlocks(nextBlocks, "Block added");
    setShowCreateBlock(false);
  }

  async function updateBlock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedDefinition || !selectedBlock) return;
    setStatus("Saving block...");
    setStatusTone("neutral");
    const updatedBlock = blockPayload(blockForm);
    const nextBlocks = selectedDefinition.blocks
      .map((block) => (block.id === selectedBlock.id ? updatedBlock : block))
      .sort((left, right) => left.sort_index - right.sort_index);
    await saveBlocks(nextBlocks, "Block saved");
  }

  async function deleteBlock(blockId: number) {
    if (!selectedDefinition) return;
    setStatus("Deleting block...");
    setStatusTone("neutral");
    const nextBlocks = selectedDefinition.blocks.filter((block) => block.id !== blockId);
    await saveBlocks(nextBlocks, "Block deleted");
  }

  return (
    <div className="grid">
      <DataToolbar
        title="Elements"
        description="Each element has a title and can contain multiple blocks such as text, todos or images. Templates only choose these finished elements and sort them."
        actions={
          <button type="button" className="button-inline" onClick={() => setShowCreateDefinition((current) => !current)}>
            {showCreateDefinition ? "Close create form" : "New element"}
          </button>
        }
      />

      <Modal
        open={showCreateDefinition}
        onClose={() => setShowCreateDefinition(false)}
        title="Create element"
        description="Build a reusable element with one title and multiple internal blocks."
      >
        <form className="grid" onSubmit={createDefinition}>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Element title</span>
              <input value={createDefinitionForm.title} onChange={(event) => setCreateDefinitionForm((current) => ({ ...current, title: event.target.value }))} placeholder="e.g. Zusammenarbeit mit Blauring" required />
              <span className="field-help">This is the main title of the whole element.</span>
            </label>
            <label className="field-stack">
              <span className="field-label">Description</span>
              <input value={createDefinitionForm.description} onChange={(event) => setCreateDefinitionForm((current) => ({ ...current, description: event.target.value }))} placeholder="Optional note for editors" />
              <span className="field-help">Optional explanation of what this element is for.</span>
            </label>
          </div>
          <label className="field-stack">
            <span className="field-label">State</span>
            <label className="checkbox-row">
              <input type="checkbox" checked={createDefinitionForm.is_active} onChange={(event) => setCreateDefinitionForm((current) => ({ ...current, is_active: event.target.checked }))} />
              Active
            </label>
            <span className="field-help">Inactive elements stay in the system but should not be chosen for new templates.</span>
          </label>
          <div className="table-toolbar-actions">
            <button type="submit" className="button-inline">Create element</button>
          </div>
        </form>
      </Modal>

      <article className="card">
        <div className="two-col">
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search elements" />
          <div className="info-note">Fixed blocks should be created here as non-editable blocks. They will appear read-only later in the protocol editor.</div>
        </div>
      </article>

      <StatusBanner tone={statusTone} message={status} />

      <DataTable columns={["Element", "Blocks", "State", "Actions"]}>
        {filteredDefinitions.map((definition) => (
          <tr key={definition.id} className={`table-row-clickable${selectedDefinitionId === definition.id ? " table-row-active" : ""}`} onClick={() => selectDefinition(definition)}>
            <td>
              <strong>{definition.title}</strong>
              <div className="muted">Element #{definition.id}</div>
            </td>
            <td>{definition.blocks.length} block{definition.blocks.length === 1 ? "" : "s"}</td>
            <td><span className="pill">{definition.is_active ? "active" : "inactive"}</span></td>
            <td>
              <div className="table-actions">
                <button type="button" className="button-inline button-danger" onClick={(event) => {
                  event.stopPropagation();
                  void deleteDefinition(definition.id);
                }}>Delete</button>
              </div>
            </td>
          </tr>
        ))}
      </DataTable>

      <Modal
        open={showDetailModal && !!selectedDefinition}
        onClose={() => {
          setShowDetailModal(false);
          setShowCreateBlock(false);
        }}
        title={selectedDefinition ? selectedDefinition.title : "Element detail"}
        description="Edit the element metadata and its internal blocks in one focused popup."
        size="wide"
      >
        {selectedDefinition ? (
        <>
          <article className="card">
            <div className="eyebrow">Element Detail</div>
            <h3>{selectedDefinition.title}</h3>
            <form className="grid" onSubmit={saveDefinition}>
              <div className="two-col">
                <label className="field-stack">
                  <span className="field-label">Element title</span>
                  <input value={definitionForm.title} onChange={(event) => setDefinitionForm((current) => ({ ...current, title: event.target.value }))} />
                </label>
                <label className="field-stack">
                  <span className="field-label">Description</span>
                  <input value={definitionForm.description} onChange={(event) => setDefinitionForm((current) => ({ ...current, description: event.target.value }))} />
                </label>
              </div>
              <label className="field-stack">
                <span className="field-label">State</span>
                <label className="checkbox-row">
                  <input type="checkbox" checked={definitionForm.is_active} onChange={(event) => setDefinitionForm((current) => ({ ...current, is_active: event.target.checked }))} />
                  Active
                </label>
              </label>
              <div className="table-toolbar-actions">
                <button type="submit" className="button-inline">Save element</button>
              </div>
            </form>
          </article>

          <article className="card">
            <DataToolbar
              title={`Blocks inside ${selectedDefinition.title}`}
              description="These blocks belong to this element. Templates cannot change them, they only choose the whole element."
              actions={
                <button type="button" className="button-inline" onClick={() => setShowCreateBlock((current) => !current)}>
                  {showCreateBlock ? "Close create form" : "New block"}
                </button>
              }
            />

            {showCreateBlock ? (
              <form className="grid section-stack" onSubmit={createBlock}>
                <div className="two-col">
                  <label className="field-stack">
                    <span className="field-label">Block name</span>
                    <input value={createBlockForm.title} onChange={(event) => setCreateBlockForm((current) => ({ ...current, title: event.target.value }))} placeholder="e.g. Meeting notes" required />
                    <span className="field-help">Internal block name for this element.</span>
                  </label>
                  <label className="field-stack">
                    <span className="field-label">Block subtitle</span>
                    <input value={createBlockForm.block_title} onChange={(event) => setCreateBlockForm((current) => ({ ...current, block_title: event.target.value }))} placeholder="e.g. Offene Punkte" />
                    <span className="field-help">Optional subtitle shown inside the element in the protocol editor.</span>
                  </label>
                </div>
                <div className="two-col">
                  <label className="field-stack">
                    <span className="field-label">Description</span>
                    <input value={createBlockForm.description} onChange={(event) => setCreateBlockForm((current) => ({ ...current, description: event.target.value }))} placeholder="Optional note for editors" />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">Default or fixed content</span>
                    <input value={createBlockForm.default_content} onChange={(event) => setCreateBlockForm((current) => ({ ...current, default_content: event.target.value }))} placeholder="Used for static text or initial text" />
                    <span className="field-help">For static text blocks this becomes the fixed content. For normal text blocks it is the initial text.</span>
                  </label>
                </div>
                <div className="three-col">
                  <label className="field-stack">
                    <span className="field-label">Block type</span>
                    <select value={createBlockForm.element_type_id} onChange={(event) => setCreateBlockForm((current) => ({ ...current, element_type_id: event.target.value }))}>
                      {elementTypeOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                    </select>
                    <span className="field-help">{optionDescription(elementTypeOptions, createBlockForm.element_type_id)}</span>
                  </label>
                  <label className="field-stack">
                    <span className="field-label">Render style</span>
                    <select value={createBlockForm.render_type_id} onChange={(event) => setCreateBlockForm((current) => ({ ...current, render_type_id: event.target.value }))}>
                      {renderTypeOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                    </select>
                    <span className="field-help">{optionDescription(renderTypeOptions, createBlockForm.render_type_id)}</span>
                  </label>
                  <label className="field-stack">
                    <span className="field-label">LaTeX template</span>
                    <input value={createBlockForm.latex_template} onChange={(event) => setCreateBlockForm((current) => ({ ...current, latex_template: event.target.value }))} placeholder="Optional export path" />
                  </label>
                </div>
                <div className="four-col">
                  <label className="field-stack">
                    <span className="field-label">Sort order</span>
                    <input value={createBlockForm.sort_index} onChange={(event) => setCreateBlockForm((current) => ({ ...current, sort_index: event.target.value }))} type="number" min={1} />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">Render order</span>
                    <input value={createBlockForm.render_order} onChange={(event) => setCreateBlockForm((current) => ({ ...current, render_order: event.target.value }))} type="number" min={1} />
                  </label>
                  <label className="checkbox-row"><input type="checkbox" checked={createBlockForm.is_editable} onChange={(event) => setCreateBlockForm((current) => ({ ...current, is_editable: event.target.checked }))} />Editable in protocol</label>
                  <label className="checkbox-row"><input type="checkbox" checked={createBlockForm.allows_multiple_values} onChange={(event) => setCreateBlockForm((current) => ({ ...current, allows_multiple_values: event.target.checked }))} />Multiple values</label>
                </div>
                <div className="four-col">
                  <label className="checkbox-row"><input type="checkbox" checked={createBlockForm.is_visible} onChange={(event) => setCreateBlockForm((current) => ({ ...current, is_visible: event.target.checked }))} />Visible</label>
                  <label className="checkbox-row"><input type="checkbox" checked={createBlockForm.export_visible} onChange={(event) => setCreateBlockForm((current) => ({ ...current, export_visible: event.target.checked }))} />Export visible</label>
                </div>
                <div className="table-toolbar-actions">
                  <button type="submit" className="button-inline">Add block</button>
                </div>
              </form>
            ) : null}

            <DataTable columns={["Block", "Type", "Subtitle", "Actions"]}>
              {selectedDefinition.blocks
                .slice()
                .sort((left, right) => left.sort_index - right.sort_index)
                .map((block) => (
                  <tr key={block.id} className={`table-row-clickable${selectedBlockId === block.id ? " table-row-active" : ""}`} onClick={() => {
                    setSelectedBlockId(block.id);
                    setBlockForm(blockFormFromBlock(block));
                  }}>
                    <td>
                      <strong>{block.title}</strong>
                      <div className="muted">Block #{block.id}</div>
                    </td>
                    <td>{optionLabel(elementTypeOptions, block.element_type_id)}</td>
                    <td>{block.block_title ?? "No subtitle"}</td>
                    <td>
                      <div className="table-actions">
                        <button type="button" className="button-inline button-danger" onClick={(event) => {
                          event.stopPropagation();
                          void deleteBlock(block.id);
                        }}>Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
            </DataTable>

            {selectedBlock ? (
              <form className="grid section-stack" onSubmit={updateBlock}>
                <div className="table-subtitle">Edit selected block</div>
                <div className="two-col">
                  <label className="field-stack">
                    <span className="field-label">Block name</span>
                    <input value={blockForm.title} onChange={(event) => setBlockForm((current) => ({ ...current, title: event.target.value }))} />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">Block subtitle</span>
                    <input value={blockForm.block_title} onChange={(event) => setBlockForm((current) => ({ ...current, block_title: event.target.value }))} placeholder="Optional subtitle" />
                  </label>
                </div>
                <div className="two-col">
                  <label className="field-stack">
                    <span className="field-label">Description</span>
                    <input value={blockForm.description} onChange={(event) => setBlockForm((current) => ({ ...current, description: event.target.value }))} />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">Default or fixed content</span>
                    <input value={blockForm.default_content} onChange={(event) => setBlockForm((current) => ({ ...current, default_content: event.target.value }))} />
                  </label>
                </div>
                <div className="three-col">
                  <label className="field-stack">
                    <span className="field-label">Block type</span>
                    <select value={blockForm.element_type_id} onChange={(event) => setBlockForm((current) => ({ ...current, element_type_id: event.target.value }))}>
                      {elementTypeOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                    </select>
                    <span className="field-help">{optionDescription(elementTypeOptions, blockForm.element_type_id)}</span>
                  </label>
                  <label className="field-stack">
                    <span className="field-label">Render style</span>
                    <select value={blockForm.render_type_id} onChange={(event) => setBlockForm((current) => ({ ...current, render_type_id: event.target.value }))}>
                      {renderTypeOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                    </select>
                    <span className="field-help">{optionDescription(renderTypeOptions, blockForm.render_type_id)}</span>
                  </label>
                  <label className="field-stack">
                    <span className="field-label">LaTeX template</span>
                    <input value={blockForm.latex_template} onChange={(event) => setBlockForm((current) => ({ ...current, latex_template: event.target.value }))} />
                  </label>
                </div>
                <div className="four-col">
                  <label className="field-stack">
                    <span className="field-label">Sort order</span>
                    <input value={blockForm.sort_index} onChange={(event) => setBlockForm((current) => ({ ...current, sort_index: event.target.value }))} type="number" min={1} />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">Render order</span>
                    <input value={blockForm.render_order} onChange={(event) => setBlockForm((current) => ({ ...current, render_order: event.target.value }))} type="number" min={1} />
                  </label>
                  <label className="checkbox-row"><input type="checkbox" checked={blockForm.is_editable} onChange={(event) => setBlockForm((current) => ({ ...current, is_editable: event.target.checked }))} />Editable in protocol</label>
                  <label className="checkbox-row"><input type="checkbox" checked={blockForm.allows_multiple_values} onChange={(event) => setBlockForm((current) => ({ ...current, allows_multiple_values: event.target.checked }))} />Multiple values</label>
                </div>
                <div className="four-col">
                  <label className="checkbox-row"><input type="checkbox" checked={blockForm.is_visible} onChange={(event) => setBlockForm((current) => ({ ...current, is_visible: event.target.checked }))} />Visible</label>
                  <label className="checkbox-row"><input type="checkbox" checked={blockForm.export_visible} onChange={(event) => setBlockForm((current) => ({ ...current, export_visible: event.target.checked }))} />Export visible</label>
                </div>
                <div className="table-toolbar-actions">
                  <button type="submit" className="button-inline">Save block</button>
                </div>
              </form>
            ) : null}
          </article>
        </>
      ) : null}
      </Modal>
    </div>
  );
}
