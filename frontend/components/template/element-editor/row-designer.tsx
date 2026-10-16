"use client";

// Ein Designer für Tabelle (Typ 6) und Matrix (Typ 11): gleiche Zeilenliste mit Drag & Drop,
// gleicher Zeilen-Inspektor, gleiche Fusszeile (Abbrechen verwirft, Übernehmen übernimmt).
// Die Matrix hat zusätzlich Spalten (manuell, ebenfalls sortierbar) oder automatische Spalten
// aus Teilnehmern, Terminen oder einer Liste.
import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { useParticipantSelectable } from "@/contexts/participant-date-context";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal } from "@/components/ui/modal";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { TagInput } from "@/components/ui/tag-input";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { applyEventFilter, columnFilterTags, normalizeEventFilter } from "@/lib/element-types/event-filter";
import type { CycleConfigSummary, StructuredListEntry } from "@/types/api";

import { defaultColumn, defaultRow, moveItem, nextColumnId, nextRowId, type BlockForm, type MatrixColumn, type TableRow } from "./block-form";
import { EventFilterEditor } from "./event-filter-editor";
import { RowInspector, rowTypeLabel, type RowInspectorData } from "./row-inspector";

type AutoSourceType = "participants" | "events" | "list";
type Selection = { kind: "row"; id: string } | { kind: "column"; id: string };

