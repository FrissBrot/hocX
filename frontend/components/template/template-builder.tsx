"use client";

import { DragEvent, FormEvent, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateRange } from "@/lib/utils/format";
import { ElementDefinition, EventSummary, ParticipantSummary, TemplateElement, TemplateSummary } from "@/types/api";

type TemplateBuilderProps = {
  initialTemplates: TemplateSummary[];
};

type TemplateEditorProps = {
  initialTemplate: TemplateSummary;
  initialElements: TemplateElement[];
  initialDefinitions: ElementDefinition[];
  availableEvents: EventSummary[];
  availableParticipants: ParticipantSummary[];
  initialAssignedParticipants: ParticipantSummary[];
};

type TemplateCreateState = {
  name: string;
  description: string;
  next_event_id: string;
  last_event_id: string;
  protocol_number_pattern: string;
  title_pattern: string;
  auto_create_next_protocol: boolean;
  cycle_reset_month: string;
  cycle_reset_day: string;
};

type TemplateItemForm = {
  element_definition_ids: string[];
};

const initialTemplateCreate: TemplateCreateState = {
  name: "",
  description: "",
  next_event_id: "",
  last_event_id: "",
  protocol_number_pattern: "",
  title_pattern: "",
  auto_create_next_protocol: false,
  cycle_reset_month: "7",
  cycle_reset_day: "31"
};

const initialTemplateItemForm: TemplateItemForm = {
  element_definition_ids: []
};

function resequenceTemplateElements(items: TemplateElement[]) {
  return items.map((item, index) => ({ ...item, sort_index: (index + 1) * 10 }));
}

function nextTemplateElementSortIndex(items: TemplateElement[]) {
  const maxSortIndex = items.reduce((max, item) => Math.max(max, item.sort_index), 0);
  return maxSortIndex + 10;
}

function definitionTypeSummary(definition: ElementDefinition) {
  const labels = Array.from(
    new Set(
      definition.blocks
        .map((block) => String(block.configuration_json?.block_type_code ?? block.title ?? "").trim())
        .filter(Boolean)
    )
  );
  return labels.length ? labels.join(", ") : `${definition.blocks.length} Block${definition.blocks.length === 1 ? "" : "e"}`;
}

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
          name: form.name,
          description: form.description || null,
          protocol_number_pattern: form.protocol_number_pattern || null,
          title_pattern: form.title_pattern || null,
          auto_create_next_protocol: form.auto_create_next_protocol,
          cycle_reset_month: Number(form.cycle_reset_month),
          cycle_reset_day: Number(form.cycle_reset_day),
          version: 1,
          status: "active",
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
          <label className="field-stack">
            <span className="field-label">Template name</span>
            <input value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} placeholder="Template name" required />
          </label>
          <label className="field-stack">
            <span className="field-label">Description</span>
            <textarea rows={4} value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} placeholder="Description" />
          </label>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Protocol number pattern</span>
              <input value={form.protocol_number_pattern} onChange={(event) => setForm((current) => ({ ...current, protocol_number_pattern: event.target.value }))} placeholder="e.g. Sitzung {n}" />
              <span className="field-help">Beispiele: Sitzung [n], Sitzung [mm].[n_month], J[yy]-[n_year], V[n_cycle]. Eckige und geschweifte Klammern funktionieren beide.</span>
            </label>
            <label className="field-stack">
              <span className="field-label">Title pattern</span>
              <input value={form.title_pattern} onChange={(event) => setForm((current) => ({ ...current, title_pattern: event.target.value }))} placeholder="e.g. Sitzung {n} - {date:DD.MM.YYYY}" />
              <span className="field-help">The date token always uses the selected protocol date, not the current day.</span>
            </label>
          </div>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Cycle reset month</span>
              <input value={form.cycle_reset_month} onChange={(event) => setForm((current) => ({ ...current, cycle_reset_month: event.target.value }))} type="number" min={1} max={12} />
            </label>
            <label className="field-stack">
              <span className="field-label">Cycle reset day</span>
              <input value={form.cycle_reset_day} onChange={(event) => setForm((current) => ({ ...current, cycle_reset_day: event.target.value }))} type="number" min={1} max={31} />
            </label>
          </div>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={form.auto_create_next_protocol}
              onChange={(event) => setForm((current) => ({ ...current, auto_create_next_protocol: event.target.checked }))}
            />
            <span>Naechstes Protokoll automatisch erstellen, wenn dieses spaeter auf Abgeschlossen gesetzt wird.</span>
          </label>
          <div className="info-note">
            Tokens: {"{n}"} = alle Protokolle, {"{n_year}"} = in diesem Jahr, {"{n_month}"} = in diesem Monat, {"{n_cycle}"} = im eigenen Zyklus. Datums-Tokens: {"{date}"}, {"{date:DD.MM.YYYY}"}, {"{dd}"}, {"{mm}"}, {"{yyyy}"}.
          </div>
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
              <div className="muted">{template.status === "archived" ? "Archiviert" : "Aktiv"}</div>
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

