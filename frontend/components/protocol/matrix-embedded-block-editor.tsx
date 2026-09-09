"use client";

import { ReactNode, useEffect, useMemo, useRef, useState } from "react";

import { useConfirm } from "@/contexts/confirm-context";
import { Badge } from "@/components/ui/badge";
import { DateInput } from "@/components/ui/date-input";
import { LightboxImage } from "@/components/ui/lightbox-image";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { EventOverviewModal } from "@/components/protocol/planning/event-overview-modal";
import { PlanningIconTrigger } from "@/components/protocol/planning/planning-icon-trigger";
import { TagConfig } from "@/lib/hooks/use-tag-config";
import { formatDateRange } from "@/lib/utils/format";
import { EventSummary, ParticipantSummary, ProtocolSummary } from "@/types/api";
import {
  ATTENDANCE_OPTIONS,
  EMBEDDED_FORM_VALUE_OPTIONS,
  MatrixEmbeddedBlock,
  ProtocolEventDraft,
  asObject,
  attendanceParticipants,
  canCreateProtocolEventDraft,
  compareIsoDate,
  createEmbeddedFormRow,
  createInlineProtocolEventDraft,
  formatShortDate,
  nextEmbeddedItemId,
} from "@/components/protocol/protocol-editor-shared";

export function MatrixEmbeddedBlockEditor({
  embeddedBlock,
  protocol,
  availableParticipants,
  availableEvents,
  matrixColumn,
  editable = true,
  updateEmbeddedBlock,
  openMultiParticipantPicker,
  createEvent,
  updateEvent,
  deleteEvent,
  currentCycleYear,
  cycleConfigId,
  onEventContextMenu,
  isPlanningMode,
  knownEventTags,
  tagConfig,
  onTagColorChange,
  onTagRename,
}: {
  embeddedBlock: MatrixEmbeddedBlock;
  protocol: ProtocolSummary;
  availableParticipants: ParticipantSummary[];
  availableEvents: EventSummary[];
  matrixColumn?: Record<string, any>;
  editable?: boolean;
  updateEmbeddedBlock: (updater: (current: MatrixEmbeddedBlock) => MatrixEmbeddedBlock, persist?: boolean) => void;
  openMultiParticipantPicker: (row: Record<string, any>) => void;
  createEvent: (forcedTag: string, draft: ProtocolEventDraft) => Promise<EventSummary | null>;
  updateEvent: (eventId: string, patch: Partial<EventSummary>) => Promise<boolean>;
  deleteEvent: (eventId: string) => Promise<void>;
  currentCycleYear: number | null;
  cycleConfigId: string | null;
  onEventContextMenu: (nativeEvent: React.MouseEvent, eventRow: EventSummary) => void;
  isPlanningMode: boolean;
  knownEventTags: string[];
  tagConfig: TagConfig;
  onTagColorChange: (tag: string, color: string) => Promise<void>;
  onTagRename: (oldTag: string, newTag: string) => Promise<void>;
}) {
  const confirm = useConfirm();
  const elementTypeId = Number(embeddedBlock.element_type_id ?? 0);
  const embeddedConfig = asObject(embeddedBlock.configuration_snapshot_json);
  const sortedEvents = [...availableEvents].sort((left, right) => compareIsoDate(left.event_date, right.event_date));
  const embeddedBlockClassName = "matrix-embedded-block";
  const eligibleAttendanceParticipants = useMemo(
    () => attendanceParticipants(availableParticipants),
    [availableParticipants]
  );
  const [embeddedEventDrafts, setEmbeddedEventDrafts] = useState<Record<string, Partial<EventSummary>>>({});
  const embeddedEventAutosaveTimers = useRef<Record<string, number>>({});
  const forcedEmbeddedTag =
    (embeddedConfig.event_use_column_tag_filter === true ? String(matrixColumn?.event_tag_filter || matrixColumn?.title || "").trim() : "") ||
    String(embeddedConfig.event_tag_filter ?? "").trim();
  const [newEmbeddedEventDraft, setNewEmbeddedEventDraft] = useState<ProtocolEventDraft>(() =>
    createInlineProtocolEventDraft(protocol.protocol_date, forcedEmbeddedTag)
  );
  const [showNewEmbeddedEventRow, setShowNewEmbeddedEventRow] = useState(false);
  const [creatingEmbeddedEvent, setCreatingEmbeddedEvent] = useState(false);
  const [showEmbeddedEventOverview, setShowEmbeddedEventOverview] = useState(false);
  const newEmbeddedEventCreateTimer = useRef<number | null>(null);
  const allowEmbeddedEndDate = embeddedConfig.event_allow_end_date === true;
  const embeddedEventColumns = {
    showDate: embeddedConfig.event_show_date !== false,
    showTag: embeddedConfig.event_show_tag !== false,
    showTitle: embeddedConfig.event_show_title !== false,
    showDescription: embeddedConfig.event_show_description !== false,
    showParticipantCount: embeddedConfig.event_show_participant_count === true,
    showCancelled: embeddedConfig.event_show_cancelled === true,
  };
  if (
    !embeddedEventColumns.showDate &&
    !embeddedEventColumns.showTag &&
    !embeddedEventColumns.showTitle &&
    !embeddedEventColumns.showDescription &&
    !embeddedEventColumns.showParticipantCount
  ) {
    embeddedEventColumns.showTitle = true;
  }

  function updateEmbeddedConfig(updater: (current: Record<string, any>) => Record<string, unknown>, persist = false) {
    updateEmbeddedBlock(
      (current) => ({
        ...current,
        configuration_snapshot_json: updater(asObject(current.configuration_snapshot_json)),
      }),
      persist
    );
  }

  useEffect(() => {
    setNewEmbeddedEventDraft((current) => {
      const hasManualContent =
        Boolean(current.title.trim()) ||
        Boolean(current.description.trim()) ||
        Boolean(current.event_end_date.trim()) ||
        Number(current.participant_count || "0") > 0;
      if (hasManualContent) {
        return current;
      }
      return createInlineProtocolEventDraft(protocol.protocol_date, forcedEmbeddedTag, embeddedEventColumns.showTitle);
    });
  }, [embeddedEventColumns.showTitle, forcedEmbeddedTag, protocol.protocol_date]);

  useEffect(() => {
    return () => {
      Object.values(embeddedEventAutosaveTimers.current).forEach((timerId) => window.clearTimeout(timerId));
      if (newEmbeddedEventCreateTimer.current) {
        window.clearTimeout(newEmbeddedEventCreateTimer.current);
      }
    };
  }, []);

  function participantNameById(participantId: string | null | undefined) {
    return availableParticipants.find((participant) => participant.id === participantId)?.display_name ?? "—";
  }

  function eventLabelById(eventId: string | null | undefined) {
    const eventRow = sortedEvents.find((entry) => entry.id === eventId);
    return eventRow ? `${formatDateRange(eventRow.event_date, eventRow.event_end_date)} · ${eventRow.title}` : "—";
  }

  function attendanceStatusLabel(status: string | null | undefined) {
    return ATTENDANCE_OPTIONS.find((option) => option.value === status)?.label ?? "Unbekannt";
  }

  function embeddedEventPayload(eventRow: EventSummary, draft: Partial<EventSummary>) {
    const nextEventRow = {
      ...eventRow,
      ...draft,
    };
    return {
      event_date: nextEventRow.event_date,
      event_end_date: allowEmbeddedEndDate ? nextEventRow.event_end_date || null : null,
      tag: forcedEmbeddedTag || nextEventRow.tag || null,
      title: nextEventRow.title,
      description: nextEventRow.description || null,
      participant_count: Math.max(0, Number(nextEventRow.participant_count ?? 0)),
    };
  }

  function queueEmbeddedEventSave(eventRow: EventSummary, patch: Partial<EventSummary>) {
    const nextDraft = {
      ...(embeddedEventDrafts[eventRow.id] ?? {}),
      ...patch,
    };
    setEmbeddedEventDrafts((current) => ({
      ...current,
      [eventRow.id]: nextDraft,
    }));
    if (embeddedEventAutosaveTimers.current[eventRow.id]) {
      window.clearTimeout(embeddedEventAutosaveTimers.current[eventRow.id]);
    }
    embeddedEventAutosaveTimers.current[eventRow.id] = window.setTimeout(async () => {
      const saved = await updateEvent(eventRow.id, embeddedEventPayload(eventRow, nextDraft));
      if (saved) {
        setEmbeddedEventDrafts((current) => {
          if (!current[eventRow.id]) {
            return current;
          }
          const next = { ...current };
          delete next[eventRow.id];
          return next;
        });
      }
    }, 500);
  }

  function resetNewEmbeddedEventRow() {
    if (newEmbeddedEventCreateTimer.current) {
      window.clearTimeout(newEmbeddedEventCreateTimer.current);
      newEmbeddedEventCreateTimer.current = null;
    }
    setCreatingEmbeddedEvent(false);
    setShowNewEmbeddedEventRow(false);
    setNewEmbeddedEventDraft(createInlineProtocolEventDraft(protocol.protocol_date, forcedEmbeddedTag, embeddedEventColumns.showTitle));
  }

  function scheduleEmbeddedEventCreate(nextDraft: ProtocolEventDraft) {
    if (newEmbeddedEventCreateTimer.current) {
      window.clearTimeout(newEmbeddedEventCreateTimer.current);
      newEmbeddedEventCreateTimer.current = null;
    }
    if (!canCreateProtocolEventDraft(nextDraft)) {
      return;
    }
    newEmbeddedEventCreateTimer.current = window.setTimeout(async () => {
      setCreatingEmbeddedEvent(true);
      const saved = await createEvent(forcedEmbeddedTag, nextDraft);
      setCreatingEmbeddedEvent(false);
      if (saved) {
        resetNewEmbeddedEventRow();
      }
    }, 500);
  }

  function patchNewEmbeddedEventDraft(patch: Partial<ProtocolEventDraft>) {
    setNewEmbeddedEventDraft((current) => {
      const nextDraft = { ...current, ...patch };
      scheduleEmbeddedEventCreate(nextDraft);
      return nextDraft;
    });
  }

  function embeddedParticipantSummary(row: Record<string, any>) {
    const selectedIds = Array.isArray(row.participant_ids) ? row.participant_ids.map(String) : [];
    if (!selectedIds.length) {
      return "Teilnehmer waehlen";
    }
    const selectedParticipants = availableParticipants.filter((participant) => selectedIds.includes(participant.id));
    if (!selectedParticipants.length) {
      return `${selectedIds.length} ausgewaehlt`;
    }
    if (selectedParticipants.length === 1) {
      return selectedParticipants[0].display_name;
    }
    if (selectedParticipants.length === 2) {
      return `${selectedParticipants[0].display_name}, ${selectedParticipants[1].display_name}`;
    }
    return `${selectedParticipants[0].display_name} + ${selectedParticipants.length - 1}`;
  }

  if (elementTypeId === 1 || elementTypeId === 5) {
    if (!editable) {
      return (
        <div className={embeddedBlockClassName}>
          <div className="matrix-static-value">{String(embeddedBlock.text_content ?? "").trim() || "Kein Inhalt"}</div>
        </div>
      );
    }
    return (
      <div className={embeddedBlockClassName}>
        <textarea
          rows={4}
          className="todo-input"
          value={String(embeddedBlock.text_content ?? "")}
          onChange={(event) => updateEmbeddedBlock((current) => ({ ...current, text_content: event.target.value }))}
          onBlur={() => updateEmbeddedBlock((current) => current, true)}
          placeholder="Blockinhalt"
        />
      </div>
    );
  }

  if (elementTypeId === 2) {
    const todoItems = (Array.isArray(embeddedConfig.todo_items) ? embeddedConfig.todo_items : []) as Array<Record<string, any>>;
    if (!editable) {
      return (
        <div className={embeddedBlockClassName}>
          {todoItems.length ? (
            <div className="matrix-static-list">
              {todoItems.map((item, index) => (
                <div className="matrix-static-list-item" key={String(item.id ?? index)}>
                  {Boolean(item.done) ? "✓ " : ""}
                  {String(item.task ?? "").trim() || "Leeres Todo"}
                </div>
              ))}
            </div>
          ) : (
            <div className="matrix-static-value">Keine Todos</div>
          )}
        </div>
      );
    }
    return (
      <div className={embeddedBlockClassName}>
        <div className="todo-list">
          {todoItems.map((item, index) => {
            const isDone = Boolean(item.done);
            return (
              <article className={`todo-card todo-card-compact${isDone ? " todo-card-done" : ""}`} key={String(item.id ?? index)}>
                <button
                  type="button"
                  className={`todo-toggle${isDone ? " todo-toggle-done" : ""}`}
                  onClick={() =>
                    updateEmbeddedConfig((current) => ({
                      ...current,
                      todo_items: todoItems.map((entry, entryIndex) =>
                        entryIndex === index ? { ...entry, done: !isDone } : entry
                      ),
                    }), true)
                  }
                >
                  {isDone ? "✓" : "○"}
                </button>
                <div className="todo-main todo-main-compact">
                  <textarea
                    rows={1}
                    className="todo-input"
                    value={String(item.task ?? "")}
                    onChange={(event) =>
                      updateEmbeddedConfig((current) => ({
                        ...current,
                        todo_items: todoItems.map((entry, entryIndex) =>
                          entryIndex === index ? { ...entry, task: event.target.value } : entry
                        ),
                      }))
                    }
                    onBlur={() => updateEmbeddedBlock((current) => current, true)}
                  />
                </div>
                <button
                  type="button"
                  className="button-inline button-danger todo-delete"
                  onClick={async () => {
                    const ok = await confirm({
                      message: `Todo "${String(item.task ?? "").trim() || "Unbenannt"}" löschen?`,
                      tone: "danger",
                      confirmLabel: "Löschen",
                    });
                    if (!ok) return;
                    updateEmbeddedConfig((current) => ({
                      ...current,
                      todo_items: todoItems.filter((_, entryIndex) => entryIndex !== index),
                    }), true);
                  }}
                >
                  Löschen
                </button>
              </article>
            );
          })}
        </div>
        <div className="todo-create todo-create-inline">
          <input value="" readOnly placeholder="Neues Todo mit dem Button hinzufügen" />
          <button
            type="button"
            onClick={() =>
              updateEmbeddedConfig((current) => ({
                ...current,
                todo_items: [
                  ...todoItems,
                  { id: nextEmbeddedItemId(todoItems, "todo"), task: "", done: false },
                ],
              }), true)
            }
          >
            + Todo
          </button>
        </div>
      </div>
    );
  }

  if (elementTypeId === 3) {
    const images = (Array.isArray(embeddedConfig.images) ? embeddedConfig.images : []) as Array<Record<string, any>>;
    if (!editable) {
      return (
        <div className={embeddedBlockClassName}>
          {images.length ? (
            <div className="image-grid">
              {images.map((image, index) => (
                <div className="card image-card" key={String(image.id ?? index)}>
                  {String(image.url ?? "").trim() ? <LightboxImage alt={String(image.caption ?? "Matrixbild")} src={String(image.url)} /> : null}
                  {String(image.caption ?? "").trim() ? <div className="muted">{String(image.caption)}</div> : null}
                </div>
              ))}
            </div>
          ) : (
            <div className="matrix-static-value">Kein Bild</div>
          )}
        </div>
      );
    }
    return (
      <div className={embeddedBlockClassName}>
        <div className="image-grid">
          {images.map((image, index) => (
            <div className="card image-card" key={String(image.id ?? index)}>
              <label className="field-stack">
                <span className="field-label">Bild-URL</span>
                <input
                  value={String(image.url ?? "")}
                  onChange={(event) =>
                    updateEmbeddedConfig((current) => ({
                      ...current,
                      images: images.map((entry, entryIndex) =>
                        entryIndex === index ? { ...entry, url: event.target.value } : entry
                      ),
                    }))
                  }
                  onBlur={() => updateEmbeddedBlock((current) => current, true)}
                  placeholder="https://..."
                />
              </label>
              <label className="field-stack">
                <span className="field-label">Bildunterschrift</span>
                <input
                  value={String(image.caption ?? "")}
                  onChange={(event) =>
                    updateEmbeddedConfig((current) => ({
                      ...current,
                      images: images.map((entry, entryIndex) =>
                        entryIndex === index ? { ...entry, caption: event.target.value } : entry
                      ),
                    }))
                  }
                  onBlur={() => updateEmbeddedBlock((current) => current, true)}
                  placeholder="Optional"
                />
              </label>
              {String(image.url ?? "").trim() ? <LightboxImage alt={String(image.caption ?? "Matrixbild")} src={String(image.url)} /> : null}
              <button
                type="button"
                className="button-inline button-danger"
                onClick={() =>
                  updateEmbeddedConfig((current) => ({
                    ...current,
                    images: images.filter((_, entryIndex) => entryIndex !== index),
                  }), true)
                }
              >
                Bild entfernen
              </button>
            </div>
          ))}
        </div>
        <div className="table-toolbar-actions">
          <button
            type="button"
            className="button-inline"
            onClick={() =>
              updateEmbeddedConfig((current) => ({
                ...current,
                images: [...images, { id: nextEmbeddedItemId(images, "image"), url: "", caption: "" }],
              }), true)
            }
          >
            Bild hinzufügen
          </button>
        </div>
      </div>
    );
  }

  if (elementTypeId === 6) {
    const rows = (Array.isArray(embeddedConfig.rows) ? embeddedConfig.rows : []) as Array<Record<string, any>>;
    if (!editable) {
      return (
        <div className={embeddedBlockClassName}>
          {rows.length ? (
            <div className="form-block-list">
              {rows.map((row, index) => {
                const rowType = String(row.value_type ?? row.row_type ?? "text");
                const referencedEvent = rowType === "event" ? sortedEvents.find((entry) => entry.id === row.event_id) : undefined;
                const rowValue: ReactNode =
                  rowType === "participant"
                    ? participantNameById(row.participant_id)
                    : rowType === "participants"
                    ? embeddedParticipantSummary(row)
                    : rowType === "event"
                    ? referencedEvent
                      ? (
                        <span
                          className={referencedEvent.is_cancelled ? "event-ref-cancelled" : undefined}
                          onContextMenu={(nativeEvent) => onEventContextMenu(nativeEvent, referencedEvent)}
                        >
                          {eventLabelById(row.event_id)}
                        </span>
                      )
                      : "—"
                    : String(row.text_value ?? "").trim() || "—";
                return (
                  <div className="form-block-row" key={String(row.id ?? index)}>
                    <div className="field-label-inline">{String(row.label ?? `Zeile ${index + 1}`)}</div>
                    <div className="matrix-static-value">{rowValue}</div>
                    <div />
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="matrix-static-value">Leere Tabelle</div>
          )}
        </div>
      );
    }
    return (
      <div className={embeddedBlockClassName}>
        <div className="form-block-list">
          {rows.map((row, index) => (
            <div className="form-block-row" key={String(row.id ?? index)}>
              <input
                value={String(row.label ?? "")}
                onChange={(event) =>
                  updateEmbeddedConfig((current) => ({
                    ...current,
                    rows: rows.map((entry, entryIndex) =>
                      entryIndex === index ? { ...entry, label: event.target.value } : entry
                    ),
                  }))
                }
                onBlur={() => updateEmbeddedBlock((current) => current, true)}
                placeholder="Zeilenbezeichnung"
              />
              <div className="grid">
                <select
                  value={String(row.value_type ?? "text")}
                  onChange={(event) =>
                    updateEmbeddedConfig((current) => ({
                      ...current,
                      rows: rows.map((entry, entryIndex) =>
                        entryIndex === index
                          ? {
                              ...entry,
                              value_type: event.target.value,
                              text_value: event.target.value === "text" ? String(entry.text_value ?? "") : "",
                              participant_id: null,
                              participant_ids: [],
                              event_id: null,
                            }
                          : entry
                      ),
                    }), true)
                  }
                >
                  {EMBEDDED_FORM_VALUE_OPTIONS.map((option) => (
                    <option key={`embedded-form-type-${option.value}`} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                {String(row.value_type ?? "text") === "participant" ? (
                  <SearchableSelect
                    options={availableParticipants}
                    getId={(participant) => participant.id}
                    getLabel={(participant) => participant.display_name}
                    value={row.participant_id ?? null}
                    onChange={(participant) =>
                      updateEmbeddedConfig((current) => ({
                        ...current,
                        rows: rows.map((entry, entryIndex) =>
                          entryIndex === index ? { ...entry, participant_id: participant ? participant.id : null } : entry
                        ),
                      }), true)
                    }
                    nullLabel="Teilnehmer waehlen"
                  />
                ) : String(row.value_type ?? "text") === "participants" ? (
                  <button type="button" className="button-ghost form-participant-picker-button" onClick={() => openMultiParticipantPicker(row)}>
                    {embeddedParticipantSummary(row)}
                  </button>
                ) : String(row.value_type ?? "text") === "event" ? (
                  <SearchableSelect
                    options={sortedEvents}
                    getId={(eventRow) => eventRow.id}
                    getLabel={(eventRow) => `${formatDateRange(eventRow.event_date, eventRow.event_end_date)} · ${eventRow.title}`}
                    value={row.event_id ?? null}
                    onChange={(eventRow) =>
                      updateEmbeddedConfig((current) => ({
                        ...current,
                        rows: rows.map((entry, entryIndex) =>
                          entryIndex === index ? { ...entry, event_id: eventRow ? eventRow.id : null } : entry
                        ),
                      }), true)
                    }
                    nullLabel="Termin waehlen"
                  />
                ) : (
                  <textarea
                    rows={1}
                    className="todo-input"
                    value={String(row.text_value ?? "")}
                    onChange={(event) =>
                      updateEmbeddedConfig((current) => ({
                        ...current,
                        rows: rows.map((entry, entryIndex) =>
                          entryIndex === index ? { ...entry, text_value: event.target.value } : entry
                        ),
                      }))
                    }
                    onBlur={() => updateEmbeddedBlock((current) => current, true)}
                    placeholder="Inhalt"
                  />
                )}
              </div>
              <button
                type="button"
                className="button-inline button-danger todo-delete"
                onClick={async () => {
                  const ok = await confirm({
                    message: `Zeile "${String(row.label ?? "").trim() || "Unbenannt"}" löschen?`,
                    tone: "danger",
                    confirmLabel: "Löschen",
                  });
                  if (!ok) return;
                  updateEmbeddedConfig((current) => ({
                    ...current,
                    rows: rows.filter((_, entryIndex) => entryIndex !== index),
                  }), true);
                }}
              >
                Löschen
              </button>
            </div>
          ))}
        </div>
        <div className="table-toolbar-actions">
          <button
            type="button"
            className="button-inline"
            onClick={() =>
              updateEmbeddedConfig((current) => ({
                ...current,
                rows: [...rows, createEmbeddedFormRow(nextEmbeddedItemId(rows, "form-row"))],
              }), true)
            }
          >
            Zeile hinzufügen
          </button>
        </div>
      </div>
    );
  }

  if (elementTypeId === 7) {
    const tagFilters = String(embeddedConfig.event_tag_filter ?? "").split(",").map((t) => t.trim().toLowerCase()).filter(Boolean);
    const columnTagFilters = embeddedConfig.event_use_column_tag_filter === true
      ? String(matrixColumn?.event_tag_filter || matrixColumn?.title || "").split(",").map((t) => t.trim().toLowerCase()).filter(Boolean) : [];
    const matchingEvents = sortedEvents.filter((eventRow) => {
      const effectiveEndDate = eventRow.event_end_date || eventRow.event_date;
      const eventTag = (eventRow.tag ?? "").toLowerCase();
      const matchesTag =
        (!tagFilters.length || tagFilters.some((t) => eventTag.includes(t))) &&
        (!columnTagFilters.length || columnTagFilters.some((t) => eventTag.includes(t)));
      const matchesDate = !protocol.protocol_date ? true : embeddedConfig.event_only_before_protocol_date === true ? effectiveEndDate < protocol.protocol_date : embeddedConfig.event_only_from_protocol_date === false ? true : effectiveEndDate >= protocol.protocol_date;
      const matchesCycle = embeddedConfig.event_only_current_cycle !== true || currentCycleYear === null
        ? true
        : (eventRow.cycle_assignments ?? []).some(
            (a) => a.cycle_config_id === cycleConfigId && a.cycle_year === currentCycleYear
          );
      return matchesTag && matchesDate && matchesCycle;
    });
    const embeddedEventDraftValue = (eventRow: EventSummary) => ({
      ...eventRow,
      ...(embeddedEventDrafts[eventRow.id] ?? {}),
    });

    if (isPlanningMode) {
      return (
        <div className={embeddedBlockClassName}>
          {matchingEvents.length === 0 ? (
            <div className="editor-block-empty-placeholder-auto">
              <span>Keine Elemente angezeigt.</span>
              <PlanningIconTrigger
                title="Terminübersicht öffnen"
                icon="🗓"
                onClick={() => setShowEmbeddedEventOverview(true)}
              />
            </div>
          ) : (
            <>
              <div className="editor-planning-toolbar">
                <PlanningIconTrigger
                  title="Terminübersicht öffnen"
                  icon="🗓"
                  onClick={() => setShowEmbeddedEventOverview(true)}
                />
              </div>
              <div className="event-table-wrap">
                <table className="data-table event-table event-table-compact">
                  <thead>
                    <tr>
                      {embeddedEventColumns.showDate ? <th>Dat.</th> : null}
                      {embeddedEventColumns.showTag ? <th>Tag</th> : null}
                      {embeddedEventColumns.showTitle ? <th>Titel</th> : null}
                      {embeddedEventColumns.showDescription ? <th>Beschreibung</th> : null}
                      {embeddedEventColumns.showParticipantCount ? <th className="event-column-count">TN</th> : null}
                      {embeddedEventColumns.showCancelled ? <th>Abgesagt</th> : null}
                    </tr>
                  </thead>
                  <tbody>
                    {matchingEvents.map((eventRow) => {
                      const isPast = !!protocol.protocol_date &&
                        (eventRow.event_end_date || eventRow.event_date) < protocol.protocol_date;
                      const showCancelledStyle = embeddedEventColumns.showCancelled && eventRow.is_cancelled;
                      return (
                        <tr
                          key={eventRow.id}
                          className={`${isPast && embeddedConfig.event_gray_past !== false ? "event-row-past" : ""}${showCancelledStyle ? " event-row-cancelled" : ""}`}
                        >
                          {embeddedEventColumns.showDate ? <td>{formatDateRange(eventRow.event_date, eventRow.event_end_date)}</td> : null}
                          {embeddedEventColumns.showTag ? <td>{eventRow.tag || "—"}</td> : null}
                          {embeddedEventColumns.showTitle ? <td>{eventRow.title}</td> : null}
                          {embeddedEventColumns.showDescription ? <td>{eventRow.description || "—"}</td> : null}
                          {embeddedEventColumns.showParticipantCount ? <td className="event-column-count">{eventRow.participant_count ?? 0}</td> : null}
                          {embeddedEventColumns.showCancelled ? (
                            <td>{eventRow.is_cancelled ? <Badge variant="danger">Abgesagt</Badge> : <span className="muted">–</span>}</td>
                          ) : null}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
          <EventOverviewModal
            open={showEmbeddedEventOverview}
            onClose={() => setShowEmbeddedEventOverview(false)}
            protocolId={protocol.id}
            forcedTag={forcedEmbeddedTag}
            allowEndDate={allowEmbeddedEndDate}
            protocolDate={protocol.protocol_date ?? null}
            visibleEvents={matchingEvents}
            availableParticipants={availableParticipants}
            knownEventTags={knownEventTags}
            tagConfig={tagConfig}
            onTagColorChange={onTagColorChange}
            onTagRename={onTagRename}
            onCreateEvent={(draft) => createEvent(forcedEmbeddedTag, draft)}
            onUpdateEvent={(eventId, patch) => updateEvent(eventId, patch)}
            onDeleteEvent={(eventId) => deleteEvent(eventId)}
          />
        </div>
      );
    }

    return (
      <div className={embeddedBlockClassName}>
        {matchingEvents.length || editable || showNewEmbeddedEventRow ? (
          <div className="event-table-wrap">
            <table className="data-table event-table event-table-compact">
              <thead>
                <tr>
                  {embeddedEventColumns.showDate ? <th>Dat.</th> : null}
                  {embeddedEventColumns.showTag ? <th>Tag</th> : null}
                  {embeddedEventColumns.showTitle ? <th>Titel</th> : null}
                  {embeddedEventColumns.showDescription ? <th>Beschreibung</th> : null}
                  {embeddedEventColumns.showParticipantCount ? <th className="event-column-count">TN</th> : null}
                  {embeddedEventColumns.showCancelled ? <th>Abgesagt</th> : null}
                  {editable ? (
                    <th className="event-column-actions" aria-label="Aktionen">
                      <button
                        type="button"
                        className="button-ghost button-icon"
                        title="Terminzeile hinzufügen"
                        aria-label="Terminzeile hinzufügen"
                        disabled={showNewEmbeddedEventRow || creatingEmbeddedEvent}
                        onClick={() => {
                          setShowNewEmbeddedEventRow(true);
                          setNewEmbeddedEventDraft((current) => {
                            const hasManualContent =
                              Boolean(current.title.trim()) ||
                              Boolean(current.description.trim()) ||
                              Boolean(current.event_end_date.trim()) ||
                              Number(current.participant_count || "0") > 0;
                            return hasManualContent
                              ? current
                              : createInlineProtocolEventDraft(protocol.protocol_date, forcedEmbeddedTag, embeddedEventColumns.showTitle);
                          });
                        }}
                      >
                        +
                      </button>
                    </th>
                  ) : null}
                </tr>
              </thead>
              <tbody>
                {showNewEmbeddedEventRow ? (
                  <tr className="event-row-new">
                    {embeddedEventColumns.showDate ? (
                      <td>
                        <div className={`event-date-fields${allowEmbeddedEndDate ? " event-date-fields-range" : ""}`}>
                          <DateInput
                            className="event-field-date"
                            value={newEmbeddedEventDraft.event_date}
                            disabled={creatingEmbeddedEvent}
                            onChange={(value) => patchNewEmbeddedEventDraft({ event_date: value })}
                          />
                          {allowEmbeddedEndDate ? (
                            <DateInput
                              className="event-field-date"
                              value={newEmbeddedEventDraft.event_end_date}
                              disabled={creatingEmbeddedEvent}
                              onChange={(value) => patchNewEmbeddedEventDraft({ event_end_date: value })}
                            />
                          ) : null}
                        </div>
                      </td>
                    ) : null}
                    {embeddedEventColumns.showTag ? (
                      <td>
                        <input
                          className="event-field-tag"
                          value={forcedEmbeddedTag || newEmbeddedEventDraft.tag}
                          readOnly={Boolean(forcedEmbeddedTag)}
                          disabled={creatingEmbeddedEvent}
                          onChange={(event) => patchNewEmbeddedEventDraft({ tag: event.target.value })}
                          placeholder="Tag"
                        />
                      </td>
                    ) : null}
                    {embeddedEventColumns.showTitle ? (
                      <td>
                        <input
                          className="event-field-title"
                          value={newEmbeddedEventDraft.title}
                          disabled={creatingEmbeddedEvent}
                          onChange={(event) => patchNewEmbeddedEventDraft({ title: event.target.value })}
                          placeholder="Titel"
                        />
                      </td>
                    ) : null}
                    {embeddedEventColumns.showDescription ? (
                      <td>
                        <input
                          className="event-field-description"
                          value={newEmbeddedEventDraft.description}
                          disabled={creatingEmbeddedEvent}
                          onChange={(event) => patchNewEmbeddedEventDraft({ description: event.target.value })}
                          placeholder="Beschreibung"
                        />
                      </td>
                    ) : null}
                    {embeddedEventColumns.showParticipantCount ? (
                      <td className="event-column-count">
                        <input
                          type="number"
                          className="event-field-count"
                          min="0"
                          value={newEmbeddedEventDraft.participant_count}
                          disabled={creatingEmbeddedEvent}
                          onChange={(event) => patchNewEmbeddedEventDraft({ participant_count: event.target.value })}
                          onFocus={(e) => e.target.select()}
                          placeholder="TN"
                        />
                      </td>
                    ) : null}
                    {embeddedEventColumns.showCancelled ? <td /> : null}
                    {editable ? (
                      <td>
                        <div className="event-row-actions">
                          <button
                            type="button"
                            className="button-ghost button-icon button-icon-danger"
                            title="Neue Terminzeile verwerfen"
                            aria-label="Neue Terminzeile verwerfen"
                            disabled={creatingEmbeddedEvent}
                            onClick={resetNewEmbeddedEventRow}
                          >
                            x
                          </button>
                        </div>
                      </td>
                    ) : null}
                  </tr>
                ) : null}
                {matchingEvents.map((eventRow) => {
                  const effectiveEndDate = eventRow.event_end_date || eventRow.event_date;
                  const isPast = !!protocol.protocol_date && effectiveEndDate < protocol.protocol_date;
                  const editableEventRow = embeddedEventDraftValue(eventRow);
                  const showCancelledStyle = embeddedEventColumns.showCancelled && eventRow.is_cancelled;
                  return (
                    <tr
                      key={eventRow.id}
                      className={`${isPast && embeddedConfig.event_gray_past !== false ? "event-row-past" : ""}${showCancelledStyle ? " event-row-cancelled" : ""}`}
                      onContextMenu={(nativeEvent) => onEventContextMenu(nativeEvent, eventRow)}
                    >
                      {embeddedEventColumns.showDate ? (
                        <td>
                          {editable ? (
                            <div className={`event-date-fields${allowEmbeddedEndDate ? " event-date-fields-range" : ""}`}>
                              <DateInput
                                className="event-field-date"
                                value={editableEventRow.event_date}
                                onChange={(value) => queueEmbeddedEventSave(eventRow, { event_date: value })}
                              />
                              {allowEmbeddedEndDate ? (
                                <DateInput
                                  className="event-field-date"
                                  value={editableEventRow.event_end_date ?? ""}
                                  onChange={(value) => queueEmbeddedEventSave(eventRow, { event_end_date: value || null })}
                                />
                              ) : null}
                            </div>
                          ) : (
                            formatDateRange(eventRow.event_date, eventRow.event_end_date)
                          )}
                        </td>
                      ) : null}
                      {embeddedEventColumns.showTag ? (
                        <td>
                          {editable ? (
                            <input
                              className="event-field-tag"
                              value={editableEventRow.tag ?? forcedEmbeddedTag}
                              readOnly={Boolean(forcedEmbeddedTag)}
                              onChange={(event) => queueEmbeddedEventSave(eventRow, { tag: event.target.value || null })}
                            />
                          ) : (
                            eventRow.tag || "—"
                          )}
                        </td>
                      ) : null}
                      {embeddedEventColumns.showTitle ? (
                        <td>
                          {editable ? (
                            <input
                              className="event-field-title"
                              value={editableEventRow.title}
                              onChange={(event) => queueEmbeddedEventSave(eventRow, { title: event.target.value })}
                            />
                          ) : (
                            eventRow.title
                          )}
                        </td>
                      ) : null}
                      {embeddedEventColumns.showDescription ? (
                        <td>
                          {editable ? (
                            <input
                              className="event-field-description"
                              value={editableEventRow.description ?? ""}
                              onChange={(event) => queueEmbeddedEventSave(eventRow, { description: event.target.value || null })}
                            />
                          ) : (
                            eventRow.description || "—"
                          )}
                        </td>
                      ) : null}
                      {embeddedEventColumns.showParticipantCount ? (
                        <td className="event-column-count">
                          {editable ? (
                            <input
                              type="number"
                              className="event-field-count"
                              min="0"
                              value={editableEventRow.participant_count ?? 0}
                              onChange={(event) => queueEmbeddedEventSave(eventRow, { participant_count: Math.max(0, Number(event.target.value || "0")) })}
                              onFocus={(e) => e.target.select()}
                            />
                          ) : (
                            eventRow.participant_count ?? 0
                          )}
                        </td>
                      ) : null}
                      {embeddedEventColumns.showCancelled ? (
                        <td>
                          {eventRow.is_cancelled ? <Badge variant="danger">Abgesagt</Badge> : <span className="muted">–</span>}
                        </td>
                      ) : null}
                      {editable ? (
                        <td>
                          <div className="event-row-actions">
                            <button
                              type="button"
                              className="button-ghost button-icon button-icon-danger"
                              title="Termin löschen"
                              aria-label="Termin löschen"
                              onClick={async () => {
                                const ok = await confirm({
                                  message: `Termin "${eventRow.title}" endgültig löschen? Das entfernt ihn aus allen Protokollen.`,
                                  tone: "danger",
                                  confirmLabel: "Löschen"
                                });
                                if (!ok) return;
                                await deleteEvent(eventRow.id);
                              }}
                            >
                              x
                            </button>
                          </div>
                        </td>
                      ) : null}
                    </tr>
                  );
                })}
                {!matchingEvents.length && !showNewEmbeddedEventRow ? (
                  <tr>
                    <td
                      colSpan={
                        Number(embeddedEventColumns.showDate) +
                        Number(embeddedEventColumns.showTag) +
                        Number(embeddedEventColumns.showTitle) +
                        Number(embeddedEventColumns.showDescription) +
                        Number(embeddedEventColumns.showParticipantCount) +
                        Number(embeddedEventColumns.showCancelled) +
                        Number(editable)
                      }
                    >
                      <span className="muted">Keine passenden Termine.</span>
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        ) : (
          <span className="muted">Keine passenden Termine</span>
        )}
      </div>
    );
  }

  if (elementTypeId === 8) {
    const bulletItems = (Array.isArray(embeddedConfig.bullet_items) ? embeddedConfig.bullet_items : []) as string[];
    if (!editable) {
      return (
        <div className={embeddedBlockClassName}>
          {bulletItems.length ? (
            <div className="matrix-static-list">
              {bulletItems.map((item, index) => (
                <div className="matrix-static-list-item" key={`embedded-bullet-${index}`}>{item || "Leerer Punkt"}</div>
              ))}
            </div>
          ) : (
            <div className="matrix-static-value">Keine Punkte</div>
          )}
        </div>
      );
    }
    return (
      <div className={embeddedBlockClassName}>
        <div className="todo-list">
          {bulletItems.map((item, index) => (
            <article className="todo-card todo-card-compact" key={`embedded-bullet-${index}`}>
              <div className="todo-toggle todo-toggle-done">•</div>
              <div className="todo-main todo-main-compact">
                <textarea
                  rows={1}
                  className="todo-input"
                  value={item}
                  onChange={(event) =>
                    updateEmbeddedConfig((current) => ({
                      ...current,
                      bullet_items: bulletItems.map((entry, entryIndex) => (entryIndex === index ? event.target.value : entry)),
                    }))
                  }
                  onBlur={() => updateEmbeddedBlock((current) => current, true)}
                  onKeyDown={(event) => {
                    if (event.key !== "Enter" || event.shiftKey) return;
                    event.preventDefault();
                    if (item === "") {
                      updateEmbeddedConfig((current) => ({
                        ...current,
                        bullet_items: bulletItems.filter((_, i) => i !== index),
                      }), true);
                    } else {
                      const nextItems = [...bulletItems.slice(0, index + 1), "", ...bulletItems.slice(index + 1)];
                      updateEmbeddedConfig((current) => ({ ...current, bullet_items: nextItems }), false);
                      const el = event.currentTarget;
                      window.setTimeout(() => {
                        const container = el.closest(".todo-list");
                        const textareas = container?.querySelectorAll<HTMLTextAreaElement>("textarea.todo-input");
                        textareas?.[index + 1]?.focus();
                      }, 50);
                    }
                  }}
                />
              </div>
              <button
                type="button"
                className="button-inline button-danger todo-delete"
                onClick={async () => {
                  const ok = await confirm({
                    message: `Bulletpoint "${String(item ?? "").trim() || "Unbenannt"}" löschen?`,
                    tone: "danger",
                    confirmLabel: "Löschen",
                  });
                  if (!ok) return;
                  updateEmbeddedConfig((current) => ({
                    ...current,
                    bullet_items: bulletItems.filter((_, entryIndex) => entryIndex !== index),
                  }), true);
                }}
              >
                Löschen
              </button>
            </article>
          ))}
        </div>
        <div className="todo-create todo-create-inline">
          <input value="" readOnly placeholder="Neuen Punkt hinzufügen" />
          <button
            type="button"
            onClick={() =>
              updateEmbeddedConfig((current) => ({
                ...current,
                bullet_items: [...bulletItems, ""],
              }), true)
            }
          >
            + Punkt
          </button>
        </div>
      </div>
    );
  }

  if (elementTypeId === 9) {
    const attendanceEntries = (Array.isArray(embeddedConfig.attendance_entries) ? embeddedConfig.attendance_entries : []) as Array<Record<string, any>>;
    if (!editable) {
      return (
        <div className={embeddedBlockClassName}>
          <div className="matrix-static-list">
            {eligibleAttendanceParticipants.map((participant) => {
              const currentEntry = attendanceEntries.find((entry) => String(entry.participant_id) === participant.id);
              return (
                <div className="matrix-static-list-item" key={`embedded-attendance-${participant.id}`}>
                  <strong>{participant.display_name}</strong>: {currentEntry?.status ? attendanceStatusLabel(currentEntry.status) : "—"}
                </div>
              );
            })}
          </div>
        </div>
      );
    }
    return (
      <div className={embeddedBlockClassName}>
        <div className="attendance-list">
          {eligibleAttendanceParticipants.map((participant) => {
            const currentEntry = attendanceEntries.find((entry) => String(entry.participant_id) === participant.id);
            const selectedStatus = currentEntry?.status ?? null;
            return (
              <div className="attendance-row" key={`embedded-attendance-${participant.id}`}>
                <span className="attendance-name">{participant.display_name}</span>
                <div className="segment-control attendance-segment-control">
                  {ATTENDANCE_OPTIONS.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      className={`segment-button attendance-segment-button${selectedStatus === option.value ? " segment-button-active" : ""}`}
                      onClick={() =>
                        updateEmbeddedConfig((current) => ({
                          ...current,
                          attendance_entries: [
                            ...attendanceEntries.filter((entry) => String(entry.participant_id) !== participant.id),
                            {
                              participant_id: participant.id,
                              participant_name: participant.display_name,
                              status: option.value,
                            },
                          ],
                        }), true)
                      }
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  if (elementTypeId === 10) {
    if (!editable) {
      return (
        <div className={embeddedBlockClassName}>
          <div className="matrix-static-value">
            {String(embeddedConfig.session_label ?? "").trim() || "Naechste Sitzung"}
            {String(embeddedConfig.selected_date ?? "").trim() ? `: ${formatShortDate(String(embeddedConfig.selected_date))}` : ""}
          </div>
        </div>
      );
    }
    return (
      <div className={embeddedBlockClassName}>
        <div className="two-col">
          <label className="field-stack">
            <span className="field-label">Bezeichnung</span>
            <input
              value={String(embeddedConfig.session_label ?? "")}
              onChange={(event) =>
                updateEmbeddedConfig((current) => ({
                  ...current,
                  session_label: event.target.value,
                }))
              }
              onBlur={() => updateEmbeddedBlock((current) => current, true)}
              placeholder="Naechste Sitzung"
            />
          </label>
          <label className="field-stack">
            <span className="field-label">Datum</span>
            <DateInput
              value={String(embeddedConfig.selected_date ?? "")}
              onChange={(value) =>
                updateEmbeddedConfig((current) => ({
                  ...current,
                  selected_date: value || null,
                }), true)
              }
            />
          </label>
        </div>
      </div>
    );
  }

  return <span className="muted">Dieser Zell-Blocktyp ist noch nicht verfügbar.</span>;
}
