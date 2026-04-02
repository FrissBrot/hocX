"use client";

import { FormEvent, useMemo, useState } from "react";

import { StructuredListTable } from "@/components/lists/structured-list-table";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import {
  EventSummary,
  ParticipantSummary,
  StructuredListDefinition,
  StructuredListEntry,
  StructuredListValueType,
} from "@/types/api";

type ListManagerProps = {
  initialLists: StructuredListDefinition[];
  initialEntriesByList: Record<number, StructuredListEntry[]>;
  availableParticipants: ParticipantSummary[];
  availableEvents: EventSummary[];
};

type ListDefinitionFormState = {
  name: string;
  description: string;
  column_one_title: string;
  column_one_value_type: StructuredListValueType;
  column_two_title: string;
  column_two_value_type: StructuredListValueType;
  is_active: boolean;
};

const valueTypeOptions: Array<{ value: StructuredListValueType; label: string }> = [
  { value: "text", label: "Freier Text" },
  { value: "participant", label: "Ein Teilnehmer" },
  { value: "participants", label: "Mehrere Teilnehmer" },
  { value: "event", label: "Ein Termin" },
];

const initialFormState: ListDefinitionFormState = {
  name: "",
  description: "",
  column_one_title: "Spalte 1",
  column_one_value_type: "text",
  column_two_title: "Spalte 2",
  column_two_value_type: "text",
  is_active: true,
};

function formFromDefinition(definition: StructuredListDefinition): ListDefinitionFormState {
  return {
    name: definition.name,
    description: definition.description ?? "",
    column_one_title: definition.column_one_title,
    column_one_value_type: definition.column_one_value_type,
    column_two_title: definition.column_two_title,
    column_two_value_type: definition.column_two_value_type,
    is_active: definition.is_active,
  };
}

function valueTypeLabel(valueType: StructuredListValueType) {
  return valueTypeOptions.find((option) => option.value === valueType)?.label ?? valueType;
}

