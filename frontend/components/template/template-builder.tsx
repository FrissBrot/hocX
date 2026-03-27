"use client";

import { FormEvent, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { ElementDefinition, TemplateElement, TemplateSummary } from "@/types/api";

type TemplateBuilderProps = {
  initialTemplates: TemplateSummary[];
};

type TemplateEditorProps = {
  initialTemplate: TemplateSummary;
  initialElements: TemplateElement[];
  initialDefinitions: ElementDefinition[];
};

type TemplateCreateState = {
  name: string;
  description: string;
  document_template_id: string;
};

type TemplateItemForm = {
  element_definition_id: string;
  sort_index: string;
};

const initialTemplateCreate: TemplateCreateState = {
  name: "",
  description: "",
  document_template_id: "1"
};

const initialTemplateItemForm: TemplateItemForm = {
  element_definition_id: "",
  sort_index: "10"
};

export function TemplateBuilder({ initialTemplates }: TemplateBuilderProps) {
  const router = useRouter();
  const [templates, setTemplates] = useState(initialTemplates);
  const [form, setForm] = useState(initialTemplateCreate);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [status, setStatus] = useState("Ready");
  const [statusTone, setStatusTone] = useState<"neutral" | "success" | "error">("neutral");
  const [search, setSearch] = useState("");

  const filteredTemplates = useMemo(
    () =>
      templates.filter((template) => {
        const haystack = `${template.name} ${template.description ?? ""}`.toLowerCase();
        return !search || haystack.includes(search.toLowerCase());
      }),
    [templates, search]
  );

  async function createTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("Creating template...");
    setStatusTone("neutral");

    try {
      const created = await browserApiFetch<TemplateSummary>("/api/templates", {
        method: "POST",
        body: JSON.stringify({
          tenant_id: 1,
          name: form.name,
          description: form.description || null,
          version: 1,
          status: "active",
          document_template_id: Number(form.document_template_id),
          created_by: null
        })
      });
      setTemplates((current) => [created, ...current]);
      setForm(initialTemplateCreate);
      setShowCreateForm(false);
      setStatus(`Created template #${created.id}`);
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Template creation failed");
      setStatusTone("error");
    }
  }

  async function deleteTemplate(templateId: number) {
    setStatus(`Deleting template #${templateId}...`);
    setStatusTone("neutral");
    try {
      await browserApiFetch(`/api/templates/${templateId}`, { method: "DELETE" });
      setTemplates((current) => current.filter((template) => template.id !== templateId));
      setStatus(`Deleted template #${templateId}`);
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Template deletion failed");
      setStatusTone("error");
    }
  }

  return (
    <div className="grid">
      <DataToolbar
        title="Templates"
        description="Templates are slim containers: they select finished elements and decide order only."
        actions={
          <button type="button" className="button-inline" onClick={() => setShowCreateForm((current) => !current)}>
            {showCreateForm ? "Close create form" : "New template"}
          </button>
        }
      />

      <Modal
        open={showCreateForm}
        onClose={() => setShowCreateForm(false)}
        title="Create template"
        description="Create a fresh template shell, then assign reusable elements to it."
      >
        <form className="grid" onSubmit={createTemplate}>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Template name</span>
              <input value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} placeholder="Template name" required />
            </label>
            <label className="field-stack">
              <span className="field-label">Document template ID</span>
              <input value={form.document_template_id} onChange={(event) => setForm((current) => ({ ...current, document_template_id: event.target.value }))} type="number" min={1} />
            </label>
          </div>
          <label className="field-stack">
            <span className="field-label">Description</span>
            <textarea rows={4} value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} placeholder="Description" />
          </label>
          <div className="table-toolbar-actions">
            <button type="submit" className="button-inline">Create template</button>
          </div>
        </form>
      </Modal>

      <article className="card">
        <div className="two-col">
          <label className="field-stack">
            <span className="field-label">Search</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search templates" />
          </label>
          <div className="card">
            <div className="eyebrow">Overview</div>
            <div className="status-row">
              <span className="pill">{filteredTemplates.length} visible</span>
              <span className="pill">{templates.length} total</span>
            </div>
          </div>
        </div>
      </article>

      <StatusBanner tone={statusTone} message={status} />

      <DataTable columns={["Template", "Description", "Version", "Actions"]}>
        {filteredTemplates.map((template) => (
          <tr key={template.id} className="table-row-clickable" onClick={() => router.push(`/templates/${template.id}`)}>
            <td>
              <strong>{template.name}</strong>
              <div className="muted">Template #{template.id}</div>
            </td>
            <td>{template.description ?? "No description"}</td>
            <td>{template.version}</td>
            <td>
              <div className="table-actions">
                <button type="button" className="button-inline button-danger" onClick={(event) => {
                  event.stopPropagation();
                  void deleteTemplate(template.id);
                }}>Delete</button>
              </div>
            </td>
          </tr>
        ))}
      </DataTable>
    </div>
  );
}

