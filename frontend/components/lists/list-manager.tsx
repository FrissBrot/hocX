"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { StructuredListTable } from "@/components/lists/structured-list-table";
import { Modal } from "@/components/ui/modal";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import {
  DocumentTemplate,
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
  documentTemplates?: DocumentTemplate[];
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
  documentTemplates = [],
}: ListManagerProps) {
  const showToast = useToast();
  const [lists, setLists] = useState(initialLists);
  const [entriesByList, setEntriesByList] = useState(initialEntriesByList);
  const [selectedListId, setSelectedListId] = useState<number | null>(initialLists[0]?.id ?? null);
  const [search, setSearch] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editingListId, setEditingListId] = useState<number | null>(null);
  const [form, setForm] = useState(initialFormState);

  // Export modal state
  const landscapeTemplates = documentTemplates.filter(
    (t) => t.is_active && (t.configuration_json as { options?: { orientation?: string } })?.options?.orientation === "landscape"
  );
  const [exportModalOpen, setExportModalOpen] = useState(false);
  const [exportTemplateId, setExportTemplateId] = useState<number | "">(landscapeTemplates[0]?.id ?? "");
  const [exportListId, setExportListId] = useState<number | "">(initialLists[0]?.id ?? "");
  const [exportGroupBy, setExportGroupBy] = useState<"" | "column_one" | "column_two">("");
  const [exportSortBy, setExportSortBy] = useState<"" | "column_one" | "column_two">("");
  const [exportSortDirection, setExportSortDirection] = useState<"asc" | "desc">("asc");
  const [exportFilterColumn, setExportFilterColumn] = useState<"" | "column_one" | "column_two">("");
  const [exportFilterParticipantId, setExportFilterParticipantId] = useState<number | "">("");
  const [exportFilterEventId, setExportFilterEventId] = useState<number | "">("");
  const [exportFilterText, setExportFilterText] = useState("");
  const [exportBusy, setExportBusy] = useState(false);
  const [exportUrl, setExportUrl] = useState<string | null>(null);
  const [templateDropdownOpen, setTemplateDropdownOpen] = useState(false);
  const templateDropdownRef = useRef<HTMLDivElement>(null);
  const [listDropdownOpen, setListDropdownOpen] = useState(false);
  const [listDropdownSearch, setListDropdownSearch] = useState("");
  const listDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!templateDropdownOpen) return;
    function handleClick(e: MouseEvent) {
      if (templateDropdownRef.current && !templateDropdownRef.current.contains(e.target as Node)) {
        setTemplateDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [templateDropdownOpen]);

  useEffect(() => {
    if (!listDropdownOpen) return;
    function handleClick(e: MouseEvent) {
      if (listDropdownRef.current && !listDropdownRef.current.contains(e.target as Node)) {
        setListDropdownOpen(false);
        setListDropdownSearch("");
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [listDropdownOpen]);

  const listDropdownFiltered = useMemo(() => {
    if (!listDropdownSearch.trim()) return lists;
    const q = listDropdownSearch.toLowerCase();
    return lists.filter((l) => l.name.toLowerCase().includes(q));
  }, [lists, listDropdownSearch]);

  function toggleExportSort(col: "column_one" | "column_two") {
    if (exportSortBy === col) {
      setExportSortDirection((d) => d === "asc" ? "desc" : "asc");
    } else {
      setExportSortBy(col);
      setExportSortDirection("asc");
    }
    clearExportUrl();
  }

  const exportListDef = useMemo(
    () => lists.find((l) => l.id === exportListId) ?? null,
    [lists, exportListId]
  );

  const exportFilteredEntries = useMemo(() => {
    if (!exportListId) return [];
    const entries = entriesByList[exportListId as number] ?? [];
    if (!exportFilterColumn || !exportListDef) return entries;
    const valueType = exportFilterColumn === "column_one" ? exportListDef.column_one_value_type : exportListDef.column_two_value_type;
    return entries.filter((entry) => {
      const value = exportFilterColumn === "column_one" ? entry.column_one_value : entry.column_two_value;
      if (valueType === "participant") {
        if (!exportFilterParticipantId) return true;
        return Number(value.participant_id) === exportFilterParticipantId;
      }
      if (valueType === "participants") {
        if (!exportFilterParticipantId) return true;
        const ids = Array.isArray(value.participant_ids) ? (value.participant_ids as unknown[]).map(Number) : [];
        return ids.includes(exportFilterParticipantId as number);
      }
      if (valueType === "event") {
        if (!exportFilterEventId) return true;
        return Number(value.event_id) === exportFilterEventId;
      }
      if (!exportFilterText) return true;
      return String(value.text_value ?? "").toLowerCase().includes(exportFilterText.toLowerCase());
    });
  }, [entriesByList, exportListId, exportFilterColumn, exportFilterParticipantId, exportFilterEventId, exportFilterText, exportListDef]);

  function clearExportUrl() { setExportUrl(null); }

  function triggerDownload(url: string) {
    const a = document.createElement("a");
    a.href = `${url}?download=1`;
    a.target = "_blank";
    a.rel = "noreferrer";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  async function handlePdfClick() {
    if (exportBusy || !exportListId || !exportTemplateId) return;
    if (exportUrl) { triggerDownload(exportUrl); return; }
    setExportBusy(true);
    try {
      const result = await browserApiFetch<{ content_url?: string | null }>("/api/exports/lists", {
        method: "POST",
        body: JSON.stringify({
          template_id: exportTemplateId,
          list_definition_id: exportListId,
          group_by: exportGroupBy,
          sort_by: exportSortBy,
          sort_direction: exportSortDirection,
          filter_column: exportFilterColumn,
          filter_participant_id: exportFilterParticipantId || null,
          filter_event_id: exportFilterEventId || null,
          filter_text: exportFilterText || null,
        }),
      });
      const url = result.content_url ?? null;
      setExportUrl(url);
      if (url) triggerDownload(url);
    } catch {
      // keep accessible
    } finally {
      setExportBusy(false);
    }
  }

  const [hoveredListId, setHoveredListId] = useState<number | null>(null);

  const filteredLists = useMemo(() => {
    const query = search.trim().toLowerCase();
    return lists
      .filter((definition) => !query || `${definition.name} ${definition.description ?? ""}`.toLowerCase().includes(query))
      .sort((a, b) => a.name.localeCompare(b.name));
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
      showToast(editingListId ? "Liste gespeichert" : "Liste erstellt", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Liste konnte nicht gespeichert werden", "error");
    }
  }

  async function deleteDefinition(listId: number) {
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
      showToast("Liste geloescht", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Liste konnte nicht geloescht werden", "error");
    }
  }

  async function createEntry(listId: number, payload: { sort_index: number; column_one_value: Record<string, unknown>; column_two_value: Record<string, unknown> }) {
    try {
      const created = await browserApiFetch<StructuredListEntry>(`/api/lists/${listId}/entries`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setEntriesByList((current) => ({
        ...current,
        [listId]: [...(current[listId] ?? []), created].sort((left, right) => left.sort_index - right.sort_index),
      }));
      showToast("Eintrag erstellt", "success");
      return true;
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Eintrag konnte nicht erstellt werden", "error");
      return false;
    }
  }

  async function updateEntry(
    listId: number,
    entryId: number,
    payload: Partial<{ sort_index: number; column_one_value: Record<string, unknown>; column_two_value: Record<string, unknown> }>
  ) {
    try {
      const updated = await browserApiFetch<StructuredListEntry>(`/api/list-entries/${entryId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      setEntriesByList((current) => ({
        ...current,
        [listId]: (current[listId] ?? []).map((entry) => (entry.id === entryId ? updated : entry)),
      }));
      showToast("Eintrag gespeichert", "success");
      return true;
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Eintrag konnte nicht gespeichert werden", "error");
      return false;
    }
  }

  async function deleteEntry(listId: number, entryId: number) {
    try {
      await browserApiFetch(`/api/list-entries/${entryId}`, { method: "DELETE" });
      setEntriesByList((current) => ({
        ...current,
        [listId]: (current[listId] ?? []).filter((entry) => entry.id !== entryId),
      }));
      showToast("Eintrag geloescht", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Eintrag konnte nicht geloescht werden", "error");
    }
  }

  return (
    <div className="grid">
      <div className="list-manager-layout">

        {/* Left sidebar */}
        <div className="list-manager-sidebar">
          <label className="field-stack" style={{ marginBottom: 8 }}>
            <span className="field-label">Suche</span>
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Listen suchen…" />
          </label>

          {/* List items — scrollable, fills available height */}
          <div className="list-manager-items">
            {filteredLists.length === 0 ? (
              <span className="muted" style={{ fontSize: "0.85rem", padding: "6px 4px", display: "block" }}>Keine Listen</span>
            ) : filteredLists.map((definition) => {
              const isSelected = selectedListId === definition.id;
              const isHovered = hoveredListId === definition.id;
              return (
                <div
                  key={definition.id}
                  className="list-manager-item-wrap"
                  onMouseEnter={() => setHoveredListId(definition.id)}
                  onMouseLeave={() => setHoveredListId(null)}
                >
                  <button
                    type="button"
                    onClick={() => setSelectedListId(definition.id)}
                    className={`list-manager-item-button${isSelected ? " list-manager-item-button-active" : ""}`}
                    style={{ paddingRight: isHovered && !isSelected ? 58 : 10 }}
                  >
                    {definition.name}
                  </button>
                  {isHovered && !isSelected && (
                    <div className="list-manager-item-actions">
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); openEdit(definition); }}
                        title="Bearbeiten"
                        className="list-manager-item-action"
                      >
                        ✎
                      </button>
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); void deleteDefinition(definition.id); }}
                        title="Löschen"
                        className="list-manager-item-action list-manager-item-action-danger"
                      >
                        ✕
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* New list button pinned at bottom */}
          <button type="button" className="domain-add-trigger" onClick={openCreate} style={{ marginTop: 10 }}>
            + Neue Liste
          </button>
        </div>

        {/* Right: content */}
        <div className="list-manager-content">
          {selectedList ? (
            <div className="grid">
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
                <div>
                  <h2 className="list-manager-title">{selectedList.name}</h2>
                  {selectedList.description && (
                    <p className="muted" style={{ margin: "3px 0 0", fontSize: "0.85rem" }}>{selectedList.description}</p>
                  )}
                </div>
                <div className="table-toolbar-actions">
                  {landscapeTemplates.length > 0 && (
                    <button type="button" className="button-inline button-ghost" onClick={() => { setExportListId(selectedListId ?? ""); setExportUrl(null); setExportModalOpen(true); }}>
                      Export
                    </button>
                  )}
                  <button type="button" className="button-inline button-ghost" onClick={() => openEdit(selectedList)}>
                    Bearbeiten
                  </button>
                </div>
              </div>
              <StructuredListTable
                definition={selectedList}
                entries={entriesByList[selectedList.id] ?? []}
                availableParticipants={availableParticipants}
                availableEvents={availableEvents}
                fullWidth
                onCreateEntry={(payload) => createEntry(selectedList.id, payload)}
                onUpdateEntry={(entryId, payload) => updateEntry(selectedList.id, entryId, payload)}
                onDeleteEntry={(entryId) => deleteEntry(selectedList.id, entryId)}
              />
            </div>
          ) : (
            <p className="muted">Wähle eine Liste aus oder erstelle eine neue.</p>
          )}
        </div>
      </div>

      <Modal
        open={exportModalOpen}
        onClose={() => setExportModalOpen(false)}
        title="Liste exportieren"
        size="wide"
      >
        <div style={{ display: "flex", gap: 24, height: "min(640px, calc(100dvh - 200px))", minHeight: 0 }}>
          {/* Left: options */}
          <div style={{ width: 260, flexShrink: 0, display: "flex", flexDirection: "column", gap: 20, overflowY: "auto" }}>

            {/* List dropdown with search */}
            <div>
              <div className="field-label" style={{ marginBottom: 8 }}>Liste</div>
              <div ref={listDropdownRef} style={{ position: "relative" }}>
                <button
                  type="button"
                  onClick={() => { setListDropdownOpen((v) => !v); setListDropdownSearch(""); }}
                  style={{ width: "100%", textAlign: "left", padding: "7px 10px", borderRadius: 6, border: "1px solid var(--border)", backgroundColor: "var(--surface)", color: "var(--text)", fontSize: "0.9rem", cursor: "pointer", minHeight: 0, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6 }}
                >
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {exportListDef?.name ?? "Liste wählen…"}
                  </span>
                  <span style={{ flexShrink: 0, opacity: 0.5 }}>▾</span>
                </button>
                {listDropdownOpen && (
                  <div style={{ position: "absolute", top: "calc(100% + 4px)", left: 0, right: 0, zIndex: 70, backgroundColor: "var(--panel-solid)", border: "1px solid var(--border)", borderRadius: 6, boxShadow: "0 6px 20px rgba(0,0,0,0.2)", overflow: "hidden" }}>
                    <div style={{ padding: "6px 8px", borderBottom: "1px solid var(--border)" }}>
                      <input
                        autoFocus
                        type="text"
                        placeholder="Suchen…"
                        value={listDropdownSearch}
                        onChange={(e) => setListDropdownSearch(e.target.value)}
                        style={{ width: "100%", boxSizing: "border-box", padding: "4px 8px", borderRadius: 4, border: "1px solid var(--border)", backgroundColor: "var(--surface)", color: "var(--text)", fontSize: "0.88rem", minHeight: 0, outline: "none" }}
                      />
                    </div>
                    <div style={{ maxHeight: 220, overflowY: "auto", padding: "4px 0" }}>
                      {listDropdownFiltered.length === 0 ? (
                        <div className="muted" style={{ padding: "8px 12px", fontSize: "0.88rem" }}>Keine Listen gefunden</div>
                      ) : listDropdownFiltered.map((l) => (
                        <button
                          key={l.id}
                          type="button"
                          onClick={() => { setExportListId(l.id); setExportFilterColumn(""); setExportFilterParticipantId(""); setExportFilterEventId(""); setExportFilterText(""); setExportGroupBy(""); setExportSortBy(""); clearExportUrl(); setListDropdownOpen(false); setListDropdownSearch(""); }}
                          style={{ display: "block", width: "100%", textAlign: "left", padding: "7px 12px", background: "none", border: "none", color: "var(--text)", cursor: "pointer", fontSize: "0.9rem", minHeight: 0, fontWeight: exportListId === l.id ? 700 : 400 }}
                        >
                          {l.name}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Group by */}
            {exportListDef && (
              <div>
                <div className="field-label" style={{ marginBottom: 8 }}>Gruppieren nach</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {(["", "column_one", "column_two"] as const).map((col) => (
                    <button
                      key={col}
                      type="button"
                      className={exportGroupBy === col ? "tag-filter-chip tag-filter-chip-active" : "tag-filter-chip"}
                      style={{ width: "auto", minHeight: 0 }}
                      onClick={() => { setExportGroupBy(col); clearExportUrl(); }}
                    >
                      {col === "" ? "Keine" : col === "column_one" ? exportListDef.column_one_title : exportListDef.column_two_title}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Filter */}
            {exportListDef && (
              <div>
                <div className="field-label" style={{ marginBottom: 8 }}>Filtern nach Spalte</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {(["", "column_one", "column_two"] as const).map((col) => (
                    <button
                      key={col}
                      type="button"
                      className={exportFilterColumn === col ? "tag-filter-chip tag-filter-chip-active" : "tag-filter-chip"}
                      style={{ width: "auto", minHeight: 0 }}
                      onClick={() => { setExportFilterColumn(col); setExportFilterParticipantId(""); setExportFilterEventId(""); setExportFilterText(""); clearExportUrl(); }}
                    >
                      {col === "" ? "Kein Filter" : col === "column_one" ? exportListDef.column_one_title : exportListDef.column_two_title}
                    </button>
                  ))}
                </div>
                {exportFilterColumn && (() => {
                  const vtype = exportFilterColumn === "column_one" ? exportListDef.column_one_value_type : exportListDef.column_two_value_type;
                  if (vtype === "participant" || vtype === "participants") {
                    return (
                      <select
                        className="input"
                        value={exportFilterParticipantId}
                        onChange={(e) => { setExportFilterParticipantId(e.target.value ? Number(e.target.value) : ""); clearExportUrl(); }}
                        style={{ marginTop: 8 }}
                      >
                        <option value="">Alle</option>
                        {availableParticipants.map((p) => <option key={p.id} value={p.id}>{p.display_name}</option>)}
                      </select>
                    );
                  }
                  if (vtype === "event") {
                    return (
                      <select
                        className="input"
                        value={exportFilterEventId}
                        onChange={(e) => { setExportFilterEventId(e.target.value ? Number(e.target.value) : ""); clearExportUrl(); }}
                        style={{ marginTop: 8 }}
                      >
                        <option value="">Alle</option>
                        {[...availableEvents].sort((a, b) => a.event_date.localeCompare(b.event_date)).map((e) => <option key={e.id} value={e.id}>{e.event_date} — {e.title}</option>)}
                      </select>
                    );
                  }
                  return (
                    <input
                      className="input"
                      type="text"
                      placeholder="Suchbegriff…"
                      value={exportFilterText}
                      onChange={(e) => { setExportFilterText(e.target.value); clearExportUrl(); }}
                      style={{ marginTop: 8 }}
                    />
                  );
                })()}
              </div>
            )}

            {/* Action bar pinned to bottom */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: "auto", paddingTop: 8 }}>
              <button
                type="button"
                className="pdf-icon-link pdf-icon-link-success"
                style={{ minWidth: 56, textAlign: "center" }}
                onClick={() => void handlePdfClick()}
                disabled={!exportTemplateId || !exportListId}
              >
                {exportBusy ? "…" : exportUrl ? "PDF ↓" : "PDF"}
              </button>
              <button
                type="button"
                className="pdf-icon-link"
                style={{ minWidth: 56, textAlign: "center", backgroundColor: "#a78bfa", color: "#fff", opacity: 0.5, cursor: "not-allowed" }}
                disabled
              >
                MD
              </button>
              <div style={{ flex: 1 }} />
              {landscapeTemplates.length > 1 && (
                <div ref={templateDropdownRef} style={{ position: "relative" }}>
                  <button
                    type="button"
                    onClick={() => setTemplateDropdownOpen((v) => !v)}
                    style={{ padding: "5px 10px", borderRadius: 6, border: "1px solid var(--border)", backgroundColor: "transparent", color: "var(--text)", fontSize: "0.85rem", cursor: "pointer", minHeight: 0, whiteSpace: "nowrap", maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis" }}
                  >
                    {landscapeTemplates.find((t) => t.id === exportTemplateId)?.name ?? "Vorlage"} ▾
                  </button>
                  {templateDropdownOpen && (
                    <div style={{ position: "absolute", right: 0, bottom: "calc(100% + 4px)", zIndex: 70, backgroundColor: "var(--panel-solid)", border: "1px solid var(--border)", borderRadius: 6, boxShadow: "0 6px 20px rgba(0,0,0,0.2)", padding: "4px 0", minWidth: 160 }}>
                      {landscapeTemplates.map((t) => (
                        <button
                          key={t.id}
                          type="button"
                          onClick={() => { setExportTemplateId(t.id); setTemplateDropdownOpen(false); clearExportUrl(); }}
                          style={{ display: "block", width: "100%", textAlign: "left", padding: "6px 12px", background: "none", border: "none", color: "var(--text)", cursor: "pointer", fontSize: "0.9rem", minHeight: 0, fontWeight: exportTemplateId === t.id ? 700 : 400 }}
                        >
                          {t.name}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Right: live preview */}
          <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", overflowY: "auto", borderLeft: "1px solid var(--border)", paddingLeft: 24 }}>
            {exportListDef ? (
              <>
                <div className="field-label" style={{ marginBottom: 12 }}>
                  Vorschau · {exportFilteredEntries.length} Einträge
                </div>
                <StructuredListTable
                  definition={exportListDef}
                  entries={exportFilteredEntries}
                  availableParticipants={availableParticipants}
                  availableEvents={availableEvents}
                  editable={false}
                  groupByColumn={exportGroupBy}
                  sortByColumn={exportSortBy}
                  sortDirection={exportSortDirection}
                  onHeaderSort={toggleExportSort}
                  onCreateEntry={async () => false}
                  onUpdateEntry={async () => false}
                  onDeleteEntry={async () => {}}
                />
              </>
            ) : (
              <p className="muted">Wähle eine Liste aus.</p>
            )}
          </div>
        </div>
      </Modal>

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