export function ListManager({
  initialLists,
  initialEntriesByList,
  availableParticipants,
  availableEvents,
}: ListManagerProps) {
  const [lists, setLists] = useState(initialLists);
  const [entriesByList, setEntriesByList] = useState(initialEntriesByList);
  const [selectedListId, setSelectedListId] = useState<number | null>(initialLists[0]?.id ?? null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("Bereit");
  const [statusTone, setStatusTone] = useState<"neutral" | "success" | "error">("neutral");
  const [modalOpen, setModalOpen] = useState(false);
  const [editingListId, setEditingListId] = useState<number | null>(null);
  const [form, setForm] = useState(initialFormState);

  const filteredLists = useMemo(() => {
    const query = search.trim().toLowerCase();
    return lists.filter((definition) => {
      if (!query) {
        return true;
      }
      return `${definition.name} ${definition.description ?? ""}`.toLowerCase().includes(query);
    });
  }, [lists, search]);

  const selectedList = useMemo(
    () => lists.find((definition) => definition.id === selectedListId) ?? null,
    [lists, selectedListId]
  );

  function openCreate() {
    setEditingListId(null);
    setForm(initialFormState);
    setModalOpen(true);
  }

  function openEdit(definition: StructuredListDefinition) {
    setEditingListId(definition.id);
    setSelectedListId(definition.id);
    setForm(formFromDefinition(definition));
    setModalOpen(true);
  }

  async function saveDefinition(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus(editingListId ? "Liste wird gespeichert..." : "Liste wird erstellt...");
    setStatusTone("neutral");
    try {
      const payload = {
        name: form.name,
        description: form.description || null,
        column_one_title: form.column_one_title,
        column_one_value_type: form.column_one_value_type,
        column_two_title: form.column_two_title,
        column_two_value_type: form.column_two_value_type,
        is_active: form.is_active,
      };
      const saved = editingListId
        ? await browserApiFetch<StructuredListDefinition>(`/api/lists/${editingListId}`, {
            method: "PATCH",
            body: JSON.stringify(payload),
          })
        : await browserApiFetch<StructuredListDefinition>("/api/lists", {
            method: "POST",
            body: JSON.stringify(payload),
          });

      setLists((current) =>
        editingListId ? current.map((item) => (item.id === saved.id ? saved : item)) : [saved, ...current]
      );
      setEntriesByList((current) => ({ ...current, [saved.id]: current[saved.id] ?? [] }));
      setSelectedListId(saved.id);
      setModalOpen(false);
      setStatus(editingListId ? "Liste gespeichert" : "Liste erstellt");
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Liste konnte nicht gespeichert werden");
      setStatusTone("error");
    }
  }

  async function deleteDefinition(listId: number) {
    setStatus("Liste wird geloescht...");
    setStatusTone("neutral");
    try {
      await browserApiFetch(`/api/lists/${listId}`, { method: "DELETE" });
      const remainingLists = lists.filter((item) => item.id !== listId);
      setLists(remainingLists);
      setEntriesByList((current) => {
        const next = { ...current };
        delete next[listId];
        return next;
      });
      setSelectedListId((current) => (current === listId ? (remainingLists[0]?.id ?? null) : current));
      setStatus("Liste geloescht");
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Liste konnte nicht geloescht werden");
      setStatusTone("error");
    }
  }

  async function createEntry(listId: number, payload: { sort_index: number; column_one_value: Record<string, unknown>; column_two_value: Record<string, unknown> }) {
    setStatus("Eintrag wird erstellt...");
    setStatusTone("neutral");
    try {
      const created = await browserApiFetch<StructuredListEntry>(`/api/lists/${listId}/entries`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setEntriesByList((current) => ({
        ...current,
        [listId]: [...(current[listId] ?? []), created].sort((left, right) => left.sort_index - right.sort_index),
      }));
      setStatus("Eintrag erstellt");
      setStatusTone("success");
      return true;
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Eintrag konnte nicht erstellt werden");
      setStatusTone("error");
      return false;
    }
  }

  async function updateEntry(
    listId: number,
    entryId: number,
    payload: Partial<{ sort_index: number; column_one_value: Record<string, unknown>; column_two_value: Record<string, unknown> }>
  ) {
    setStatus("Eintrag wird gespeichert...");
    setStatusTone("neutral");
    try {
      const updated = await browserApiFetch<StructuredListEntry>(`/api/list-entries/${entryId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      setEntriesByList((current) => ({
        ...current,
        [listId]: (current[listId] ?? []).map((entry) => (entry.id === entryId ? updated : entry)),
      }));
      setStatus("Eintrag gespeichert");
      setStatusTone("success");
      return true;
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Eintrag konnte nicht gespeichert werden");
      setStatusTone("error");
      return false;
    }
  }

  async function deleteEntry(listId: number, entryId: number) {
    setStatus("Eintrag wird geloescht...");
    setStatusTone("neutral");
    try {
      await browserApiFetch(`/api/list-entries/${entryId}`, { method: "DELETE" });
      setEntriesByList((current) => ({
        ...current,
        [listId]: (current[listId] ?? []).filter((entry) => entry.id !== entryId),
      }));
      setStatus("Eintrag geloescht");
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Eintrag konnte nicht geloescht werden");
      setStatusTone("error");
    }
  }

  return (
    <div className="grid">
      {status !== "Bereit" ? <StatusBanner tone={statusTone} message={status} /> : null}

      <DataToolbar
        title="Listen"
        description="Globale Zweispalten-Listen, die du spaeter direkt an Tabellenbloecke koppeln kannst."
        actions={
          <button type="button" className="button-inline" onClick={openCreate}>
            Neue Liste
          </button>
        }
      />

      <article className="card">
        <div className="two-col">
          <label className="field-stack">
            <span className="field-label">Suche</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Listen durchsuchen" />
          </label>
          <div className="card">
            <div className="eyebrow">Ueberblick</div>
            <div className="status-row">
              <span className="pill">{filteredLists.length} sichtbar</span>
              <span className="pill">{lists.length} gesamt</span>
              <span className="pill">{selectedList ? (entriesByList[selectedList.id] ?? []).length : 0} Eintraege</span>
            </div>
          </div>
        </div>
      </article>

      <DataTable columns={["Liste", "Spalte 1", "Spalte 2", "Status", "Aktionen"]} emptyMessage="Noch keine Listen angelegt.">
        {filteredLists.map((definition) => (
          <tr
            key={definition.id}
            className={`table-row-clickable${selectedListId === definition.id ? " table-row-selected" : ""}`}
            onClick={() => setSelectedListId(definition.id)}
          >
            <td>
              <strong>{definition.name}</strong>
              <div className="muted">{definition.description || "Keine Beschreibung"}</div>
            </td>
            <td>
              {definition.column_one_title}
              <div className="muted">{valueTypeLabel(definition.column_one_value_type)}</div>
            </td>
            <td>
              {definition.column_two_title}
              <div className="muted">{valueTypeLabel(definition.column_two_value_type)}</div>
            </td>
            <td><span className="pill">{definition.is_active ? "Aktiv" : "Inaktiv"}</span></td>
            <td>
              <div className="table-actions table-actions-start">
                <button
                  type="button"
                  className="button-inline"
                  onClick={(event) => {
                    event.stopPropagation();
                    openEdit(definition);
                  }}
                >
                  Bearbeiten
                </button>
                <button
                  type="button"
                  className="button-inline button-danger"
                  onClick={(event) => {
                    event.stopPropagation();
                    void deleteDefinition(definition.id);
                  }}
                >
                  Loeschen
                </button>
              </div>
            </td>
          </tr>
        ))}
      </DataTable>

      {selectedList ? (
        <article className="card grid">
          <DataToolbar
            title={selectedList.name}
            description={selectedList.description || "Diese Liste ist direkt mit Tabellenbloecken verknuepfbar."}
          />
          <StructuredListTable
            definition={selectedList}
            entries={entriesByList[selectedList.id] ?? []}
            availableParticipants={availableParticipants}
            availableEvents={availableEvents}
            onCreateEntry={(payload) => createEntry(selectedList.id, payload)}
            onUpdateEntry={(entryId, payload) => updateEntry(selectedList.id, entryId, payload)}
            onDeleteEntry={(entryId) => deleteEntry(selectedList.id, entryId)}
          />
        </article>
      ) : (
        <article className="card">
          <p className="muted">Waehle zuerst eine Liste aus oder erstelle eine neue.</p>
        </article>
      )}

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editingListId ? "Liste bearbeiten" : "Liste erstellen"}
        description="Jede Liste hat genau zwei Spalten. Der Datentyp bestimmt, welche Eingabe spaeter im Tabellenblock und im Protokoll sichtbar ist."
      >
        <form className="grid" onSubmit={saveDefinition}>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Listenname</span>
              <input value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} required />
            </label>
            <label className="checkbox-line">
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={(event) => setForm((current) => ({ ...current, is_active: event.target.checked }))}
              />
              Aktiv
            </label>
          </div>
          <label className="field-stack">
            <span className="field-label">Beschreibung</span>
            <input
              value={form.description}
              onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              placeholder="Optional"
            />
          </label>
          <div className="two-col">
            <div className="card grid">
              <div className="eyebrow">Spalte 1</div>
              <label className="field-stack">
                <span className="field-label">Titel</span>
                <input
                  value={form.column_one_title}
                  onChange={(event) => setForm((current) => ({ ...current, column_one_title: event.target.value }))}
                  required
                />
              </label>
              <label className="field-stack">
                <span className="field-label">Datentyp</span>
                <select
                  value={form.column_one_value_type}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      column_one_value_type: event.target.value as StructuredListValueType,
                    }))
                  }
                >
                  {valueTypeOptions.map((option) => (
                    <option key={`list-column-one-type-${option.value}`} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="card grid">
              <div className="eyebrow">Spalte 2</div>
              <label className="field-stack">
                <span className="field-label">Titel</span>
                <input
                  value={form.column_two_title}
                  onChange={(event) => setForm((current) => ({ ...current, column_two_title: event.target.value }))}
                  required
                />
              </label>
              <label className="field-stack">
                <span className="field-label">Datentyp</span>
                <select
                  value={form.column_two_value_type}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      column_two_value_type: event.target.value as StructuredListValueType,
                    }))
                  }
                >
                  {valueTypeOptions.map((option) => (
                    <option key={`list-column-two-type-${option.value}`} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>
          <div className="table-toolbar-actions">
            <button type="submit" className="button-inline">
              {editingListId ? "Liste speichern" : "Liste erstellen"}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