export function TemplateEditor({ initialTemplate, initialElements, initialDefinitions }: TemplateEditorProps) {
  const [template, setTemplate] = useState(initialTemplate);
  const [elements, setElements] = useState(initialElements);
  const [templateMeta, setTemplateMeta] = useState({
    name: initialTemplate.name,
    description: initialTemplate.description ?? "",
    status: initialTemplate.status,
    document_template_id: String(initialTemplate.document_template_id ?? 1)
  });
  const [newItemForm, setNewItemForm] = useState<TemplateItemForm>({
    ...initialTemplateItemForm,
    element_definition_id: initialDefinitions[0] ? String(initialDefinitions[0].id) : ""
  });
  const [showCreateItem, setShowCreateItem] = useState(false);
  const [status, setStatus] = useState("Ready");
  const [statusTone, setStatusTone] = useState<"neutral" | "success" | "error">("neutral");

  const definitionById = useMemo(
    () => new Map(initialDefinitions.map((definition) => [definition.id, definition])),
    [initialDefinitions]
  );

  async function saveTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("Saving template...");
    setStatusTone("neutral");
    try {
      const updated = await browserApiFetch<TemplateSummary>(`/api/templates/${template.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: templateMeta.name,
          description: templateMeta.description || null,
          status: templateMeta.status,
          document_template_id: Number(templateMeta.document_template_id)
        })
      });
      setTemplate(updated);
      setStatus("Template saved");
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Template save failed");
      setStatusTone("error");
    }
  }

  async function addElementToTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("Adding element to template...");
    setStatusTone("neutral");
    try {
      const created = await browserApiFetch<TemplateElement>(`/api/templates/${template.id}/elements`, {
        method: "POST",
        body: JSON.stringify({
          element_definition_id: Number(newItemForm.element_definition_id),
          sort_index: Number(newItemForm.sort_index)
        })
      });
      setElements((current) => [...current, created].sort((left, right) => left.sort_index - right.sort_index));
      setNewItemForm({
        ...initialTemplateItemForm,
        element_definition_id: initialDefinitions[0] ? String(initialDefinitions[0].id) : ""
      });
      setShowCreateItem(false);
      setStatus("Element added to template");
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Template element creation failed");
      setStatusTone("error");
    }
  }

  async function updateTemplateItemSort(templateElementId: number, sortIndex: number) {
    setStatus("Saving template order...");
    setStatusTone("neutral");
    try {
      const updated = await browserApiFetch<TemplateElement>(`/api/template-elements/${templateElementId}`, {
        method: "PATCH",
        body: JSON.stringify({ sort_index: sortIndex })
      });
      setElements((current) => current.map((item) => (item.id === updated.id ? updated : item)).sort((left, right) => left.sort_index - right.sort_index));
      setStatus("Template order saved");
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Template order update failed");
      setStatusTone("error");
    }
  }

  async function deleteTemplateItem(templateElementId: number) {
    setStatus("Removing element from template...");
    setStatusTone("neutral");
    try {
      await browserApiFetch(`/api/template-elements/${templateElementId}`, { method: "DELETE" });
      setElements((current) => current.filter((item) => item.id !== templateElementId));
      setStatus("Element removed from template");
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Template element deletion failed");
      setStatusTone("error");
    }
  }

  return (
    <div className="grid">
      <StatusBanner tone={statusTone} message={status} />

      <article className="card">
        <DataToolbar title="Template settings" description="General information about this template and the document layout it uses." />
        <form className="grid" onSubmit={saveTemplate}>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Template name</span>
              <input value={templateMeta.name} onChange={(event) => setTemplateMeta((current) => ({ ...current, name: event.target.value }))} />
            </label>
            <label className="field-stack">
              <span className="field-label">Document template ID</span>
              <input value={templateMeta.document_template_id} onChange={(event) => setTemplateMeta((current) => ({ ...current, document_template_id: event.target.value }))} type="number" min={1} />
            </label>
          </div>
          <label className="field-stack">
            <span className="field-label">Description</span>
            <textarea rows={4} value={templateMeta.description} onChange={(event) => setTemplateMeta((current) => ({ ...current, description: event.target.value }))} />
          </label>
          <label className="field-stack">
            <span className="field-label">Template status</span>
            <select value={templateMeta.status} onChange={(event) => setTemplateMeta((current) => ({ ...current, status: event.target.value }))}>
              <option value="active">Active</option>
              <option value="archived">Archived</option>
            </select>
          </label>
          <div className="table-toolbar-actions">
            <button type="submit" className="button-inline">Save template</button>
          </div>
        </form>
      </article>

      <article className="card">
        <div className="eyebrow">How templates work now</div>
        <p className="muted">Templates no longer build blocks themselves. They only choose ready-made elements from the Elements area and place them in order.</p>
      </article>

      <article className="card">
        <DataToolbar
          title="Template elements"
          description="Use the navigator below instead of scrolling through many nested forms."
          actions={
            <button type="button" className="button-inline" onClick={() => setShowCreateItem((current) => !current)}>
              {showCreateItem ? "Close create form" : "Add element"}
            </button>
          }
        />

        <Modal
          open={showCreateItem}
          onClose={() => setShowCreateItem(false)}
          title="Add element to template"
          description="Pick a reusable element and place it in the flow order for this template."
        >
          <form className="grid" onSubmit={addElementToTemplate}>
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">Element</span>
                <select value={newItemForm.element_definition_id} onChange={(event) => setNewItemForm((current) => ({ ...current, element_definition_id: event.target.value }))}>
                  {initialDefinitions.map((definition) => (
                    <option key={definition.id} value={definition.id}>
                      {definition.title} ({definition.blocks.length} blocks)
                    </option>
                  ))}
                </select>
              </label>
              <label className="field-stack">
                <span className="field-label">Sort order</span>
                <input value={newItemForm.sort_index} onChange={(event) => setNewItemForm((current) => ({ ...current, sort_index: event.target.value }))} type="number" min={1} />
              </label>
            </div>
            <div className="table-toolbar-actions">
              <button type="submit" className="button-inline">Add element</button>
            </div>
          </form>
        </Modal>

        <DataTable columns={["Element", "Blocks", "Order", "Actions"]}>
          {elements.map((item) => (
            <tr key={item.id}>
              <td>
                <strong>{item.title}</strong>
                <div className="muted">{item.description ?? "No description"}</div>
              </td>
              <td>{item.blocks.length} block{item.blocks.length === 1 ? "" : "s"}</td>
              <td>
                <input
                  type="number"
                  min={1}
                  defaultValue={item.sort_index}
                  onBlur={(event) => {
                    const nextValue = Number(event.target.value);
                    if (!Number.isNaN(nextValue) && nextValue !== item.sort_index) {
                      void updateTemplateItemSort(item.id, nextValue);
                    }
                  }}
                />
              </td>
              <td>
                <div className="table-actions">
                  <button type="button" className="button-inline button-danger" onClick={() => void deleteTemplateItem(item.id)}>Remove</button>
                </div>
              </td>
            </tr>
          ))}
        </DataTable>

        {elements.length > 0 ? (
          <div className="section-stack">
            <div className="table-subtitle">Preview of selected elements</div>
            <div className="grid">
              {elements.map((item) => (
                <article className="card" key={item.id}>
                  <strong>{item.title}</strong>
                  <p className="muted">{item.description ?? "No description"}</p>
                  <div className="table-pill-wrap">
                    {item.blocks.map((block) => (
                      <span className="pill" key={`${item.id}-${block.id}`}>{block.block_title || block.title}</span>
                    ))}
                  </div>
                </article>
              ))}
            </div>
          </div>
        ) : null}
      </article>
    </div>
  );
}
