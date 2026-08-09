"use client";

import { useState } from "react";

import { useConfirm } from "@/contexts/confirm-context";
import { Modal } from "@/components/ui/modal";
import { DateInput } from "@/components/ui/date-input";
import { TagInput } from "@/components/ui/tag-input";
import { EventDetailForm } from "@/components/protocol/planning/event-detail-form";
import { fetchCycleEvents } from "@/lib/api/cycle-events";
import { EventSummary, ParticipantSummary } from "@/types/api";
import type { TagConfig } from "@/lib/hooks/use-tag-config";
import { formatDateRange } from "@/lib/utils/format";

// Mirrors the editor's own ProtocolEventDraft shape so onCreateEvent can be wired
// directly to the existing createEventFromBlock(blockId, blockConfig, draft) — same
// tag-forcing/participant-count handling, no duplicated logic.
type NewEventDraft = {
  event_date: string;
  event_end_date: string;
  tag: string;
  title: string;
  description: string;
  participant_count: string;
};

type EventOverviewModalProps = {
  open: boolean;
  onClose: () => void;
  protocolId: number;
  forcedTag: string;
  allowEndDate: boolean;
  protocolDate: string | null;
  /** Exactly what's already shown inline (same filter as the read-only table) — no separate fetch/scope for the main list. */
  visibleEvents: EventSummary[];
  availableParticipants: ParticipantSummary[];
  knownEventTags: string[];
  tagConfig: TagConfig;
  onTagColorChange: (tag: string, color: string) => Promise<void>;
  onTagRename: (oldTag: string, newTag: string) => Promise<void>;
  onCreateEvent: (draft: NewEventDraft) => Promise<EventSummary | null>;
  onUpdateEvent: (eventId: number, patch: Partial<EventSummary>) => Promise<boolean>;
  onDeleteEvent: (eventId: number) => Promise<void>;
};

function emptyDraft(protocolDate: string | null, forcedTag: string): NewEventDraft {
  return {
    event_date: protocolDate ?? "",
    event_end_date: "",
    tag: forcedTag,
    title: "",
    description: "",
    participant_count: "0",
  };
}

/**
 * Planning-mode ("geplant") "Terminübersicht" popup for Terminliste (event_list) blocks
 * and embedded Terminlisten in Matrix-Zellen. Main list = exactly what's already visible
 * inline (visibleEvents prop, same filter as the read-only table) — no separate default
 * scope. "+ Hinzufügen" opens a search over existing Termine (aktueller Zyklus/alle, mit
 * Suche); picking one assigns it the block's forced tag so it becomes visible — the tag on
 * the Termin changes, never the block's filter config. A "+ Neuer Termin" option within the
 * same panel creates a brand-new Termin (auto-tagged the same way as everywhere else).
 */
