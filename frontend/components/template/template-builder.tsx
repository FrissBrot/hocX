"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { StatusBanner } from "@/components/ui/status-banner";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { browserApiFetch } from "@/lib/api/client";
import { ElementDefinition, TemplateElement, TemplateSummary } from "@/types/api";

type TemplateBuilderProps = {
  initialTemplates: TemplateSummary[];
};

type BuilderState = {
  name: string;
  description: string;
  document_template_id: string;
};

type TemplateEditorProps = {
  initialTemplate: TemplateSummary;
  initialElements: TemplateElement[];
  initialDefinitions: ElementDefinition[];
};

type TemplateFormState = {
  name: string;
  description: string;
  status: string;
  document_template_id: string;
};

type TemplateElementFormState = {
  element_definition_id: string;
  sort_index: string;
  render_order: string;
  section_name: string;
  section_order: string;
  heading_text: string;
  is_required: boolean;
  is_visible: boolean;
  export_visible: boolean;
};

type DefinitionFormState = {
  title: string;
  description: string;
  element_type_id: string;
  render_type_id: string;
  is_active: boolean;
};

const initialState: BuilderState = {
  name: "",
  description: "",
  document_template_id: "1"
};

const initialDefinitionForm: DefinitionFormState = {
  title: "",
  description: "",
  element_type_id: "1",
  render_type_id: "2",
  is_active: true
};

const initialElementForm: TemplateElementFormState = {
  element_definition_id: "",
  sort_index: "10",
  render_order: "10",
  section_name: "",
  section_order: "1",
  heading_text: "",
  is_required: false,
  is_visible: true,
  export_visible: true
};

function buttonLabel(open: boolean, idleLabel: string, openLabel: string) {
  return open ? openLabel : idleLabel;
}

export function TemplateBuilder({ initialTemplates }: TemplateBuilderProps) {
  const router = useRouter();
  const [templates, setTemplates] = useState(initialTemplates);
  const [form, setForm] = useState(initialState);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [status, setStatus] = useState<string>("Ready");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [statusTone, setStatusTone] = useState<"neutral" | "success" | "error">("neutral");

  const sortedTemplates = useMemo(
    () =>
      [...templates]
        .filter((template) => {
          const matchesSearch =
            !search ||
            template.name.toLowerCase().includes(search.toLowerCase()) ||
            (template.description ?? "").toLowerCase().includes(search.toLowerCase());
          const matchesStatus = statusFilter === "all" || template.status === statusFilter;
          return matchesSearch && matchesStatus;
        })
        .sort((left, right) => right.id - left.id),
    [templates, search, statusFilter]
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
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
      setForm(initialState);
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
      await browserApiFetch<{ message: string }>(`/api/templates/${templateId}`, {
        method: "DELETE"
      });
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
        description="Manage your templates in a single table. Click a row to open the editor."
        actions={
          <button type="button" className="button-inline" onClick={() => setShowCreateForm((current) => !current)}>
            {buttonLabel(showCreateForm, "New template", "Close create form")}
          </button>
        }
      />

      {showCreateForm ? (
        <article className="card">
          <div className="eyebrow">Create Template</div>
          <form className="grid" onSubmit={handleSubmit}>
            <div className="two-col">
              <input
                placeholder="Template name"
                value={form.name}
                onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                required
              />
              <input
                placeholder="Document template id"
                type="number"
                min={1}
                value={form.document_template_id}
                onChange={(event) => setForm((current) => ({ ...current, document_template_id: event.target.value }))}
              />
            </div>
            <textarea
              rows={4}
              placeholder="Short description"
              value={form.description}
              onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
            />
            <div className="table-toolbar-actions">
              <button type="submit" className="button-inline">
                Create template
              </button>
            </div>
          </form>
        </article>
      ) : null}

      <article className="card">
        <div className="eyebrow">Filter</div>
        <div className="two-col">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search by name or description"
          />
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="all">All statuses</option>
            <option value="active">Active</option>
            <option value="archived">Archived</option>
          </select>
        </div>
      </article>

      <StatusBanner tone={statusTone} message={status} />

      <DataTable columns={["Name", "Description", "Version", "Status", "Actions"]}>
        {sortedTemplates.map((item) => (
          <tr key={item.id} className="table-row-clickable" onClick={() => router.push(`/templates/${item.id}`)}>
            <td>
              <strong>{item.name}</strong>
              <div className="muted">Template #{item.id}</div>
            </td>
            <td>{item.description ?? "No description"}</td>
            <td>{item.version}</td>
            <td>
              <span className="pill">{item.status}</span>
            </td>
            <td>
              <div className="table-actions">
                <button
                  type="button"
                  className="button-inline button-danger"
                  onClick={(event) => {
                    event.stopPropagation();
                    void deleteTemplate(item.id);
                  }}
                >
                  Delete
                </button>
              </div>
            </td>
          </tr>
        ))}
      </DataTable>

      {sortedTemplates.length === 0 ? <p className="muted">No templates found for the current filter.</p> : null}
    </div>
  );
}

