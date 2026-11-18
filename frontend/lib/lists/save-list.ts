// Listen mit Spalten speichern (Migration 0186) - gemeinsam für die Listenverwaltung am Desktop
// (components/lists/list-manager.tsx) und auf dem Handy (mobile-lists.tsx). Neue Listen gehen mit
// ihren Startspalten in einem Aufruf; bestehende Spalten über die Spalten-Endpunkte (entfernen,
// ändern, anlegen, Reihenfolge), danach Name und Rollen. Löschen und Typwechsel fragen vorher nach.
import { browserApiFetch } from "@/lib/api/client";
import type { ListColumn, StructuredListDefinition, StructuredListValueType } from "@/types/api";

export const MAX_COLUMNS = 20;

/** Spalte im Formular: `id` = Spalten-Key einer bestehenden Spalte, `localId` auch für neue. */
export type ColumnFormState = { localId: string; id?: string; title: string; value_type: StructuredListValueType; savedType?: StructuredListValueType };

export type ListSaveRequest = {
  name: string;
  description: string;
  is_active: boolean;
  is_group_source: boolean;
  columns: ColumnFormState[];
  /** localId der Spalten mit Rolle «Bezeichnung» bzw. «Verantwortliche» ("" = keine) */
  labelColumn: string;
  responsibleColumn: string;
};

export type ColumnUsage = { kind: string; label: string; href?: string | null };

let newColumnCounter = 0;
export function newLocalId() {
  newColumnCounter += 1;
  return `neu-${newColumnCounter}`;
}

export const isPersonType = (type: StructuredListValueType) => type === "participant" || type === "participants";

export function columnsForForm(definition: StructuredListDefinition): ColumnFormState[] {
  return [...definition.columns]
    .sort((left, right) => left.sort_index - right.sort_index)
    .map((column) => ({ localId: column.id, id: column.id, title: column.title, value_type: column.value_type, savedType: column.value_type }));
}

const ordered = (columns: ListColumn[]) => [...columns].sort((left, right) => left.sort_index - right.sort_index);

export async function createListDefinition(request: ListSaveRequest): Promise<StructuredListDefinition> {
  const created = await browserApiFetch<StructuredListDefinition>("/api/lists", {
    method: "POST",
    body: JSON.stringify({
      name: request.name.trim(),
      description: request.description || null,
      is_active: request.is_active,
      is_group_source: request.is_group_source,
      columns: request.columns.map((column) => ({ title: column.title.trim(), value_type: column.value_type })),
    }),
  });
  // Rollen auf die neuen Spalten-Keys (gleiche Reihenfolge wie im Formular)
  const keyOf = (localId: string) => {
    const index = request.columns.findIndex((column) => column.localId === localId);
    return index >= 0 ? ordered(created.columns)[index]?.id ?? null : null;
  };
  return browserApiFetch<StructuredListDefinition>(`/api/lists/${created.id}`, {
    method: "PATCH",
    body: JSON.stringify({ label_column_id: keyOf(request.labelColumn), responsible_column_id: keyOf(request.responsibleColumn) }),
  });
}

export async function updateListDefinition(
  original: StructuredListDefinition,
  request: ListSaveRequest,
  confirmations: {
    confirmRemove: (column: ListColumn, usages: ColumnUsage[]) => Promise<boolean>;
    confirmRetype: (titles: string[]) => Promise<boolean>;
  }
): Promise<StructuredListDefinition | null> {
  const listId = original.id;
  const columnUrl = (key: string) => `/api/lists/${listId}/columns/${encodeURIComponent(key)}`;
  const removed = original.columns.filter((column) => !request.columns.some((entry) => entry.id === column.id));
  for (const column of removed) {
    const usages = await browserApiFetch<ColumnUsage[]>(`${columnUrl(column.id)}/usages`);
    if (!(await confirmations.confirmRemove(column, usages))) return null;
  }
  const retyped = request.columns.filter((column) => column.id && column.savedType && column.savedType !== column.value_type);
  if (retyped.length && !(await confirmations.confirmRetype(retyped.map((column) => column.title)))) return null;

  let current = original;
  for (const column of removed) {
    current = await browserApiFetch<StructuredListDefinition>(columnUrl(column.id), { method: "DELETE" });
  }
  const keyByLocal: Record<string, string> = {};
  for (const column of request.columns) {
    if (column.id) {
      keyByLocal[column.localId] = column.id;
      const before = original.columns.find((entry) => entry.id === column.id);
      if (before && (before.title !== column.title.trim() || before.value_type !== column.value_type)) {
        current = await browserApiFetch<StructuredListDefinition>(columnUrl(column.id), {
          method: "PATCH",
          body: JSON.stringify({ title: column.title.trim(), value_type: column.value_type }),
        });
      }
    } else {
      const known = new Set(current.columns.map((entry) => entry.id));
      current = await browserApiFetch<StructuredListDefinition>(`/api/lists/${listId}/columns`, {
        method: "POST",
        body: JSON.stringify({ title: column.title.trim(), value_type: column.value_type }),
      });
      const added = current.columns.find((entry) => !known.has(entry.id));
      if (added) keyByLocal[column.localId] = added.id;
    }
  }
  const order = request.columns.map((column) => keyByLocal[column.localId]).filter(Boolean);
  if (order.join("|") !== ordered(current.columns).map((column) => column.id).join("|")) {
    current = await browserApiFetch<StructuredListDefinition>(`/api/lists/${listId}/columns/order`, {
      method: "PUT",
      body: JSON.stringify({ column_ids: order }),
    });
  }
  return browserApiFetch<StructuredListDefinition>(`/api/lists/${listId}`, {
    method: "PATCH",
    body: JSON.stringify({
      name: request.name.trim(),
      description: request.description || null,
      is_active: request.is_active,
      is_group_source: request.is_group_source,
      label_column_id: keyByLocal[request.labelColumn] ?? null,
      responsible_column_id: keyByLocal[request.responsibleColumn] ?? null,
    }),
  });
}