export function TemplateEditor({
  initialTemplate,
  initialElements,
  initialDefinitions,
  availableEvents,
  availableParticipants,
  initialAssignedParticipants,
}: TemplateEditorProps) {
  const router = useRouter();
  const [template, setTemplate] = useState(initialTemplate);
  const [elements, setElements] = useState(initialElements);
  const [templateMeta, setTemplateMeta] = useState({
    name: initialTemplate.name,
    description: initialTemplate.description ?? "",
    status: initialTemplate.status,
    next_event_id: initialTemplate.next_event_id ? String(initialTemplate.next_event_id) : "",
    last_event_id: initialTemplate.last_event_id ? String(initialTemplate.last_event_id) : "",
    protocol_number_pattern: initialTemplate.protocol_number_pattern ?? "",
    title_pattern: initialTemplate.title_pattern ?? "",
    auto_create_next_protocol: Boolean(initialTemplate.auto_create_next_protocol),
    cycle_reset_month: String(initialTemplate.cycle_reset_month ?? 7),
    cycle_reset_day: String(initialTemplate.cycle_reset_day ?? 31)
  });
  const [newItemForm, setNewItemForm] = useState<TemplateItemForm>({
    ...initialTemplateItemForm
  });
  const [showCreateItem, setShowCreateItem] = useState(false);
  const [showParticipantModal, setShowParticipantModal] = useState(false);
  const [status, setStatus] = useState("Ready");
  const [statusTone, setStatusTone] = useState<"neutral" | "success" | "error">("neutral");
  const [draggedTemplateElementId, setDraggedTemplateElementId] = useState<number | null>(null);
  const [assignedParticipantIds, setAssignedParticipantIds] = useState<number[]>(
    initialAssignedParticipants.map((participant) => participant.id)
  );

  const allParticipantIds = useMemo(
    () => availableParticipants.filter((participant) => participant.is_active).map((participant) => participant.id),
    [availableParticipants]
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
          next_event_id: templateMeta.next_event_id ? Number(templateMeta.next_event_id) : null,
          last_event_id: templateMeta.last_event_id ? Number(templateMeta.last_event_id) : null,
          protocol_number_pattern: templateMeta.protocol_number_pattern || null,
          title_pattern: templateMeta.title_pattern || null,
          auto_create_next_protocol: templateMeta.auto_create_next_protocol,
          cycle_reset_month: Number(templateMeta.cycle_reset_month),
          cycle_reset_day: Number(templateMeta.cycle_reset_day)
        })
      });
      setTemplate(updated);
      setStatus("Template saved");
      setStatusTone("success");
      router.refresh();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Template save failed");
      setStatusTone("error");
    }
  }

  async function saveTemplateParticipants(closeAfter = false) {
    setStatus("Saving participant assignments...");
    setStatusTone("neutral");
    try {
      await browserApiFetch(`/api/templates/${template.id}/participants`, {
        method: "PUT",
        body: JSON.stringify({ participant_ids: assignedParticipantIds }),
      });
      setStatus("Participant assignments saved");
      setStatusTone("success");
      router.refresh();
      if (closeAfter) {
        setShowParticipantModal(false);
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Participant assignments could not be saved");
      setStatusTone("error");
    }
  }

  async function addElementToTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
      setStatus("Adding element to template...");
    setStatusTone("neutral");
    try {
      const createdItems = await Promise.all(
        newItemForm.element_definition_ids.map((elementDefinitionId, index) =>
          browserApiFetch<TemplateElement>(`/api/templates/${template.id}/elements`, {
            method: "POST",
            body: JSON.stringify({
              element_definition_id: Number(elementDefinitionId),
              sort_index: nextTemplateElementSortIndex(elements) + index * 10
            })
          })
        )
      );
      setElements((current) => [...current, ...createdItems].sort((left, right) => left.sort_index - right.sort_index));
      setNewItemForm(initialTemplateItemForm);
      setShowCreateItem(false);
      setStatus(`${createdItems.length} Element${createdItems.length === 1 ? "" : "e"} hinzugefuegt`);
      setStatusTone("success");
      router.refresh();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Template element creation failed");
      setStatusTone("error");
    }
  }

  async function reorderTemplateItems(sourceId: number, targetId: number) {
    if (sourceId === targetId) {
      return;
    }
    setStatus("Saving template order...");
    setStatusTone("neutral");
    try {
      const ordered = [...elements].sort((left, right) => left.sort_index - right.sort_index);
      const sourceIndex = ordered.findIndex((item) => item.id === sourceId);
      const targetIndex = ordered.findIndex((item) => item.id === targetId);
      if (sourceIndex === -1 || targetIndex === -1) {
        return;
      }
      const [moved] = ordered.splice(sourceIndex, 1);
      ordered.splice(targetIndex, 0, moved);
      const resequenced = resequenceTemplateElements(ordered);
      const temporaryItems = resequenced.map((item, index) => ({
        ...item,
        sort_index: -1000 - index,
      }));
      for (const item of temporaryItems) {
        await browserApiFetch<TemplateElement>(`/api/template-elements/${item.id}`, {
          method: "PATCH",
          body: JSON.stringify({ sort_index: item.sort_index })
        });
      }
      const updatedItems: TemplateElement[] = [];
      for (const item of resequenced) {
        const updated = await browserApiFetch<TemplateElement>(`/api/template-elements/${item.id}`, {
          method: "PATCH",
          body: JSON.stringify({ sort_index: item.sort_index })
        });
        updatedItems.push(updated);
      }
      setElements(updatedItems.sort((left, right) => left.sort_index - right.sort_index));
      setStatus("Template order saved");
      setStatusTone("success");
      router.refresh();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Template order update failed");
      setStatusTone("error");
    }
  }

  function handleTemplateDragStart(event: DragEvent<HTMLElement>, templateElementId: number) {
    setDraggedTemplateElementId(templateElementId);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/template-element", String(templateElementId));
  }

  function handleTemplateDrop(event: DragEvent<HTMLElement>, targetId: number) {
    event.preventDefault();
    const transferValue = event.dataTransfer.getData("text/template-element");
    const sourceId = transferValue ? Number(transferValue) : draggedTemplateElementId;
    setDraggedTemplateElementId(null);
    if (!sourceId || Number.isNaN(sourceId)) {
      return;
    }
    void reorderTemplateItems(sourceId, targetId);
  }

  async function deleteTemplateItem(templateElementId: number) {
    setStatus("Removing element from template...");
    setStatusTone("neutral");
    try {
      await browserApiFetch(`/api/template-elements/${templateElementId}`, { method: "DELETE" });
      setElements((current) => current.filter((item) => item.id !== templateElementId));
      setStatus("Element removed from template");
      setStatusTone("success");
      router.refresh();
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
          <label className="field-stack">
            <span className="field-label">Template name</span>
            <input value={templateMeta.name} onChange={(event) => setTemplateMeta((current) => ({ ...current, name: event.target.value }))} />
          </label>
          <label className="field-stack">
            <span className="field-label">Description</span>
            <textarea rows={4} value={templateMeta.description} onChange={(event) => setTemplateMeta((current) => ({ ...current, description: event.target.value }))} />
          </label>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Protocol number pattern</span>
              <input value={templateMeta.protocol_number_pattern} onChange={(event) => setTemplateMeta((current) => ({ ...current, protocol_number_pattern: event.target.value }))} placeholder="e.g. Sitzung {n}" />
              <span className="field-help">Beispiele: Sitzung [n], Sitzung [mm].[n_month], J[yy]-[n_year], V[n_cycle]. Eckige und geschweifte Klammern funktionieren beide.</span>
            </label>
            <label className="field-stack">
              <span className="field-label">Title pattern</span>
              <input value={templateMeta.title_pattern} onChange={(event) => setTemplateMeta((current) => ({ ...current, title_pattern: event.target.value }))} placeholder="e.g. Sitzung {n} - {date:DD.MM.YYYY}" />
              <span className="field-help">Used automatically when a new protocol is created and the title field is left empty.</span>
            </label>
          </div>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Cycle reset month</span>
              <input value={templateMeta.cycle_reset_month} onChange={(event) => setTemplateMeta((current) => ({ ...current, cycle_reset_month: event.target.value }))} type="number" min={1} max={12} />
            </label>
            <label className="field-stack">
              <span className="field-label">Cycle reset day</span>
              <input value={templateMeta.cycle_reset_day} onChange={(event) => setTemplateMeta((current) => ({ ...current, cycle_reset_day: event.target.value }))} type="number" min={1} max={31} />
              <span className="field-help">Example: 31.07 means the cycle resets after 31 July, so the next cycle starts on 01 August.</span>
            </label>
          </div>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Naechste Sitzung</span>
              <select value={templateMeta.next_event_id} onChange={(event) => setTemplateMeta((current) => ({ ...current, next_event_id: event.target.value }))}>
                <option value="">Nicht gesetzt</option>
                {availableEvents.map((event) => (
                  <option key={event.id} value={event.id}>
                    {formatDateRange(event.event_date, event.event_end_date)} - {event.title}
                  </option>
                ))}
              </select>
              <span className="field-help">Kann in Todos und spaeteren Blöcken als Marker verwendet werden.</span>
            </label>
            <label className="field-stack">
              <span className="field-label">Letzte Sitzung</span>
              <select value={templateMeta.last_event_id} onChange={(event) => setTemplateMeta((current) => ({ ...current, last_event_id: event.target.value }))}>
                <option value="">Nicht gesetzt</option>
                {availableEvents.map((event) => (
                  <option key={event.id} value={event.id}>
                    {formatDateRange(event.event_date, event.event_end_date)} - {event.title}
                  </option>
                ))}
              </select>
              <span className="field-help">Bleibt als Template-Kontext erhalten und ist nicht auf das heutige Datum bezogen.</span>
            </label>
          </div>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={templateMeta.auto_create_next_protocol}
              onChange={(event) =>
                setTemplateMeta((current) => ({ ...current, auto_create_next_protocol: event.target.checked }))
              }
            />
            <span>Naechstes Protokoll automatisch erstellen, sobald dieses Protokoll spaeter auf Abgeschlossen gesetzt wird.</span>
          </label>
          <div className="info-note">
            Kurzinfo: [n] zaehlt alle Protokolle, [n_year] pro Kalenderjahr, [n_month] pro Monat und [n_cycle] im eigenen Zyklus. Du kannst frei kombinieren, z. B. Sitzung [mm].[n_month] oder Protokoll [n_cycle]/[cycle_yyyy_end].
          </div>
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
          title="Teilnehmer im Template"
          description="Nur diese Teilnehmer werden spaeter in den Todo-Bloecken dieses Templates zur Auswahl angeboten."
          actions={
            <div className="table-toolbar-actions">
              <button type="button" className="button-inline" onClick={() => setShowParticipantModal(true)}>
                Teilnehmer waehlen
              </button>
            </div>
          }
        />
        <div className="status-row">
          <span className="pill">{assignedParticipantIds.length} ausgewaehlt</span>
          <span className="pill">{availableParticipants.length} verfuegbar</span>
        </div>

        <Modal
          open={showParticipantModal}
          onClose={() => setShowParticipantModal(false)}
          title="Teilnehmer waehlen"
          description="Mit Haken festlegen, welche Teilnehmer in diesem Template spaeter in Todos und passenden Bloecken zur Auswahl stehen."
          size="fullscreen"
        >
          <div className="grid">
            <div className="table-toolbar-actions">
              <button
                type="button"
                className="button-ghost button-inline"
                onClick={() => setAssignedParticipantIds(allParticipantIds)}
              >
                Alle auswaehlen
              </button>
            </div>
            <div className="selection-list">
              {availableParticipants.map((participant) => {
                const checked = assignedParticipantIds.includes(participant.id);
                return (
                  <label key={participant.id} className={`selection-card selection-card-checkbox${checked ? " selection-card-active" : ""}`}>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(event) =>
                        setAssignedParticipantIds((current) =>
                          event.target.checked
                            ? [...new Set([...current, participant.id])]
                            : current.filter((id) => id !== participant.id)
                        )
                      }
                    />
                    <div>
                      <strong>{participant.display_name}</strong>
                      <div className="muted">
                        {[participant.first_name, participant.last_name].filter(Boolean).join(" ") || participant.email || "Teilnehmer"}
                      </div>
                    </div>
                  </label>
                );
              })}
            </div>
            <div className="table-toolbar-actions table-actions-end">
              <button type="button" className="button-inline" onClick={() => void saveTemplateParticipants(true)}>
                Auswahl speichern
              </button>
            </div>
          </div>
        </Modal>
      </article>

      <article className="card">
        <DataToolbar
          title="Template elements"
          description="Templates only collect finished elements. Wiederholungen und Filter werden direkt in den Blöcken des Elements gepflegt."
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
          description="Waehle ein oder mehrere fertige Elemente aus und fuege sie gesammelt zum Template hinzu."
        >
          <form className="grid" onSubmit={addElementToTemplate}>
            <DataTable columns={["", "Element", "Typen", "Beschreibung", "Bloecke"]}>
              {initialDefinitions.map((definition) => {
                const checked = newItemForm.element_definition_ids.includes(String(definition.id));
                return (
                  <tr
                    key={definition.id}
                    className="table-row-clickable"
                    onClick={() =>
                      setNewItemForm((current) => ({
                        ...current,
                        element_definition_ids: checked
                          ? current.element_definition_ids.filter((id) => id !== String(definition.id))
                          : [...current.element_definition_ids, String(definition.id)],
                      }))
                    }
                  >
                    <td>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => undefined}
                        aria-label={`Element ${definition.title} auswaehlen`}
                      />
                    </td>
                    <td>
                      <strong>{definition.title}</strong>
                    </td>
                    <td>{definitionTypeSummary(definition)}</td>
                    <td>{definition.description ?? "Keine Beschreibung"}</td>
                    <td>{definition.blocks.length}</td>
                  </tr>
                );
              })}
            </DataTable>
            <span className="field-help">Neue Elemente werden automatisch hinten angehaengt. Die Reihenfolge kannst du danach per Drag and Drop anpassen.</span>
            <div className="table-toolbar-actions">
              <button type="submit" className="button-inline" disabled={newItemForm.element_definition_ids.length === 0}>Ausgewaehlte Elemente hinzufuegen</button>
            </div>
          </form>
        </Modal>

        <DataTable columns={["Element", "Blocks", "Order", "Actions"]}>
          {elements
            .slice()
            .sort((left, right) => left.sort_index - right.sort_index)
            .map((item) => (
            <tr
              key={item.id}
              className={draggedTemplateElementId === item.id ? "table-row-dragging" : ""}
              onDragEnd={() => setDraggedTemplateElementId(null)}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => handleTemplateDrop(event, item.id)}
            >
              <td>
                <strong>{item.title}</strong>
                <div className="muted">{item.description ?? "No description"}</div>
              </td>
              <td>{item.blocks.length} block{item.blocks.length === 1 ? "" : "s"}</td>
              <td>
                <button
                  type="button"
                  draggable
                  className="pill table-drag-handle"
                  onDragStart={(event) => handleTemplateDragStart(event, item.id)}
                  onDragEnd={() => setDraggedTemplateElementId(null)}
                  title="Ziehen zum Umordnen"
                >
                  Drag
                </button>
              </td>
              <td>
                <div className="table-actions">
                  <button type="button" className="button-inline button-danger" onClick={() => void deleteTemplateItem(item.id)}>Remove</button>
                </div>
              </td>
            </tr>
          ))}
        </DataTable>
      </article>
    </div>
  );
}
