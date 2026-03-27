"use client";

import { FormEvent, useMemo, useState } from "react";

import { browserApiFetch } from "@/lib/api/client";
import { StatusBanner } from "@/components/ui/status-banner";
import { ElementDefinition, TemplateElement, TemplateSummary } from "@/types/api";

type TemplateBuilderProps = {
  initialTemplates: TemplateSummary[];
};

type BuilderState = {
  name: string;
  description: string;
  document_template_id: string;
};

const initialState: BuilderState = {
  name: "",
  description: "",
  document_template_id: "1"
};

export function TemplateBuilder({ initialTemplates }: TemplateBuilderProps) {
  const [templates, setTemplates] = useState(initialTemplates);
  const [form, setForm] = useState(initialState);
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
      setStatus(`Created template #${created.id}`);
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Template creation failed");
      setStatusTone("error");
    }
  }

  return (
    <div className="grid">
      <article className="card">
        <div className="eyebrow">Create Template</div>
        <h3>Start a new template</h3>
        <form className="grid" onSubmit={handleSubmit}>
          <input
            placeholder="Template name"
            value={form.name}
            onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
            required
          />
          <textarea
            rows={4}
            placeholder="Short description"
            value={form.description}
            onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
          />
          <input
            placeholder="Document template id"
            type="number"
            min={1}
            value={form.document_template_id}
            onChange={(event) => setForm((current) => ({ ...current, document_template_id: event.target.value }))}
          />
          <button type="submit">Create template</button>
        </form>
        <StatusBanner tone={statusTone} message={status} />
      </article>

      <article className="card">
        <div className="eyebrow">Builder Scope</div>
        <h3>What this UI already supports</h3>
        <p className="muted">
          Create templates, inspect existing ones, and open the detail builder to manage structure and element
          assignment.
        </p>
      </article>

      <article className="card">
        <div className="eyebrow">Filter</div>
        <h3>Search existing templates</h3>
        <div className="two-col">
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search by name or description" />
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="all">All statuses</option>
            <option value="active">Active</option>
            <option value="archived">Archived</option>
          </select>
        </div>
      </article>

      <div className="grid">
        {sortedTemplates.map((item) => (
          <article className="card" key={item.id}>
            <div className="eyebrow">Template #{item.id}</div>
            <h3>{item.name}</h3>
            <p className="muted">
              Version {item.version} · {item.status}
            </p>
            <p className="muted">{item.description ?? "No description yet."}</p>
            <a href={`/templates/${item.id}`}>Open template builder</a>
          </article>
        ))}
      </div>
    </div>
  );
}

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
  const [elementForm, setElementForm] = useState<TemplateElementFormState>({
    ...initialElementForm,
    element_definition_id: initialDefinitions[0] ? String(initialDefinitions[0].id) : ""
  });
  const [definitionForm, setDefinitionForm] = useState<DefinitionFormState>({
    title: "",
    description: "",
    element_type_id: "1",
    render_type_id: "2"
  });
  const [status, setStatus] = useState<string>("Ready");
  const [statusTone, setStatusTone] = useState<"neutral" | "success" | "error">("neutral");

  const definitionById = useMemo(
    () => new Map(definitions.map((definition) => [definition.id, definition])),
    [definitions]
  );

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

  async function addElement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("Adding template element...");
    setStatusTone("neutral");

    try {
      const created = await browserApiFetch<TemplateElement>(`/api/templates/${template.id}/elements`, {
        method: "POST",
        body: JSON.stringify({
          element_definition_id: Number(elementForm.element_definition_id),
          sort_index: Number(elementForm.sort_index),
          render_order: Number(elementForm.render_order),
          section_name: elementForm.section_name || null,
          section_order: Number(elementForm.section_order),
          heading_text: elementForm.heading_text || null,
          is_required: elementForm.is_required,
          is_visible: elementForm.is_visible,
          export_visible: elementForm.export_visible,
          configuration_override_json: {}
        })
      });

      setElements((current) => [...current, created].sort((left, right) => left.sort_index - right.sort_index));
      setStatus(`Added template element #${created.id}`);
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Adding template element failed");
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
          element_type_id: Number(definitionForm.element_type_id),
          render_type_id: Number(definitionForm.render_type_id),
          title: definitionForm.title,
          description: definitionForm.description || null,
          is_editable: true,
          allows_multiple_values: false,
          export_visible: true,
          latex_template: null,
          configuration_json: {},
          is_active: true
        })
      });

      setDefinitions((current) => [created, ...current]);
      setElementForm((current) => ({ ...current, element_definition_id: String(created.id) }));
      setDefinitionForm({
        title: "",
        description: "",
        element_type_id: "1",
        render_type_id: "2"
      });
      setStatus(`Created element definition #${created.id}`);
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Element definition creation failed");
      setStatusTone("error");
    }
  }

  async function updateElement(elementId: number, patch: Partial<TemplateElement>) {
    setStatus(`Saving element #${elementId}...`);

    try {
      const updated = await browserApiFetch<TemplateElement>(`/api/template-elements/${elementId}`, {
        method: "PATCH",
        body: JSON.stringify(patch)
      });
      setElements((current) =>
        current
          .map((element) => (element.id === elementId ? updated : element))
          .sort((left, right) => left.sort_index - right.sort_index)
      );
      setStatus(`Saved element #${elementId}`);
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Element update failed");
      setStatusTone("error");
    }
  }

  async function deleteElement(elementId: number) {
    setStatus(`Deleting element #${elementId}...`);

    try {
      await browserApiFetch<{ message: string }>(`/api/template-elements/${elementId}`, {
        method: "DELETE"
      });
      setElements((current) => current.filter((element) => element.id !== elementId));
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

      <div className="two-col">
        <article className="card">
          <div className="eyebrow">Template Meta</div>
          <h3>{template.name}</h3>
          <form className="grid" onSubmit={saveTemplate}>
            <input
              value={templateForm.name}
              onChange={(event) => setTemplateForm((current) => ({ ...current, name: event.target.value }))}
            />
            <textarea
              rows={4}
              value={templateForm.description}
              onChange={(event) => setTemplateForm((current) => ({ ...current, description: event.target.value }))}
            />
            <input
              value={templateForm.status}
              onChange={(event) => setTemplateForm((current) => ({ ...current, status: event.target.value }))}
            />
            <input
              type="number"
              min={1}
              value={templateForm.document_template_id}
              onChange={(event) =>
                setTemplateForm((current) => ({ ...current, document_template_id: event.target.value }))
              }
            />
            <button type="submit">Save template</button>
          </form>
        </article>

        <article className="card">
          <div className="eyebrow">Element Catalog</div>
          <h3>Available element definitions</h3>
          <div className="block-list">
            {definitions.map((definition) => (
              <div className="block" key={definition.id}>
                <strong>{definition.title}</strong>
                <p className="muted">
                  Element type #{definition.element_type_id} · Render type #{definition.render_type_id}
                </p>
                <p className="muted">{definition.description ?? "No description set."}</p>
              </div>
            ))}
          </div>
        </article>
      </div>

      <article className="card">
        <div className="eyebrow">Create Definition</div>
        <h3>Add a reusable element definition</h3>
        <form className="grid" onSubmit={createDefinition}>
          <input
            value={definitionForm.title}
            onChange={(event) => setDefinitionForm((current) => ({ ...current, title: event.target.value }))}
            placeholder="Definition title"
            required
          />
          <textarea
            rows={3}
            value={definitionForm.description}
            onChange={(event) => setDefinitionForm((current) => ({ ...current, description: event.target.value }))}
            placeholder="Definition description"
          />
          <div className="two-col">
            <input
              type="number"
              min={1}
              value={definitionForm.element_type_id}
              onChange={(event) =>
                setDefinitionForm((current) => ({ ...current, element_type_id: event.target.value }))
              }
              placeholder="Element type id"
            />
            <input
              type="number"
              min={1}
              value={definitionForm.render_type_id}
              onChange={(event) =>
                setDefinitionForm((current) => ({ ...current, render_type_id: event.target.value }))
              }
              placeholder="Render type id"
            />
          </div>
          <button type="submit">Create definition</button>
        </form>
      </article>

      <article className="card">
        <div className="eyebrow">Add Block</div>
        <h3>Assign an element definition to this template</h3>
        <form className="grid" onSubmit={addElement}>
          <select
            value={elementForm.element_definition_id}
            onChange={(event) =>
              setElementForm((current) => ({ ...current, element_definition_id: event.target.value }))
            }
          >
            {definitions.map((definition) => (
              <option key={definition.id} value={definition.id}>
                #{definition.id} {definition.title}
              </option>
            ))}
          </select>
          <div className="two-col">
            <input
              type="number"
              min={1}
              value={elementForm.sort_index}
              onChange={(event) => setElementForm((current) => ({ ...current, sort_index: event.target.value }))}
              placeholder="Sort index"
            />
            <input
              type="number"
              min={1}
              value={elementForm.render_order}
              onChange={(event) => setElementForm((current) => ({ ...current, render_order: event.target.value }))}
              placeholder="Render order"
            />
          </div>
          <div className="two-col">
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
              placeholder="Section order"
            />
          </div>
          <input
            value={elementForm.heading_text}
            onChange={(event) => setElementForm((current) => ({ ...current, heading_text: event.target.value }))}
            placeholder="Heading text"
          />
          <label className="muted">
            <input
              type="checkbox"
              checked={elementForm.is_required}
              onChange={(event) => setElementForm((current) => ({ ...current, is_required: event.target.checked }))}
            />{" "}
            Required
          </label>
          <label className="muted">
            <input
              type="checkbox"
              checked={elementForm.is_visible}
              onChange={(event) => setElementForm((current) => ({ ...current, is_visible: event.target.checked }))}
            />{" "}
            Visible
          </label>
          <label className="muted">
            <input
              type="checkbox"
              checked={elementForm.export_visible}
              onChange={(event) =>
                setElementForm((current) => ({ ...current, export_visible: event.target.checked }))
              }
            />{" "}
            Export visible
          </label>
          <button type="submit" disabled={!elementForm.element_definition_id}>
            Add element to template
          </button>
        </form>
      </article>

      <article className="card">
        <div className="eyebrow">Structure</div>
        <h3>Template elements</h3>
        <div className="block-list">
          {elements.map((element) => {
            const definition = definitionById.get(element.element_definition_id);
            return (
              <div className="block" key={element.id}>
                <div className="two-col">
                  <div>
                    <strong>{definition?.title ?? `Definition #${element.element_definition_id}`}</strong>
                    <p className="muted">
                      sort {element.sort_index} · render {element.render_order ?? element.sort_index}
                    </p>
                    <p className="muted">
                      section {element.section_name ?? "none"} · heading {element.heading_text ?? "none"}
                    </p>
                  </div>
                  <div className="grid">
                    <button type="button" onClick={() => updateElement(element.id, { sort_index: element.sort_index - 1 })}>
                      Move up
                    </button>
                    <button type="button" onClick={() => updateElement(element.id, { sort_index: element.sort_index + 1 })}>
                      Move down
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        updateElement(element.id, { is_required: !element.is_required, heading_text: element.heading_text })
                      }
                    >
                      Toggle required
                    </button>
                    <button type="button" onClick={() => deleteElement(element.id)}>
                      Delete
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
          {elements.length === 0 ? <div className="block"><p className="muted">No elements assigned yet.</p></div> : null}
        </div>
      </article>
    </div>
  );
}