export function RowDesigner({
  open,
  kind,
  form,
  data,
  cycleConfigs,
  initialRowId,
  onApply,
  onCancel,
}: {
  open: boolean;
  kind: "form" | "matrix";
  form: BlockForm;
  data: RowInspectorData;
  cycleConfigs: CycleConfigSummary[];
  initialRowId?: string | null;
  onApply: (next: BlockForm) => void;
  onCancel: () => void;
}) {
  const t = useTranslations("templates.elementEditor");
  const tTypes = useTranslations("templates");
  const showToast = useToast();
  const isParticipantSelectable = useParticipantSelectable();
  // Eigener Entwurf: «Abbrechen» verwirft ihn, ohne das Formular anzufassen (vorher hatte nur
  // die Matrix einen Snapshot, die Tabelle übernahm Änderungen auch beim Abbrechen).
  const [draft, setDraft] = useState<BlockForm>(form);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [dragged, setDragged] = useState<Selection | null>(null);
  const [preview, setPreview] = useState<Array<{ id: string; title: string }> | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    const rows = (form.config.rows as TableRow[] | undefined)?.length ? (form.config.rows as TableRow[]) : [defaultRow("1")];
    const columns = kind === "matrix" && form.config.mode !== "auto" && !(form.config.columns as MatrixColumn[] | undefined)?.length
      ? [defaultColumn()]
      : ((form.config.columns as MatrixColumn[] | undefined) ?? []);
    setDraft({ ...form, config: { ...form.config, rows, ...(kind === "matrix" ? { columns } : {}) } });
    setSelection({ kind: "row", id: initialRowId && rows.some((row) => row.id === initialRowId) ? initialRowId : rows[0].id });
    setPreview(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const rows = (draft.config.rows ?? []) as TableRow[];
  const columns = (draft.config.columns ?? []) as MatrixColumn[];
  const isMatrix = kind === "matrix";
  const isAuto = isMatrix && draft.config.mode === "auto";
  const autoSource = (isAuto ? draft.config.auto_source?.type ?? null : null) as AutoSourceType | null;
  const autoEventFilter = normalizeEventFilter(draft.config.auto_source?.event_filter);
  const setConfig = (patch: Record<string, unknown>) => setDraft((current) => ({ ...current, config: { ...current.config, ...patch } }));
  const setRows = (next: TableRow[]) => setConfig({ rows: next });
  const setColumns = (next: MatrixColumn[]) => setConfig({ columns: next });
  const setAutoSource = (patch: Record<string, unknown>) =>
    setConfig({ auto_source: { type: autoSource ?? "participants", list_id: null, event_filter: null, sort: "source", ...(draft.config.auto_source ?? {}), ...patch } });

  const selectedRow = selection?.kind === "row" ? rows.find((row) => row.id === selection.id) ?? null : null;
  const selectedColumn = selection?.kind === "column" ? columns.find((column) => column.id === selection.id) ?? null : null;

  useEffect(() => {
    setPreview(null);
  }, [autoSource, draft.config.auto_source?.list_id, JSON.stringify(draft.config.auto_source?.event_filter ?? null), draft.config.auto_source?.sort]); // eslint-disable-line react-hooks/exhaustive-deps

  function addRow() {
    const id = nextRowId(rows);
    setRows([...rows, defaultRow(id)]);
    setSelection({ kind: "row", id });
  }

  function addColumn() {
    const id = nextColumnId(columns);
    setColumns([...columns, defaultColumn(id)]);
    setSelection({ kind: "column", id });
  }

  function removeRow(id: string) {
    const next = rows.filter((row) => row.id !== id);
    setRows(next);
    setSelection(next[0] ? { kind: "row", id: next[0].id } : null);
  }

  function removeColumn(id: string) {
    const next = columns.filter((column) => column.id !== id);
    setColumns(next);
    setSelection(rows[0] ? { kind: "row", id: rows[0].id } : null);
  }

  function drop(target: Selection) {
    if (!dragged || dragged.kind !== target.kind) return;
    if (target.kind === "row") {
      setRows(moveItem(rows, rows.findIndex((row) => row.id === dragged.id), rows.findIndex((row) => row.id === target.id)));
    } else {
      setColumns(moveItem(columns, columns.findIndex((column) => column.id === dragged.id), columns.findIndex((column) => column.id === target.id)));
    }
    setDragged(null);
  }

  async function loadPreview() {
    setPreviewLoading(true);
    try {
      if (autoSource === "participants") {
        setPreview(data.participants.filter(isParticipantSelectable).map((participant) => ({ id: participant.id, title: participant.display_name })));
      } else if (autoSource === "events") {
        // Gleiche Regeln wie im Protokoll; die Vorschau bezieht Zeitraum/Zyklus aufs heutige Datum.
        const today = new Date().toISOString().slice(0, 10);
        const resolveCycle = (configId: string | null) => cycleConfigs.find((config) => config.id === configId) ?? null;
        setPreview(applyEventFilter(data.events, autoEventFilter, { protocolDate: today, resolveCycle }).map((event) => ({ id: event.id, title: event.title })));
      } else if (autoSource === "list") {
        const listId = draft.config.auto_source?.list_id;
        const entries = listId ? await browserApiFetch<StructuredListEntry[]>(`/api/lists/${listId}/entries`) : [];
        setPreview((entries ?? []).map((entry) => ({
          id: entry.id,
          title: String((entry.column_one_value as Record<string, unknown>)?.text_value ?? "").trim() || t("matrix.entryFallback", { id: entry.id }),
        })));
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("matrix.previewFailed"), "error");
    } finally {
      setPreviewLoading(false);
    }
  }

  const gridColumns = isMatrix ? (isAuto ? preview ?? [] : columns.map((column) => ({ id: column.id, title: column.title }))) : [];
  const gridCount = Math.max(1, gridColumns.length);
  const gridStyle = isMatrix ? { gridTemplateColumns: `minmax(180px, 200px) repeat(${gridCount}, minmax(130px, 1fr))` } : undefined;
  const gridMinWidth = isMatrix ? { minWidth: `${200 + gridCount * 136}px` } : undefined;
  const typeLabel = (rowType: string) => rowTypeLabel(rowType, t, tTypes);
  const selectedListName = useMemo(
    () => data.lists.find((list) => list.id === draft.config.auto_source?.list_id)?.name ?? "",
    [data.lists, draft.config.auto_source?.list_id]
  );

  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={isMatrix ? t("matrix.title") : t("table.title")}
      description={isMatrix ? t("matrix.description") : t("table.description")}
      size="fullscreen"
      className="matrix-designer-modal"
      footer={
        <>
          <span className="muted">{t(isMatrix ? "designer.countMatrix" : "designer.countTable", { rows: rows.length, columns: isAuto ? 0 : columns.length })}</span>
          <div className="modal-footer-actions">
            <button type="button" className="button-ghost" onClick={onCancel}>{t("cancel")}</button>
            <button type="button" className="button-primary" onClick={() => onApply(draft)}>{t("apply")}</button>
          </div>
        </>
      }
    >
      <div className="matrix-designer-layout">
        {isMatrix ? (
          <div className="matrix-designer-strip">
            <div className="matrix-designer-strip-group">
              <span className="field-label">{t("matrix.columnsLabel")}</span>
              <FilterTabs
                options={[{ value: "manual", label: t("matrix.modeManual") }, { value: "auto", label: t("matrix.modeAuto") }]}
                value={isAuto ? "auto" : "manual"}
                onChange={(mode) => {
                  setConfig({
                    mode,
                    auto_source: mode === "auto" ? draft.config.auto_source ?? { type: "participants", list_id: null, event_filter: null, sort: "source" } : null,
                    columns: mode === "manual" && !columns.length ? [defaultColumn()] : columns,
                  });
                  if (selection?.kind === "column") setSelection(rows[0] ? { kind: "row", id: rows[0].id } : null);
                }}
              />
            </div>
            {isAuto ? (
              <div className="matrix-designer-strip-group">
                <span className="field-label">{t("matrix.source")}</span>
                <FilterTabs
                  options={(["participants", "events", "list"] as AutoSourceType[]).map((value) => ({ value, label: t(`matrix.sourceType.${value}`) }))}
                  value={autoSource ?? "participants"}
                  onChange={(type) => setAutoSource({ type, event_filter: type === "events" ? autoEventFilter : null, list_id: type === "list" ? draft.config.auto_source?.list_id ?? null : null })}
                />
              </div>
            ) : null}
            {isAuto && autoSource === "list" ? (
              <div className="matrix-designer-strip-group matrix-designer-strip-field">
                <span className="field-label">{t("matrix.sourceType.list")}</span>
                <SearchableSelect
                  options={data.lists}
                  getId={(list) => list.id}
                  getLabel={(list) => list.name}
                  value={draft.config.auto_source?.list_id ?? null}
                  onChange={(list) => setAutoSource({ list_id: list?.id ?? null })}
                  nullLabel={t("matrix.chooseList")}
                />
              </div>
            ) : null}
            {isAuto ? (
              <div className="matrix-designer-strip-group">
                <label className="field-label" htmlFor="matrix-auto-sort">{t("matrix.sort")}</label>
                <select id="matrix-auto-sort" value={draft.config.auto_source?.sort ?? "source"} onChange={(event) => setAutoSource({ sort: event.target.value })}>
                  <option value="source">{t(`matrix.sortSource.${autoSource ?? "participants"}`)}</option>
                  <option value="alpha">{t("matrix.sortAlpha")}</option>
                  <option value="alpha_desc">{t("matrix.sortAlphaDesc")}</option>
                  {autoSource === "participants" ? <option value="last_name">{t("matrix.sortLastName")}</option> : null}
                </select>
              </div>
            ) : null}
            <div className="matrix-designer-strip-group matrix-designer-strip-end">
              <span className="field-label">{t("matrix.inProtocol")}</span>
              <label className="matrix-designer-switch-row">
                <input
                  type="checkbox"
                  className="mini-menu-switch-input"
                  checked={draft.config.allow_column_management !== false}
                  onChange={(event) => setConfig({ allow_column_management: event.target.checked })}
                />
                <span className="mini-menu-switch" aria-hidden="true" />
                <span>{t("matrix.columnManagement")}</span>
              </label>
            </div>
          </div>
        ) : null}

        {isAuto && autoSource === "events" ? (
          <div className="matrix-designer-source-filter">
            <EventFilterEditor
              value={autoEventFilter}
              onChange={(next) => setAutoSource({ event_filter: next })}
              knownEventTags={data.knownEventTags}
              tagConfig={data.tagConfig}
              rangeModes={["all", "future", "past", "window"]}
              cycleConfigs={cycleConfigs}
              showSortLimit
              tagLabel={t("matrix.eventTag")}
            />
          </div>
        ) : null}
        {isAuto ? (
          <div className="matrix-designer-source-note">
            {autoSource === "participants"
              ? t("matrix.sentence.participants")
              : autoSource === "events"
              ? t("matrix.sentence.events")
              : selectedListName
              ? t("matrix.sentence.list", { list: selectedListName })
              : t("matrix.sentence.listNone")}
          </div>
        ) : null}

        <div className="matrix-designer-body">
          <div className="matrix-designer-main">
            <div className="matrix-designer-toolbar">
              <span className="matrix-designer-count">{t("designer.dragHint")}</span>
              <div className="matrix-designer-toolbar-actions">
                {isAuto ? (
                  <button type="button" className="button-secondary" disabled={previewLoading || !autoSource} onClick={() => { void loadPreview(); }}>
                    {previewLoading ? t("loading") : preview ? t("matrix.refreshPreview") : t("matrix.loadPreview")}
                  </button>
                ) : isMatrix ? (
                  <button type="button" className="button-secondary" onClick={addColumn}>{t("matrix.addColumn")}</button>
                ) : null}
                <button type="button" className="button-secondary" onClick={addRow}>{t("designer.addRow")}</button>
              </div>
            </div>

            <div className="matrix-designer-grid-scroll">
              <div className="matrix-designer-rows" style={gridMinWidth}>
                {isMatrix ? (
                  <div className="matrix-designer-grid-row" style={gridStyle}>
                    <div className="matrix-designer-corner">{t("matrix.corner")}</div>
                    {!isAuto
                      ? columns.map((column, index) => (
                          <button
                            key={column.id}
                            type="button"
                            draggable
                            className={`matrix-designer-head${selectedColumn?.id === column.id ? " matrix-designer-head-active" : ""}`}
                            onClick={() => setSelection({ kind: "column", id: column.id })}
                            onDragStart={() => setDragged({ kind: "column", id: column.id })}
                            onDragEnd={() => setDragged(null)}
                            onDragOver={(event) => event.preventDefault()}
                            onDrop={(event) => { event.preventDefault(); drop({ kind: "column", id: column.id }); }}
                          >
                            <span className="matrix-designer-head-title">{column.title || t("matrix.newColumn")}</span>
                            <span className="matrix-designer-head-sub">
                              {column.event_tag_filter ? t("matrix.columnTag", { tag: column.event_tag_filter }) : t("matrix.columnNumber", { number: index + 1 })}
                            </span>
                          </button>
                        ))
                      : preview?.length
                      ? preview.map((column) => (
                          <div key={column.id} className="matrix-designer-head matrix-designer-head-preview">
                            <span className="matrix-designer-head-title">{column.title}</span>
                          </div>
                        ))
                      : (
                          <div className="matrix-designer-head-empty">
                            {previewLoading ? t("loading") : preview ? t("matrix.previewEmpty") : t("matrix.previewPending")}
                          </div>
                        )}
                  </div>
                ) : null}

                {rows.map((row, rowIndex) => {
                  const rowActive = selectedRow?.id === row.id;
                  return (
                    <div
                      key={row.id}
                      className={isMatrix ? "matrix-designer-grid-row" : "table-designer-grid-row"}
                      style={gridStyle}
                      onDragOver={(event) => event.preventDefault()}
                      onDrop={(event) => { event.preventDefault(); drop({ kind: "row", id: row.id }); }}
                    >
                      <button
                        type="button"
                        draggable
                        className={`matrix-designer-row-head${rowActive ? " matrix-designer-row-head-active" : ""}${dragged?.kind === "row" && dragged.id === row.id ? " matrix-designer-row-head-dragging" : ""}`}
                        onClick={() => setSelection({ kind: "row", id: row.id })}
                        onDragStart={() => setDragged({ kind: "row", id: row.id })}
                        onDragEnd={() => setDragged(null)}
                      >
                        <span className="matrix-designer-row-num">{rowIndex + 1}</span>
                        <span className="matrix-designer-row-text">
                          <span className="matrix-designer-head-title">{row.label || t("row.unnamed")}</span>
                          <span className="matrix-designer-head-sub">
                            {row.locked_in_protocol ? t("row.typeLocked", { type: typeLabel(row.row_type) }) : typeLabel(row.row_type)}
                          </span>
                        </span>
                      </button>
                      {isMatrix
                        ? (isAuto ? (preview?.length ? preview : [{ id: "placeholder", title: "" }]) : columns).map((column) => (
                            <button
                              key={`${row.id}-${column.id}`}
                              type="button"
                              className={`matrix-designer-cell${rowActive ? " matrix-designer-cell-column" : ""}`}
                              onClick={() => setSelection({ kind: "row", id: row.id })}
                            >
                              <span className="matrix-designer-cell-text">
                                {row.row_type === "events" && !isAuto
                                  ? (() => {
                                      // Gleiche Regel wie im Protokoll: Zeilen-Tags, plus Spaltenfilter nur mit «Spalten-Tagfilter anwenden».
                                      const rowFilter = normalizeEventFilter(row.row_config.event_filter, "future");
                                      const tags = [...rowFilter.tags, ...(rowFilter.use_column_filter ? columnFilterTags(column as MatrixColumn) : [])];
                                      return tags.join(", ") || t("matrix.allEvents");
                                    })()
                                  : row.auto_source_field
                                  ? t(`autoField.${row.auto_source_field}`)
                                  : typeLabel(row.row_type)}
                              </span>
                              <span className={`matrix-designer-cell-bar${row.row_type === "text" ? " matrix-designer-cell-bar-wide" : ""}`} />
                            </button>
                          ))
                        : null}
                    </div>
                  );
                })}

                <button type="button" className="matrix-designer-add-row" onClick={addRow}>{t("designer.addRowLong")}</button>
              </div>
            </div>
          </div>

          <aside className="matrix-designer-panel">
            {selectedColumn ? (
              <div className="matrix-designer-inspector">
                <div className="matrix-designer-inspector-header">
                  <div>
                    <div className="eyebrow">{t("matrix.columnNumber", { number: columns.findIndex((column) => column.id === selectedColumn.id) + 1 })}</div>
                    <div className="matrix-designer-inspector-title">{selectedColumn.title || t("matrix.newColumn")}</div>
                  </div>
                  <button type="button" className="button-ghost button-danger" onClick={() => removeColumn(selectedColumn.id)}>{t("remove")}</button>
                </div>
                <label className="field-stack">
                  <span className="field-label">{t("matrix.columnTitle")}</span>
                  <input
                    value={selectedColumn.title}
                    onChange={(event) => setColumns(columns.map((column) => column.id === selectedColumn.id ? { ...column, title: event.target.value } : column))}
                    placeholder={t("matrix.columnTitlePlaceholder")}
                  />
                </label>
                <label className="field-stack">
                  <span className="field-label">{t("matrix.columnPlaceholder")}</span>
                  <input
                    value={selectedColumn.title_placeholder}
                    onChange={(event) => setColumns(columns.map((column) => column.id === selectedColumn.id ? { ...column, title_placeholder: event.target.value } : column))}
                    placeholder={t("matrix.columnPlaceholderExample")}
                  />
                  <span className="field-help">{t("matrix.columnPlaceholderHelp")}</span>
                </label>
                <label className="field-stack">
                  <span className="field-label">{t("matrix.columnTagFilter")}</span>
                  <TagInput
                    value={selectedColumn.event_tag_filter}
                    onChange={(value) => setColumns(columns.map((column) => column.id === selectedColumn.id ? { ...column, event_tag_filter: value } : column))}
                    suggestions={data.knownEventTags}
                    tagConfig={data.tagConfig}
                    placeholder={t("matrix.columnTagFilterPlaceholder")}
                  />
                  <span className="field-help">{t("matrix.columnTagFilterHelp")}</span>
                </label>
              </div>
            ) : selectedRow ? (
              <RowInspector
                row={selectedRow}
                kind={kind}
                autoSource={autoSource}
                data={data}
                heading={t("row.number", { number: rows.findIndex((row) => row.id === selectedRow.id) + 1 })}
                onChange={(next) => setRows(rows.map((row) => (row.id === next.id ? next : row)))}
                onRemove={() => removeRow(selectedRow.id)}
              />
            ) : (
              <p className="muted matrix-designer-inspector">{t("designer.selectHint")}</p>
            )}
          </aside>
        </div>
      </div>
    </Modal>
  );
}
