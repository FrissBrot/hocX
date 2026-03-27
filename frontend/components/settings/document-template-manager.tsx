"use client";

import { Dispatch, FormEvent, SetStateAction, useMemo, useState } from "react";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { DocumentTemplate, DocumentTemplatePart } from "@/types/api";

type Props = {
  initialTemplates: DocumentTemplate[];
  initialParts: DocumentTemplatePart[];
};

type PartFormState = {
  code: string;
  name: string;
  part_type: string;
  description: string;
  version: string;
  is_active: boolean;
  file: File | null;
};

type TemplateFormState = {
  code: string;
  name: string;
  description: string;
  version: string;
  is_active: boolean;
  is_default: boolean;
  primary_color: string;
  secondary_color: string;
  font_family: string;
  font_size: string;
  show_toc: boolean;
  numbering_mode: string;
  preamble: string;
  macros: string;
  title_page: string;
  header_footer: string;
  toc: string;
  element_text: string;
  element_todo: string;
  element_image: string;
  element_display: string;
  element_static_text: string;
};

const slotDefinitions = [
  { key: "preamble", label: "Preamble", help: "Packages and global setup before the document starts." },
  { key: "macros", label: "Macros", help: "Reusable commands and helpers shared across layouts." },
  { key: "title_page", label: "Title page", help: "Optional cover page for protocol metadata and branding." },
  { key: "header_footer", label: "Header and footer", help: "Page header, footer and page-number rules." },
  { key: "toc", label: "Table of contents", help: "Reusable TOC snippet or custom section overview." },
  { key: "element_text", label: "Text block partial", help: "How text blocks render in PDF." },
  { key: "element_todo", label: "Todo block partial", help: "How todo lists render in PDF." },
  { key: "element_image", label: "Image block partial", help: "How uploaded images render in PDF." },
  { key: "element_display", label: "Display block partial", help: "How read-only snapshots render in PDF." },
  { key: "element_static_text", label: "Static text block partial", help: "How fixed text blocks render in PDF." }
] as const;

const partTypeOptions = slotDefinitions.map((entry) => entry.key);

const initialPartForm: PartFormState = {
  code: "",
  name: "",
  part_type: "preamble",
  description: "",
  version: "1",
  is_active: true,
  file: null
};

const initialTemplateForm: TemplateFormState = {
  code: "",
  name: "",
  description: "",
  version: "1",
  is_active: true,
  is_default: false,
  primary_color: "A83F2F",
  secondary_color: "6F675D",
  font_family: "default",
  font_size: "11pt",
  show_toc: true,
  numbering_mode: "sections",
  preamble: "",
  macros: "",
  title_page: "",
  header_footer: "",
  toc: "",
  element_text: "",
  element_todo: "",
  element_image: "",
  element_display: "",
  element_static_text: ""
};

function templateFormFromTemplate(template: DocumentTemplate): TemplateFormState {
  const config = (template.configuration_json ?? {}) as Record<string, any>;
  const theme = config.theme ?? {};
  const options = config.options ?? {};
  const slots = config.slots ?? {};
  return {
    code: template.code,
    name: template.name,
    description: template.description ?? "",
    version: String(template.version),
    is_active: template.is_active,
    is_default: template.is_default,
    primary_color: theme.primary_color ?? "A83F2F",
    secondary_color: theme.secondary_color ?? "6F675D",
    font_family: theme.font_family ?? "default",
    font_size: theme.font_size ?? "11pt",
    show_toc: options.show_toc ?? true,
    numbering_mode: options.numbering_mode ?? "sections",
    preamble: slots.preamble ? String(slots.preamble) : "",
    macros: slots.macros ? String(slots.macros) : "",
    title_page: slots.title_page ? String(slots.title_page) : "",
    header_footer: slots.header_footer ? String(slots.header_footer) : "",
    toc: slots.toc ? String(slots.toc) : "",
    element_text: slots.element_text ? String(slots.element_text) : "",
    element_todo: slots.element_todo ? String(slots.element_todo) : "",
    element_image: slots.element_image ? String(slots.element_image) : "",
    element_display: slots.element_display ? String(slots.element_display) : "",
    element_static_text: slots.element_static_text ? String(slots.element_static_text) : ""
  };
}

