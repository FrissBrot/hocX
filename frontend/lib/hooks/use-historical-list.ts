import { useCallback, useEffect, useState } from "react";

import { browserApiFetch } from "@/lib/api/client";
import {
  StructuredListDefinition,
  StructuredListEntry,
  StructuredListValueType,
  TableSnapshotCycleSummary,
  TableSnapshotListReconstructDraft,
  TableSnapshotRowsRead,
} from "@/types/api";

/** snapshot_json rows are raw column dicts (see backend row_to_dict()) - column names
 * match the ORM model, not the frontend's schema-renamed field names (e.g.
 * column_one_value_json, not column_one_value). Maps a historical list_definition row
 * into the same shape the live list manager already renders. */
function mapDefinitionRow(row: Record<string, unknown>): StructuredListDefinition {
  return {
    id: String(row.public_id ?? ""),
    tenant_id: String(row.tenant_id ?? ""),
    name: String(row.name ?? ""),
    description: (row.description as string | null) ?? null,
    column_one_title: String(row.column_one_title ?? ""),
    column_one_value_type: row.column_one_value_type as StructuredListValueType,
    column_two_title: String(row.column_two_title ?? ""),
    column_two_value_type: row.column_two_value_type as StructuredListValueType,
    is_active: Boolean(row.is_active),
    content_version: Number(row.content_version ?? 0),
    created_at: String(row.created_at ?? ""),
    updated_at: String(row.updated_at ?? ""),
  };
}

function mapEntryRow(row: Record<string, unknown>, listDefinitionPublicId: string): StructuredListEntry {
  return {
    id: String(row.public_id ?? ""),
    list_definition_id: listDefinitionPublicId,
    sort_index: Number(row.sort_index ?? 0),
    column_one_value: (row.column_one_value_json as Record<string, unknown>) ?? {},
    column_two_value: (row.column_two_value_json as Record<string, unknown>) ?? {},
    created_at: String(row.created_at ?? ""),
    updated_at: String(row.updated_at ?? ""),
  };
}

/** Draft entries (from the reconstruct-draft endpoint) already use the un-suffixed
 * frontend field names except column_one_value_json/column_two_value_json, which the
 * backend keeps as-is since that's the shape it round-trips back into the reconstruct
 * POST. */
function mapDraftEntry(row: Record<string, unknown>, listDefinitionPublicId: string): StructuredListEntry {
  return {
    id: String(row.public_id ?? ""),
    list_definition_id: listDefinitionPublicId,
    sort_index: Number(row.sort_index ?? 0),
    column_one_value: (row.column_one_value_json as Record<string, unknown>) ?? {},
    column_two_value: (row.column_two_value_json as Record<string, unknown>) ?? {},
    created_at: "",
    updated_at: "",
  };
}

export type HistoricalListState = {
  mode: "live" | "historical" | "reconstructing";
  availableCycles: TableSnapshotCycleSummary[];
  cycleConfigId: string | null;
  cycleYear: number | null;
  cycleConfigName: string | null;
  isLoading: boolean;
  /** null while mode is "live", or if the selected list didn't exist yet in that cycle. */
  definition: StructuredListDefinition | null;
  entries: StructuredListEntry[];
  isEdited: boolean;
  editUnlocked: boolean;
  /** Only set while mode === "reconstructing": where the draft was pre-filled from. */
  reconstructSource: { kind: "live" | "snapshot"; cycleYear: number | null } | null;
  switchToHistorical: (cycleConfigId: string, cycleYear: number, hasSnapshot: boolean) => void;
  switchToLive: () => void;
  unlockEditing: () => void;
  saveHistoricalEntry: (
    entryPublicId: string,
    values: Partial<{ sort_index: number; column_one_value: Record<string, unknown>; column_two_value: Record<string, unknown> }>
  ) => Promise<void>;
  deleteHistoricalEntry: (entryPublicId: string) => Promise<void>;
  /** Reconstruction-mode-only: edits stay purely local until confirmReconstruction(). */
  updateDraftEntry: (
    entryPublicId: string,
    values: Partial<{ sort_index: number; column_one_value: Record<string, unknown>; column_two_value: Record<string, unknown> }>
  ) => void;
  deleteDraftEntry: (entryPublicId: string) => void;
  confirmReconstruction: () => Promise<void>;
  cancelReconstruction: () => void;
};

/** Owns "which cycle the Listen overview is currently viewing" for one selected list -
 * live, a real historical snapshot, or an in-progress reconstruction of a period that
 * has no snapshot yet (see list_snapshot_cycles' has_snapshot flag). A list's history
 * spans two snapshotted tables (list_definition for name/column titles, list_entry for
 * the rows) that have to be cross-referenced: list_entry rows keep the definition's
 * *internal* id from snapshot time, not its public_id, so the definition snapshot is
 * fetched first to resolve which internal id belongs to the currently selected list's
 * public_id. */