function elementFormFromRow(row: TemplateElement): TemplateElementFormState {
  return {
    element_definition_id: String(row.element_definition_id),
    sort_index: String(row.sort_index),
    render_order: String(row.render_order ?? row.sort_index),
    section_name: row.section_name ?? "",
    section_order: String(row.section_order ?? 1),
    heading_text: row.heading_text ?? "",
    is_required: row.is_required,
    is_visible: row.is_visible,
    export_visible: row.export_visible
  };
}

function definitionFormFromRow(row: ElementDefinition): DefinitionFormState {
  return {
    title: row.title,
    description: row.description ?? "",
    element_type_id: String(row.element_type_id),
    render_type_id: String(row.render_type_id),
    is_active: row.is_active
  };
}

export function TemplateEditor({
  initialTemplate,
  initialElements,
  initialDefinitions
}: TemplateEditorProps) {
  const [template, setTemplate] = useState(initialTemplate);
  const [templateForm, setTemplateForm] = useState<TemplateFormState>({
    name: initialTemplate.name,
    description: initialTemplate.description ?? "",
    status: initialTemplate.status,
    document_template_id: String(initialTemplate.document_template_id ?? 1)
  });
  const [elements, setElements] = useState(initialElements);
  const [definitions, setDefinitions] = useState(initialDefinitions);
  const [selectedElementId, setSelectedElementId] = useState<number | null>(initialElements[0]?.id ?? null);
  const [selectedDefinitionId, setSelectedDefinitionId] = useState<number | null>(initialDefinitions[0]?.id ?? null);
  const [elementForm, setElementForm] = useState<TemplateElementFormState>(
    initialElements[0] ? elementFormFromRow(initialElements[0]) : initialElementForm
  );
  const [definitionForm, setDefinitionForm] = useState<DefinitionFormState>(
    initialDefinitions[0] ? definitionFormFromRow(initialDefinitions[0]) : initialDefinitionForm
  );
  const [createDefinitionForm, setCreateDefinitionForm] = useState<DefinitionFormState>(initialDefinitionForm);
  const [newElementForm, setNewElementForm] = useState<TemplateElementFormState>({
    ...initialElementForm,
    element_definition_id: initialDefinitions[0] ? String(initialDefinitions[0].id) : ""
  });
  const [showCreateDefinition, setShowCreateDefinition] = useState(false);
  const [showAddElement, setShowAddElement] = useState(false);
  const [status, setStatus] = useState<string>("Ready");
  const [statusTone, setStatusTone] = useState<"neutral" | "success" | "error">("neutral");

  const definitionById = useMemo(
    () => new Map(definitions.map((definition) => [definition.id, definition])),
    [definitions]
  );

  const selectedDefinition = useMemo(
    () => definitions.find((definition) => definition.id === selectedDefinitionId) ?? null,
    [definitions, selectedDefinitionId]
  );
  const selectedElement = useMemo(
    () => elements.find((element) => element.id === selectedElementId) ?? null,
    [elements, selectedElementId]
  );

  useEffect(() => {
    if (selectedDefinition) {
      setDefinitionForm(definitionFormFromRow(selectedDefinition));
    }
  }, [selectedDefinition]);

  useEffect(() => {
    if (selectedElement) {
      setElementForm(elementFormFromRow(selectedElement));
    }
  }, [selectedElement]);

  async function saveTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("Saving template...");
    setStatusTone("neutral");

    try {
      const updated = await browserApiFetch<TemplateSummary>(`/api/templates/${template.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: templateForm.name,
          description: templateForm.description || null,
          status: templateForm.status,
          document_template_id: Number(templateForm.document_template_id)
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

  async function createDefinition(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("Creating element definition...");
    setStatusTone("neutral");

    try {
      const created = await browserApiFetch<ElementDefinition>("/api/element-definitions", {
        method: "POST",
        body: JSON.stringify({
          tenant_id: 1,
          element_type_id: Number(createDefinitionForm.element_type_id),
          render_type_id: Number(createDefinitionForm.render_type_id),
          title: createDefinitionForm.title,
          description: createDefinitionForm.description || null,
          is_editable: true,
          allows_multiple_values: false,
          export_visible: true,
          latex_template: null,
          configuration_json: {},
          is_active: createDefinitionForm.is_active
        })
      });

      setDefinitions((current) => [created, ...current]);
      setSelectedDefinitionId(created.id);
      setNewElementForm((current) => ({ ...current, element_definition_id: String(created.id) }));
      setCreateDefinitionForm(initialDefinitionForm);
      setShowCreateDefinition(false);
      setStatus(`Created element definition #${created.id}`);
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Element definition creation failed");
      setStatusTone("error");
    }
  }

  async function saveDefinition(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedDefinition) {
      return;
    }
    setStatus(`Saving definition #${selectedDefinition.id}...`);
    setStatusTone("neutral");

    try {
      const updated = await browserApiFetch<ElementDefinition>(`/api/element-definitions/${selectedDefinition.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: definitionForm.title,
          description: definitionForm.description || null,
          element_type_id: Number(definitionForm.element_type_id),
          render_type_id: Number(definitionForm.render_type_id),
          is_active: definitionForm.is_active
        })
      });
      setDefinitions((current) => current.map((definition) => (definition.id === updated.id ? updated : definition)));
      setStatus(`Saved definition #${updated.id}`);
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Definition update failed");
      setStatusTone("error");
    }
  }

  async function deleteDefinition(definitionId: number) {
    setStatus(`Deleting definition #${definitionId}...`);
    setStatusTone("neutral");

    try {
      await browserApiFetch<{ message: string }>(`/api/element-definitions/${definitionId}`, {
        method: "DELETE"
      });
      const nextDefinitions = definitions.filter((definition) => definition.id !== definitionId);
      setDefinitions(nextDefinitions);
      setSelectedDefinitionId(nextDefinitions[0]?.id ?? null);
      setStatus(`Deleted definition #${definitionId}`);
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Definition deletion failed");
      setStatusTone("error");
    }
  }

  async function addElement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("Adding template element...");
    setStatusTone("neutral");

    try {
      const created = await browserApiFetch<TemplateElement>(`/api/templates/${template.id}/elements`, {
        method: "POST",
        body: JSON.stringify({
          element_definition_id: Number(newElementForm.element_definition_id),
          sort_index: Number(newElementForm.sort_index),
          render_order: Number(newElementForm.render_order),
          section_name: newElementForm.section_name || null,
          section_order: Number(newElementForm.section_order),
          heading_text: newElementForm.heading_text || null,
          is_required: newElementForm.is_required,
          is_visible: newElementForm.is_visible,
          export_visible: newElementForm.export_visible,
          configuration_override_json: {}
        })
      });

      const nextElements = [...elements, created].sort((left, right) => left.sort_index - right.sort_index);
      setElements(nextElements);
      setSelectedElementId(created.id);
      setShowAddElement(false);
      setStatus(`Added template element #${created.id}`);
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Adding template element failed");
      setStatusTone("error");
    }
  }

  async function saveElement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedElement) {
      return;
    }
    setStatus(`Saving element #${selectedElement.id}...`);
    setStatusTone("neutral");

    try {
      const updated = await browserApiFetch<TemplateElement>(`/api/template-elements/${selectedElement.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          element_definition_id: Number(elementForm.element_definition_id),
          sort_index: Number(elementForm.sort_index),
          render_order: Number(elementForm.render_order),
          section_name: elementForm.section_name || null,
          section_order: Number(elementForm.section_order),
          heading_text: elementForm.heading_text || null,
          is_required: elementForm.is_required,
          is_visible: elementForm.is_visible,
          export_visible: elementForm.export_visible
        })
      });
      const nextElements = elements
        .map((element) => (element.id === updated.id ? updated : element))
        .sort((left, right) => left.sort_index - right.sort_index);
      setElements(nextElements);
      setStatus(`Saved element #${updated.id}`);
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Element update failed");
      setStatusTone("error");
    }
  }

  async function deleteElement(elementId: number) {
    setStatus(`Deleting element #${elementId}...`);
    setStatusTone("neutral");

    try {
      await browserApiFetch<{ message: string }>(`/api/template-elements/${elementId}`, {
        method: "DELETE"
      });
      const nextElements = elements.filter((element) => element.id !== elementId);
      setElements(nextElements);
      setSelectedElementId(nextElements[0]?.id ?? null);
      setStatus(`Deleted element #${elementId}`);
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Element deletion failed");
      setStatusTone("error");
    }
  }

  return (
    <div className="grid">
      <div className="status-row">
        <span className="pill">Template #{template.id}</span>
        <span className="pill">Status: {template.status}</span>
      </div>
      <StatusBanner tone={statusTone} message={status} />

      <article className="card">
        <DataToolbar title="Template settings" description="Update the main metadata for this template." />
        <form className="grid" onSubmit={saveTemplate}>
          <div className="two-col">
            <input
              value={templateForm.name}
              onChange={(event) => setTemplateForm((current) => ({ ...current, name: event.target.value }))}
            />
            <input
              type="number"
              min={1}
              value={templateForm.document_template_id}
              onChange={(event) =>
                setTemplateForm((current) => ({ ...current, document_template_id: event.target.value }))
              }
            />
          </div>
          <textarea
            rows={4}
            value={templateForm.description}
            onChange={(event) => setTemplateForm((current) => ({ ...current, description: event.target.value }))}
          />
          <select value={templateForm.status} onChange={(event) => setTemplateForm((current) => ({ ...current, status: event.target.value }))}>
            <option value="active">Active</option>
            <option value="archived">Archived</option>
          </select>
          <div className="table-toolbar-actions">
            <button type="submit" className="button-inline">
              Save template
            </button>
          </div>
        </form>
      </article>

      <article className="card">
        <DataToolbar
          title="Element definitions"
          description="Reusable definitions used by template elements. Click a row to edit it."
          actions={
            <button
              type="button"
              className="button-inline"
              onClick={() => setShowCreateDefinition((current) => !current)}
            >
              {buttonLabel(showCreateDefinition, "New definition", "Close create form")}
            </button>
          }
        />

        {showCreateDefinition ? (
          <form className="grid section-stack" onSubmit={createDefinition}>
            <div className="two-col">
              <input
                value={createDefinitionForm.title}
                onChange={(event) =>
                  setCreateDefinitionForm((current) => ({ ...current, title: event.target.value }))
                }
                placeholder="Definition title"
                required
              />
              <input
                value={createDefinitionForm.description}
                onChange={(event) =>
                  setCreateDefinitionForm((current) => ({ ...current, description: event.target.value }))
                }
                placeholder="Definition description"
              />
            </div>
            <div className="three-col">
              <input
                type="number"
                min={1}
                value={createDefinitionForm.element_type_id}
                onChange={(event) =>
                  setCreateDefinitionForm((current) => ({ ...current, element_type_id: event.target.value }))
                }
                placeholder="Element type id"
              />
              <input
                type="number"
                min={1}
                value={createDefinitionForm.render_type_id}
                onChange={(event) =>
                  setCreateDefinitionForm((current) => ({ ...current, render_type_id: event.target.value }))
                }
                placeholder="Render type id"
              />
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={createDefinitionForm.is_active}
                  onChange={(event) =>
                    setCreateDefinitionForm((current) => ({ ...current, is_active: event.target.checked }))
                  }
                />
                Active
              </label>
            </div>
            <div className="table-toolbar-actions">
              <button type="submit" className="button-inline">
                Create definition
              </button>
            </div>
          </form>
        ) : null}

        <DataTable columns={["Title", "Type", "Render", "State", "Actions"]}>
          {definitions.map((definition) => (
            <tr
              key={definition.id}
              className={`table-row-clickable${selectedDefinitionId === definition.id ? " table-row-active" : ""}`}
              onClick={() => setSelectedDefinitionId(definition.id)}
            >
              <td>
                <strong>{definition.title}</strong>
                <div className="muted">Definition #{definition.id}</div>
              </td>
              <td>{definition.element_type_id}</td>
              <td>{definition.render_type_id}</td>
              <td>
                <span className="pill">{definition.is_active ? "active" : "inactive"}</span>
              </td>
              <td>
                <div className="table-actions">
                  <button
                    type="button"
                    className="button-inline button-danger"
                    onClick={(event) => {
                      event.stopPropagation();
                      void deleteDefinition(definition.id);
                    }}
                  >
                    Delete
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </DataTable>

        {selectedDefinition ? (
          <form className="grid section-stack" onSubmit={saveDefinition}>
            <div className="table-subtitle">Edit definition #{selectedDefinition.id}</div>
            <div className="two-col">
              <input
                value={definitionForm.title}
                onChange={(event) => setDefinitionForm((current) => ({ ...current, title: event.target.value }))}
              />
              <input
                value={definitionForm.description}
                onChange={(event) =>
                  setDefinitionForm((current) => ({ ...current, description: event.target.value }))
                }
              />
            </div>
            <div className="three-col">
              <input
                type="number"
                min={1}
                value={definitionForm.element_type_id}
                onChange={(event) =>
                  setDefinitionForm((current) => ({ ...current, element_type_id: event.target.value }))
                }
              />
              <input
                type="number"
                min={1}
                value={definitionForm.render_type_id}
                onChange={(event) =>
                  setDefinitionForm((current) => ({ ...current, render_type_id: event.target.value }))
                }
              />
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={definitionForm.is_active}
                  onChange={(event) =>
                    setDefinitionForm((current) => ({ ...current, is_active: event.target.checked }))
                  }
                />
                Active
              </label>
            </div>
            <div className="table-toolbar-actions">
              <button type="submit" className="button-inline">
                Save definition
              </button>
            </div>
          </form>
        ) : null}
      </article>

      <article className="card">
        <DataToolbar
          title="Template elements"
          description="Assigned structure blocks for this template. Click a row to edit it."
          actions={
            <button type="button" className="button-inline" onClick={() => setShowAddElement((current) => !current)}>
              {buttonLabel(showAddElement, "New element", "Close create form")}
            </button>
          }
        />

        {showAddElement ? (
          <form className="grid section-stack" onSubmit={addElement}>
            <div className="two-col">
              <select
                value={newElementForm.element_definition_id}
                onChange={(event) =>
                  setNewElementForm((current) => ({ ...current, element_definition_id: event.target.value }))
                }
              >
                {definitions.map((definition) => (
                  <option key={definition.id} value={definition.id}>
                    #{definition.id} {definition.title}
                  </option>
                ))}
              </select>
              <input
                value={newElementForm.heading_text}
                onChange={(event) => setNewElementForm((current) => ({ ...current, heading_text: event.target.value }))}
                placeholder="Heading text"
              />
            </div>
            <div className="four-col">
              <input
                type="number"
                min={1}
                value={newElementForm.sort_index}
                onChange={(event) => setNewElementForm((current) => ({ ...current, sort_index: event.target.value }))}
                placeholder="Sort index"
              />
              <input
                type="number"
                min={1}
                value={newElementForm.render_order}
                onChange={(event) =>
                  setNewElementForm((current) => ({ ...current, render_order: event.target.value }))
                }
                placeholder="Render order"
              />
              <input
                value={newElementForm.section_name}
                onChange={(event) => setNewElementForm((current) => ({ ...current, section_name: event.target.value }))}
                placeholder="Section name"
              />
              <input
                type="number"
                min={1}
                value={newElementForm.section_order}
                onChange={(event) =>
                  setNewElementForm((current) => ({ ...current, section_order: event.target.value }))
                }
                placeholder="Section order"
              />
            </div>
            <div className="three-col">
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={newElementForm.is_required}
                  onChange={(event) =>
                    setNewElementForm((current) => ({ ...current, is_required: event.target.checked }))
                  }
                />
                Required
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={newElementForm.is_visible}
                  onChange={(event) =>
                    setNewElementForm((current) => ({ ...current, is_visible: event.target.checked }))
                  }
                />
                Visible
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={newElementForm.export_visible}
                  onChange={(event) =>
                    setNewElementForm((current) => ({ ...current, export_visible: event.target.checked }))
                  }
                />
                Export visible
              </label>
            </div>
            <div className="table-toolbar-actions">
              <button type="submit" className="button-inline" disabled={!newElementForm.element_definition_id}>
                Add element
              </button>
            </div>
          </form>
        ) : null}

        <DataTable columns={["Definition", "Sort", "Section", "Flags", "Actions"]}>
          {elements.map((element) => {
            const definition = definitionById.get(element.element_definition_id);
            return (
              <tr
                key={element.id}
                className={`table-row-clickable${selectedElementId === element.id ? " table-row-active" : ""}`}
                onClick={() => setSelectedElementId(element.id)}
              >
                <td>
                  <strong>{definition?.title ?? `Definition #${element.element_definition_id}`}</strong>
                  <div className="muted">Element #{element.id}</div>
                </td>
                <td>
                  {element.sort_index}
                  <div className="muted">render {element.render_order ?? element.sort_index}</div>
                </td>
                <td>
                  {element.section_name ?? "No section"}
                  <div className="muted">order {element.section_order ?? "-"}</div>
                </td>
                <td>
                  <div className="table-pill-wrap">
                    <span className="pill">{element.is_required ? "required" : "optional"}</span>
                    <span className="pill">{element.is_visible ? "visible" : "hidden"}</span>
                    <span className="pill">{element.export_visible ? "export" : "no export"}</span>
                  </div>
                </td>
                <td>
                  <div className="table-actions">
                    <button
                      type="button"
                      className="button-inline button-danger"
                      onClick={(event) => {
                        event.stopPropagation();
                        void deleteElement(element.id);
                      }}
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            );
          })}
        </DataTable>

        {selectedElement ? (
          <form className="grid section-stack" onSubmit={saveElement}>
            <div className="table-subtitle">Edit element #{selectedElement.id}</div>
            <div className="two-col">
              <select
                value={elementForm.element_definition_id}
                onChange={(event) => setElementForm((current) => ({ ...current, element_definition_id: event.target.value }))}
              >
                {definitions.map((definition) => (
                  <option key={definition.id} value={definition.id}>
                    #{definition.id} {definition.title}
                  </option>
                ))}
              </select>
              <input
                value={elementForm.heading_text}
                onChange={(event) => setElementForm((current) => ({ ...current, heading_text: event.target.value }))}
                placeholder="Heading text"
              />
            </div>
            <div className="four-col">
              <input
                type="number"
                min={1}
                value={elementForm.sort_index}
                onChange={(event) => setElementForm((current) => ({ ...current, sort_index: event.target.value }))}
              />
              <input
                type="number"
                min={1}
                value={elementForm.render_order}
                onChange={(event) => setElementForm((current) => ({ ...current, render_order: event.target.value }))}
              />
              <input
                value={elementForm.section_name}
                onChange={(event) => setElementForm((current) => ({ ...current, section_name: event.target.value }))}
                placeholder="Section name"
              />
              <input
                type="number"
                min={1}
                value={elementForm.section_order}
                onChange={(event) => setElementForm((current) => ({ ...current, section_order: event.target.value }))}
              />
            </div>
            <div className="three-col">
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={elementForm.is_required}
                  onChange={(event) => setElementForm((current) => ({ ...current, is_required: event.target.checked }))}
                />
                Required
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={elementForm.is_visible}
                  onChange={(event) => setElementForm((current) => ({ ...current, is_visible: event.target.checked }))}
                />
                Visible
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={elementForm.export_visible}
                  onChange={(event) =>
                    setElementForm((current) => ({ ...current, export_visible: event.target.checked }))
                  }
                />
                Export visible
              </label>
            </div>
            <div className="table-toolbar-actions">
              <button type="submit" className="button-inline">
                Save element
              </button>
            </div>
          </form>
        ) : null}
      </article>
    </div>
  );
}