export function EventOverviewModal({
  open,
  onClose,
  protocolId,
  forcedTag,
  allowEndDate,
  protocolDate,
  visibleEvents,
  availableParticipants,
  knownEventTags,
  tagConfig,
  onTagColorChange,
  onTagRename,
  onCreateEvent,
  onUpdateEvent,
  onDeleteEvent,
}: EventOverviewModalProps) {
  const [showAddPanel, setShowAddPanel] = useState(false);
  const [addScope, setAddScope] = useState<"current" | "all">("current");
  const [addSearch, setAddSearch] = useState("");
  const [addResults, setAddResults] = useState<EventSummary[]>([]);
  const [addLoading, setAddLoading] = useState(false);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newDraft, setNewDraft] = useState<NewEventDraft>(() => emptyDraft(protocolDate, forcedTag));
  const [creating, setCreating] = useState(false);
  const [assigningId, setAssigningId] = useState<number | null>(null);
  const [detailEvent, setDetailEvent] = useState<EventSummary | null>(null);
  const confirm = useConfirm();

  const visibleIds = new Set(visibleEvents.map((e) => e.id));

  async function loadAddResults(scope: "current" | "all", search: string) {
    setAddLoading(true);
    try {
      const result = await fetchCycleEvents(protocolId, { scope, search, limit: 500 });
      setAddResults(result.items.filter((e) => !visibleIds.has(e.id)));
    } finally {
      setAddLoading(false);
    }
  }

  function openAddPanel() {
    setShowAddPanel(true);
    setShowCreateForm(false);
    setAddSearch("");
    void loadAddResults(addScope, "");
  }

  function onAddScopeChange(next: "current" | "all") {
    setAddScope(next);
    void loadAddResults(next, addSearch);
  }

  function onAddSearchChange(value: string) {
    setAddSearch(value);
    void loadAddResults(addScope, value);
  }

  async function handleAssignExisting(evt: EventSummary) {
    setAssigningId(evt.id);
    const ok = await onUpdateEvent(evt.id, { tag: forcedTag || evt.tag });
    setAssigningId(null);
    if (ok) {
      setShowAddPanel(false);
    }
  }

  async function handleCreate() {
    if (!newDraft.event_date.trim() || !newDraft.title.trim()) return;
    setCreating(true);
    const created = await onCreateEvent(newDraft);
    setCreating(false);
    if (created) {
      setNewDraft(emptyDraft(protocolDate, forcedTag));
      setShowCreateForm(false);
      setShowAddPanel(false);
    }
  }

  async function handleUpdate(eventId: number, patch: Partial<EventSummary>) {
    setDetailEvent((current) => (current && current.id === eventId ? { ...current, ...patch } : current));
    await onUpdateEvent(eventId, patch);
  }

  async function handleDelete(eventId: number, title: string) {
    if (
      !(await confirm({
        message: `Termin "${title}" endgültig löschen? Das entfernt ihn aus allen Protokollen.`,
        tone: "danger",
        confirmLabel: "Löschen"
      }))
    )
      return;
    await onDeleteEvent(eventId);
  }

  return (
    <Modal open={open} onClose={onClose} title="Terminübersicht" size="fullscreen">
      <div className="event-overview-modal">
        {visibleEvents.length === 0 ? (
          <p className="muted">Keine Termine angezeigt.</p>
        ) : (
          <div className="event-table-wrap event-table-wrap-scrollable event-overview-table-wrap">
            <table className="data-table event-table event-table-compact">
              <colgroup>
                <col style={{ width: "16%" }} />
                <col style={{ width: "14%" }} />
                <col style={{ width: "22%" }} />
                <col style={{ width: "auto" }} />
                <col style={{ width: "40px" }} />
              </colgroup>
              <thead>
                <tr>
                  <th>Datum</th>
                  <th>Tag</th>
                  <th>Titel</th>
                  <th>Beschreibung</th>
                  <th aria-label="Aktionen" />
                </tr>
              </thead>
              <tbody>
                {visibleEvents.map((eventRow) => (
                  <tr key={eventRow.id} className="table-row-clickable" onClick={() => setDetailEvent(eventRow)}>
                    <td>{formatDateRange(eventRow.event_date, eventRow.event_end_date)}</td>
                    <td>{eventRow.tag || <span className="muted">—</span>}</td>
                    <td>{eventRow.title}</td>
                    <td>{eventRow.description || <span className="muted">—</span>}</td>
                    <td>
                      <button
                        type="button"
                        className="button-ghost button-icon button-icon-danger"
                        title="Termin endgültig löschen"
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleDelete(eventRow.id, eventRow.title);
                        }}
                      >
                        x
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {!showAddPanel ? (
          <div className="modal-actions">
            <button type="button" className="button-inline" onClick={openAddPanel}>
              + Hinzufügen
            </button>
          </div>
        ) : (
          <div className="event-overview-add-panel">
            <div className="editor-planning-toolbar" style={{ justifyContent: "space-between" }}>
              <div className="list-block-config-bar">
                <button
                  type="button"
                  className={`button-toggle${addScope === "current" ? " button-toggle-active" : ""}`}
                  onClick={() => onAddScopeChange("current")}
                >
                  Aktueller Zyklus
                </button>
                <button
                  type="button"
                  className={`button-toggle${addScope === "all" ? " button-toggle-active" : ""}`}
                  onClick={() => onAddScopeChange("all")}
                >
                  Alle Termine
                </button>
              </div>
              <input
                className="input"
                value={addSearch}
                onChange={(e) => onAddSearchChange(e.target.value)}
                placeholder="Suche nach Titel oder Tag…"
              />
            </div>

            {addLoading ? (
              <p className="muted">Lädt…</p>
            ) : addResults.length === 0 ? (
              <p className="muted">Keine passenden Termine gefunden.</p>
            ) : (
              <div className="participant-check-grid">
                {addResults.map((evt) => (
                  <button
                    key={evt.id}
                    type="button"
                    className="candidate-card candidate-card-pick"
                    disabled={assigningId === evt.id}
                    onClick={() => void handleAssignExisting(evt)}
                  >
                    <div className="candidate-card-toolbar">
                      <span className="candidate-card-pick-icon">+</span>
                      <span />
                    </div>
                    <div className="candidate-card-body">
                      <div>{evt.title ?? `Termin ${evt.id}`}</div>
                      <div className="muted">
                        {evt.event_date}
                        {evt.tag ? ` · ${evt.tag}` : ""}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}

            {showCreateForm ? (
              <div className="event-row-new grid" style={{ gap: 8, marginTop: 12 }}>
                <div className={`event-date-fields${allowEndDate ? " event-date-fields-range" : ""}`}>
                  <DateInput
                    className="event-field-date"
                    value={newDraft.event_date}
                    disabled={creating}
                    onChange={(value) => setNewDraft((d) => ({ ...d, event_date: value }))}
                  />
                  {allowEndDate ? (
                    <DateInput
                      className="event-field-date"
                      value={newDraft.event_end_date}
                      disabled={creating}
                      onChange={(value) => setNewDraft((d) => ({ ...d, event_end_date: value }))}
                    />
                  ) : null}
                </div>
                <TagInput
                  value={forcedTag || newDraft.tag}
                  onChange={(v) => setNewDraft((d) => ({ ...d, tag: v }))}
                  suggestions={knownEventTags}
                  placeholder="Tag"
                  multi={false}
                  readOnly={Boolean(forcedTag) || creating}
                  tagConfig={tagConfig}
                  onTagColorChange={onTagColorChange}
                  onTagRename={onTagRename}
                />
                <input
                  className="event-field-title"
                  value={newDraft.title}
                  disabled={creating}
                  onChange={(e) => setNewDraft((d) => ({ ...d, title: e.target.value }))}
                  placeholder="Titel"
                />
                <input
                  className="event-field-description"
                  value={newDraft.description}
                  disabled={creating}
                  onChange={(e) => setNewDraft((d) => ({ ...d, description: e.target.value }))}
                  placeholder="Beschreibung"
                />
                <div className="modal-actions">
                  <button type="button" className="button-ghost" disabled={creating} onClick={() => setShowCreateForm(false)}>
                    Abbrechen
                  </button>
                  <button type="button" className="button-primary" disabled={creating} onClick={() => void handleCreate()}>
                    {creating ? "…" : "Termin anlegen"}
                  </button>
                </div>
              </div>
            ) : (
              <div className="modal-actions">
                <button type="button" className="button-ghost" onClick={() => setShowAddPanel(false)}>
                  Schliessen
                </button>
                <button type="button" className="button-inline" onClick={() => setShowCreateForm(true)}>
                  + Neuer Termin
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      <Modal
        open={Boolean(detailEvent)}
        onClose={() => setDetailEvent(null)}
        title={detailEvent?.title || "Termin"}
        description={detailEvent ? formatDateRange(detailEvent.event_date, detailEvent.event_end_date) : undefined}
        size="wide"
      >
        {detailEvent ? (
          <EventDetailForm
            event={detailEvent}
            allowEndDate={allowEndDate}
            availableParticipants={availableParticipants}
            knownEventTags={knownEventTags}
            tagConfig={tagConfig}
            onTagColorChange={onTagColorChange}
            onTagRename={onTagRename}
            onUpdate={(patch) => handleUpdate(detailEvent.id, patch)}
          />
        ) : null}
      </Modal>
    </Modal>
  );
}