function buildTemplatePayload(form: TemplateFormState) {
  return {
    tenant_id: 1,
    code: form.code,
    name: form.name,
    description: form.description || null,
    version: Number(form.version),
    is_active: form.is_active,
    is_default: form.is_default,
    configuration_json: {
      theme: {
        primary_color: form.primary_color,
        secondary_color: form.secondary_color,
        font_family: form.font_family,
        font_size: form.font_size
      },
      options: {
        show_toc: form.show_toc,
        numbering_mode: form.numbering_mode
      },
      slots: Object.fromEntries(
        [
          "preamble",
          "macros",
          "title_page",
          "header_footer",
          "toc",
          "element_text",
          "element_todo",
          "element_image",
          "element_display",
          "element_static_text"
        ]
          .filter((slot) => form[slot as keyof TemplateFormState])
          .map((slot) => [slot, Number(form[slot as keyof TemplateFormState] as string)])
      )
    }
  };
}

export function DocumentTemplateManager({ initialTemplates, initialParts }: Props) {
  const [parts, setParts] = useState(initialParts);
  const [templates, setTemplates] = useState(initialTemplates);
  const [activePanel, setActivePanel] = useState<"parts" | "layouts">("layouts");
  const [showPartForm, setShowPartForm] = useState(false);
  const [showTemplateForm, setShowTemplateForm] = useState(false);
  const [partForm, setPartForm] = useState(initialPartForm);
  const [templateForm, setTemplateForm] = useState(initialTemplateForm);
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | null>(initialTemplates[0]?.id ?? null);
  const [selectedTemplateForm, setSelectedTemplateForm] = useState<TemplateFormState>(
    initialTemplates[0] ? templateFormFromTemplate(initialTemplates[0]) : initialTemplateForm
  );
  const [status, setStatus] = useState("Ready");
  const [statusTone, setStatusTone] = useState<"neutral" | "success" | "error">("neutral");

  const selectedTemplate = useMemo(
    () => templates.find((template) => template.id === selectedTemplateId) ?? null,
    [templates, selectedTemplateId]
  );

  const partsByType = useMemo(() => {
    const grouped: Record<string, DocumentTemplatePart[]> = {};
    for (const part of parts) {
      grouped[part.part_type] = [...(grouped[part.part_type] ?? []), part];
    }
    return grouped;
  }, [parts]);

  function selectTemplate(template: DocumentTemplate) {
    setSelectedTemplateId(template.id);
    setSelectedTemplateForm(templateFormFromTemplate(template));
  }

  async function createPart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!partForm.file) {
      setStatus("Please choose a .tex file");
      setStatusTone("error");
      return;
    }
    setStatus("Uploading part...");
    setStatusTone("neutral");
    try {
      const body = new FormData();
      body.append("code", partForm.code);
      body.append("name", partForm.name);
      body.append("part_type", partForm.part_type);
      body.append("description", partForm.description);
      body.append("version", partForm.version);
      body.append("is_active", String(partForm.is_active));
      body.append("file", partForm.file);
      const created = await browserApiFetch<DocumentTemplatePart>("/api/document-template-parts", {
        method: "POST",
        body
      });
      setParts((current) => [...current, created].sort((a, b) => a.part_type.localeCompare(b.part_type) || a.name.localeCompare(b.name)));
      setPartForm(initialPartForm);
      setShowPartForm(false);
      setStatus("Part uploaded");
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Part upload failed");
      setStatusTone("error");
    }
  }

  async function deletePart(partId: number) {
    setStatus("Deleting part...");
    setStatusTone("neutral");
    try {
      await browserApiFetch<{ message: string }>(`/api/document-template-parts/${partId}`, { method: "DELETE" });
      setParts((current) => current.filter((part) => part.id !== partId));
      setStatus("Part deleted");
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Part deletion failed");
      setStatusTone("error");
    }
  }

  async function createTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("Creating document template...");
    setStatusTone("neutral");
    try {
      const created = await browserApiFetch<DocumentTemplate>("/api/document-templates", {
        method: "POST",
        body: JSON.stringify(buildTemplatePayload(templateForm))
      });
      setTemplates((current) => [created, ...current.filter((item) => item.id !== created.id)]);
      setTemplateForm(initialTemplateForm);
      setShowTemplateForm(false);
      selectTemplate(created);
      setStatus("Document template created");
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Document template creation failed");
      setStatusTone("error");
    }
  }

  async function saveSelectedTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedTemplate) return;
    setStatus("Saving document template...");
    setStatusTone("neutral");
    try {
      const updated = await browserApiFetch<DocumentTemplate>(`/api/document-templates/${selectedTemplate.id}`, {
        method: "PATCH",
        body: JSON.stringify(buildTemplatePayload(selectedTemplateForm))
      });
      setTemplates((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      selectTemplate(updated);
      setStatus("Document template saved");
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Document template save failed");
      setStatusTone("error");
    }
  }

  async function deleteTemplate(templateId: number) {
    setStatus("Deleting document template...");
    setStatusTone("neutral");
    try {
      await browserApiFetch<{ message: string }>(`/api/document-templates/${templateId}`, { method: "DELETE" });
      const remaining = templates.filter((template) => template.id !== templateId);
      setTemplates(remaining);
      if (selectedTemplateId === templateId) {
        setSelectedTemplateId(remaining[0]?.id ?? null);
        setSelectedTemplateForm(remaining[0] ? templateFormFromTemplate(remaining[0]) : initialTemplateForm);
      }
      setStatus("Document template deleted");
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Document template deletion failed");
      setStatusTone("error");
    }
  }

  return (
    <div className="grid">
      <StatusBanner tone={statusTone} message={status} />

      <div className="segment-control">
        <button type="button" className={`segment-button${activePanel === "layouts" ? " segment-button-active" : ""}`} onClick={() => setActivePanel("layouts")}>
          Layouts
        </button>
        <button type="button" className={`segment-button${activePanel === "parts" ? " segment-button-active" : ""}`} onClick={() => setActivePanel("parts")}>
          Parts library
        </button>
      </div>

      <Modal
        open={showPartForm}
        onClose={() => setShowPartForm(false)}
        title="Upload LaTeX part"
        description="Add a reusable tenant-wide snippet for headers, title pages, block partials or TOC behavior."
      >
        <form className="grid" onSubmit={createPart}>
          <div className="three-col">
            <label className="field-stack">
              <span className="field-label">Code</span>
              <input value={partForm.code} onChange={(event) => setPartForm((current) => ({ ...current, code: event.target.value }))} required />
            </label>
            <label className="field-stack">
              <span className="field-label">Name</span>
              <input value={partForm.name} onChange={(event) => setPartForm((current) => ({ ...current, name: event.target.value }))} required />
            </label>
            <label className="field-stack">
              <span className="field-label">Type</span>
              <select value={partForm.part_type} onChange={(event) => setPartForm((current) => ({ ...current, part_type: event.target.value }))}>
                {partTypeOptions.map((type) => <option key={type} value={type}>{type}</option>)}
              </select>
            </label>
          </div>
          <div className="three-col">
            <label className="field-stack">
              <span className="field-label">Description</span>
              <input value={partForm.description} onChange={(event) => setPartForm((current) => ({ ...current, description: event.target.value }))} />
            </label>
            <label className="field-stack">
              <span className="field-label">Version</span>
              <input type="number" min={1} value={partForm.version} onChange={(event) => setPartForm((current) => ({ ...current, version: event.target.value }))} />
            </label>
            <label className="field-stack">
              <span className="field-label">LaTeX file</span>
              <input type="file" accept=".tex" onChange={(event) => setPartForm((current) => ({ ...current, file: event.target.files?.[0] ?? null }))} required />
            </label>
          </div>
          <label className="checkbox-row">
            <input type="checkbox" checked={partForm.is_active} onChange={(event) => setPartForm((current) => ({ ...current, is_active: event.target.checked }))} />
            Active
          </label>
          <div className="table-toolbar-actions">
            <button type="submit" className="button-inline">Upload part</button>
          </div>
        </form>
      </Modal>

      <Modal
        open={showTemplateForm}
        onClose={() => setShowTemplateForm(false)}
        title="Create document layout"
        description="Assemble a reusable PDF layout from global theme settings and uploaded LaTeX parts."
        size="wide"
      >
        <form className="grid" onSubmit={createTemplate}>
          <TemplateForm form={templateForm} setForm={setTemplateForm} partsByType={partsByType} />
          <div className="table-toolbar-actions">
            <button type="submit" className="button-inline">Create document template</button>
          </div>
        </form>
      </Modal>

      {activePanel === "parts" ? (
        <article className="card">
          <DataToolbar
            title="LaTeX parts library"
            description="Upload reusable LaTeX files once per tenant and mix them into many document layouts."
            actions={<button type="button" className="button-inline" onClick={() => setShowPartForm(true)}>Upload part</button>}
          />

          <div className="info-note">
            Parts are tenant-wide reusable LaTeX snippets. Upload once, then reuse them across title pages, headers,
            TOC behavior and block rendering.
          </div>

          <DataTable columns={["Name", "Type", "Version", "State", "Actions"]}>
            {parts.map((part) => (
              <tr key={part.id}>
                <td>
                  <strong>{part.name}</strong>
                  <div className="muted">{part.code}</div>
                </td>
                <td>{slotDefinitions.find((entry) => entry.key === part.part_type)?.label ?? part.part_type}</td>
                <td>{part.version}</td>
                <td><span className="pill">{part.is_active ? "active" : "inactive"}</span></td>
                <td>
                  <div className="table-actions">
                    <button type="button" className="button-inline button-danger" onClick={() => deletePart(part.id)}>
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </DataTable>
        </article>
      ) : (
        <article className="card">
          <DataToolbar
            title="Document layouts"
            description="Compose reusable PDF layouts, then assign them per protocol when needed."
            actions={<button type="button" className="button-inline" onClick={() => setShowTemplateForm(true)}>New document template</button>}
          />

          <div className="info-note">
            A document template defines the full PDF layout for one tenant. Protocols can choose one of these layouts
            and snapshot it so later exports stay reproducible.
          </div>

          <div className="editor-shell">
            <aside className="editor-nav">
              <div className="editor-nav-section">
                <h3 className="editor-nav-title">Available layouts</h3>
                {templates.map((template) => (
                  <button
                    key={template.id}
                    type="button"
                    className={`editor-nav-item${selectedTemplateId === template.id ? " editor-nav-item-active" : ""}`}
                    onClick={() => selectTemplate(template)}
                  >
                    <strong>{template.name}</strong>
                    <span className="muted">{template.code}</span>
                    <div className="status-row">
                      <span className="pill">{template.version}</span>
                      <span className="pill">{template.is_default ? "Default" : "Custom"}</span>
                    </div>
                  </button>
                ))}
              </div>
            </aside>

            <div className="editor-panel">
              {selectedTemplate ? (
                <form className="grid" onSubmit={saveSelectedTemplate}>
                  <div className="editor-panel-header">
                    <div>
                      <div className="eyebrow">Selected layout</div>
                      <h2>{selectedTemplate.name}</h2>
                    </div>
                    <button type="button" className="button-inline button-danger" onClick={() => deleteTemplate(selectedTemplate.id)}>
                      Delete
                    </button>
                  </div>
                  <TemplateForm form={selectedTemplateForm} setForm={setSelectedTemplateForm} partsByType={partsByType} />
                  <div className="table-toolbar-actions">
                    <button type="submit" className="button-inline">Save document template</button>
                  </div>
                </form>
              ) : (
                <div className="editor-panel-empty">Select a layout to edit it.</div>
              )}
            </div>
          </div>
        </article>
      )}
    </div>
  );
}

function TemplateForm({
  form,
  setForm,
  partsByType
}: {
  form: TemplateFormState;
  setForm: Dispatch<SetStateAction<TemplateFormState>>;
  partsByType: Record<string, DocumentTemplatePart[]>;
}) {
  return (
    <div className="grid">
      <div className="three-col">
        <label className="field-stack">
          <span className="field-label">Code</span>
          <input value={form.code} onChange={(event) => setForm((current) => ({ ...current, code: event.target.value }))} required />
        </label>
        <label className="field-stack">
          <span className="field-label">Name</span>
          <input value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} required />
        </label>
        <label className="field-stack">
          <span className="field-label">Version</span>
          <input type="number" min={1} value={form.version} onChange={(event) => setForm((current) => ({ ...current, version: event.target.value }))} />
        </label>
      </div>

      <label className="field-stack">
        <span className="field-label">Description</span>
        <input value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} />
      </label>

      <div className="four-col">
        <label className="checkbox-row"><input type="checkbox" checked={form.is_active} onChange={(event) => setForm((current) => ({ ...current, is_active: event.target.checked }))} />Active</label>
        <label className="checkbox-row"><input type="checkbox" checked={form.is_default} onChange={(event) => setForm((current) => ({ ...current, is_default: event.target.checked }))} />Default for tenant</label>
        <label className="checkbox-row"><input type="checkbox" checked={form.show_toc} onChange={(event) => setForm((current) => ({ ...current, show_toc: event.target.checked }))} />Show TOC</label>
        <label className="field-stack">
          <span className="field-label">Numbering</span>
          <select value={form.numbering_mode} onChange={(event) => setForm((current) => ({ ...current, numbering_mode: event.target.value }))}>
            <option value="sections">Section numbers</option>
            <option value="none">No numbering</option>
          </select>
        </label>
      </div>

      <div className="four-col">
        <label className="field-stack">
          <span className="field-label">Primary color</span>
          <input value={form.primary_color} onChange={(event) => setForm((current) => ({ ...current, primary_color: event.target.value }))} />
        </label>
        <label className="field-stack">
          <span className="field-label">Secondary color</span>
          <input value={form.secondary_color} onChange={(event) => setForm((current) => ({ ...current, secondary_color: event.target.value }))} />
        </label>
        <label className="field-stack">
          <span className="field-label">Font family</span>
          <select value={form.font_family} onChange={(event) => setForm((current) => ({ ...current, font_family: event.target.value }))}>
            <option value="default">Default</option>
            <option value="helvet">Helvetica</option>
            <option value="palatino">Palatino</option>
          </select>
        </label>
        <label className="field-stack">
          <span className="field-label">Font size</span>
          <select value={form.font_size} onChange={(event) => setForm((current) => ({ ...current, font_size: event.target.value }))}>
            <option value="10pt">10pt</option>
            <option value="11pt">11pt</option>
            <option value="12pt">12pt</option>
          </select>
        </label>
      </div>

      <div className="three-col">
        {slotDefinitions.map(({ key, label, help }) => (
          <label className="field-stack" key={key}>
            <span className="field-label">{label}</span>
            <select value={form[key as keyof TemplateFormState] as string} onChange={(event) => setForm((current) => ({ ...current, [key]: event.target.value }))}>
              <option value="">None</option>
              {(partsByType[key] ?? []).map((part) => (
                <option key={part.id} value={part.id}>
                  {part.name}
                </option>
              ))}
            </select>
            <span className="field-help">{help}</span>
          </label>
        ))}
      </div>
    </div>
  );
}