export function useHistoricalList(selectedListId: string | null): HistoricalListState {
  const [cycles, setCycles] = useState<TableSnapshotCycleSummary[]>([]);
  const [selected, setSelected] = useState<{ cycleConfigId: string; cycleYear: number; cycleConfigName: string } | null>(null);
  const [mode, setMode] = useState<"live" | "historical" | "reconstructing">("live");
  const [definition, setDefinition] = useState<StructuredListDefinition | null>(null);
  const [entries, setEntries] = useState<StructuredListEntry[]>([]);
  const [isEdited, setIsEdited] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [editUnlocked, setEditUnlocked] = useState(false);
  const [reconstructSource, setReconstructSource] = useState<{ kind: "live" | "snapshot"; cycleYear: number | null } | null>(null);

  const refetchCycles = useCallback(() => {
    return browserApiFetch<TableSnapshotCycleSummary[]>("/api/table-snapshots/cycles")
      .then((data) => setCycles(data))
      .catch(() => setCycles([]));
  }, []);

  useEffect(() => {
    void refetchCycles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadForList = useCallback(
    (cycleConfigId: string, cycleYear: number, listId: string | null) => {
      if (!listId) {
        setDefinition(null);
        setEntries([]);
        return;
      }
      setIsLoading(true);
      Promise.all([
        browserApiFetch<TableSnapshotRowsRead>(`/api/table-snapshots/${cycleConfigId}/${cycleYear}/list_definition`),
        browserApiFetch<TableSnapshotRowsRead>(`/api/table-snapshots/${cycleConfigId}/${cycleYear}/list_entry`),
      ])
        .then(([definitionsRead, entriesRead]) => {
          const definitionRow = definitionsRead.rows.find((row) => row.public_id === listId);
          if (!definitionRow) {
            setDefinition(null);
            setEntries([]);
            setIsEdited(definitionsRead.is_edited || entriesRead.is_edited);
            return;
          }
          const mappedDefinition = mapDefinitionRow(definitionRow);
          const internalId = definitionRow.id;
          const mappedEntries = entriesRead.rows
            .filter((row) => row.list_definition_id === internalId)
            .map((row) => mapEntryRow(row, listId))
            .sort((a, b) => a.sort_index - b.sort_index);
          setDefinition(mappedDefinition);
          setEntries(mappedEntries);
          setIsEdited(definitionsRead.is_edited || entriesRead.is_edited);
        })
        .finally(() => setIsLoading(false));
    },
    []
  );

  const loadDraftForList = useCallback((cycleConfigId: string, cycleYear: number, listId: string) => {
    setIsLoading(true);
    browserApiFetch<TableSnapshotListReconstructDraft>(
      `/api/table-snapshots/${cycleConfigId}/${cycleYear}/lists/${listId}/reconstruct-draft`
    )
      .then((draft) => {
        setDefinition(mapDefinitionRow({ public_id: listId, ...draft.definition_values }));
        setEntries(draft.entries.map((row) => mapDraftEntry(row, listId)).sort((a, b) => a.sort_index - b.sort_index));
        setReconstructSource({ kind: draft.source, cycleYear: draft.source_cycle_year });
      })
      .catch(() => {
        setDefinition(null);
        setEntries([]);
        setReconstructSource(null);
      })
      .finally(() => setIsLoading(false));
  }, []);

  const switchToHistorical = useCallback(
    (cycleConfigId: string, cycleYear: number, hasSnapshot: boolean) => {
      const cycleConfigName = cycles.find((c) => c.cycle_config_id === cycleConfigId)?.cycle_config_name ?? "";
      setSelected({ cycleConfigId, cycleYear, cycleConfigName });
      setEditUnlocked(false);
      if (!hasSnapshot) {
        setMode("reconstructing");
        if (selectedListId) loadDraftForList(cycleConfigId, cycleYear, selectedListId);
        return;
      }
      setMode("historical");
      setReconstructSource(null);
      loadForList(cycleConfigId, cycleYear, selectedListId);
    },
    [cycles, loadForList, loadDraftForList, selectedListId]
  );

  const switchToLive = useCallback(() => {
    setSelected(null);
    setMode("live");
    setDefinition(null);
    setEntries([]);
    setIsEdited(false);
    setEditUnlocked(false);
    setReconstructSource(null);
  }, []);

  const cancelReconstruction = switchToLive;

  // Switching which list is selected in the sidebar while a historical/reconstructing
  // cycle is active re-fetches for the new list under the *same* cycle, instead of
  // forcing back to live.
  useEffect(() => {
    if (!selected) return;
    setEditUnlocked(false);
    if (mode === "reconstructing") {
      if (selectedListId) loadDraftForList(selected.cycleConfigId, selected.cycleYear, selectedListId);
    } else {
      loadForList(selected.cycleConfigId, selected.cycleYear, selectedListId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedListId]);

  const unlockEditing = useCallback(() => setEditUnlocked(true), []);

  const saveHistoricalEntry = useCallback(
    async (
      entryPublicId: string,
      values: Partial<{ sort_index: number; column_one_value: Record<string, unknown>; column_two_value: Record<string, unknown> }>
    ) => {
      if (!selected || !selectedListId) throw new Error("Kein historischer Zyklus ausgewählt");
      const backendValues: Record<string, unknown> = {};
      if (values.sort_index !== undefined) backendValues.sort_index = values.sort_index;
      if (values.column_one_value !== undefined) backendValues.column_one_value_json = values.column_one_value;
      if (values.column_two_value !== undefined) backendValues.column_two_value_json = values.column_two_value;
      const updated = await browserApiFetch<Record<string, unknown>>(
        `/api/table-snapshots/${selected.cycleConfigId}/${selected.cycleYear}/list_entry/rows/${entryPublicId}`,
        { method: "PUT", body: JSON.stringify({ values: backendValues, confirm_historical_edit: true }) }
      );
      setIsEdited(true);
      setEntries((current) =>
        current.map((entry) => (entry.id === entryPublicId ? mapEntryRow(updated, selectedListId) : entry))
      );
    },
    [selected, selectedListId]
  );

  const deleteHistoricalEntry = useCallback(
    async (entryPublicId: string) => {
      if (!selected) throw new Error("Kein historischer Zyklus ausgewählt");
      await browserApiFetch(
        `/api/table-snapshots/${selected.cycleConfigId}/${selected.cycleYear}/list_entry/rows/${entryPublicId}`,
        { method: "DELETE", body: JSON.stringify({ confirm_historical_edit: true }) }
      );
      setIsEdited(true);
      setEntries((current) => current.filter((entry) => entry.id !== entryPublicId));
    },
    [selected]
  );

  const updateDraftEntry = useCallback(
    (
      entryPublicId: string,
      values: Partial<{ sort_index: number; column_one_value: Record<string, unknown>; column_two_value: Record<string, unknown> }>
    ) => {
      setEntries((current) => current.map((entry) => (entry.id === entryPublicId ? { ...entry, ...values } : entry)));
    },
    []
  );

  const deleteDraftEntry = useCallback((entryPublicId: string) => {
    setEntries((current) => current.filter((entry) => entry.id !== entryPublicId));
  }, []);

  const confirmReconstruction = useCallback(async () => {
    if (!selected || !selectedListId || !definition) throw new Error("Kein Entwurf zum Bestätigen");
    await browserApiFetch(
      `/api/table-snapshots/${selected.cycleConfigId}/${selected.cycleYear}/lists/${selectedListId}/reconstruct`,
      {
        method: "POST",
        body: JSON.stringify({
          definition_values: {
            name: definition.name,
            description: definition.description,
            column_one_title: definition.column_one_title,
            column_one_value_type: definition.column_one_value_type,
            column_two_title: definition.column_two_title,
            column_two_value_type: definition.column_two_value_type,
            is_active: definition.is_active,
          },
          entries: entries.map((entry) => ({
            public_id: entry.id,
            sort_index: entry.sort_index,
            column_one_value_json: entry.column_one_value,
            column_two_value_json: entry.column_two_value,
          })),
        }),
      }
    );
    setMode("historical");
    setReconstructSource(null);
    await refetchCycles();
    loadForList(selected.cycleConfigId, selected.cycleYear, selectedListId);
  }, [selected, selectedListId, definition, entries, refetchCycles, loadForList]);

  return {
    mode,
    availableCycles: cycles,
    cycleConfigId: selected?.cycleConfigId ?? null,
    cycleYear: selected?.cycleYear ?? null,
    cycleConfigName: selected?.cycleConfigName ?? null,
    isLoading,
    definition,
    entries,
    isEdited,
    editUnlocked,
    reconstructSource,
    switchToHistorical,
    switchToLive,
    unlockEditing,
    saveHistoricalEntry,
    deleteHistoricalEntry,
    updateDraftEntry,
    deleteDraftEntry,
    confirmReconstruction,
    cancelReconstruction,
  };
}
