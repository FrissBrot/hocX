// GENERATED FILE - do not edit by hand. Source of truth: element-types/registry.json (repo root).
// Regenerate with: python3 scripts/sync-element-types.py

export type ElementTypeCode = "text" | "todo" | "image" | "display" | "static_text" | "form" | "event_list" | "bullet_list" | "attendance" | "session_date" | "matrix" | "finance_balance" | "finance_transactions" | "fine_list" | "chart" | "entry_exit" | "session_notes";
export type ElementTypeCategory = "basics" | "finance" | "organisation";
export type RepeatSource = "event" | "todo";

export type ElementTypeInfo = {
  id: number;
  code: ElementTypeCode;
  category: ElementTypeCategory;
  renderTypeId: number;
  allowsMultipleValues: boolean;
  defaultEditable: boolean;
  pickable: boolean;
  content: boolean;
  repeat: RepeatSource[];
  carryOver: boolean;
  matrixEmbeddable: boolean;
};

export const ELEMENT_TYPES: readonly ElementTypeInfo[] = [
  { id: 1, code: "text", category: "basics", renderTypeId: 2, allowsMultipleValues: false, defaultEditable: true, pickable: true, content: true, repeat: ["event", "todo"], carryOver: true, matrixEmbeddable: true },
  { id: 2, code: "todo", category: "basics", renderTypeId: 3, allowsMultipleValues: true, defaultEditable: true, pickable: true, content: false, repeat: ["event", "todo"], carryOver: false, matrixEmbeddable: true },
  { id: 3, code: "image", category: "basics", renderTypeId: 4, allowsMultipleValues: true, defaultEditable: true, pickable: true, content: false, repeat: ["event", "todo"], carryOver: true, matrixEmbeddable: true },
  { id: 4, code: "display", category: "basics", renderTypeId: 6, allowsMultipleValues: false, defaultEditable: false, pickable: false, content: false, repeat: [], carryOver: false, matrixEmbeddable: false },
  { id: 5, code: "static_text", category: "basics", renderTypeId: 6, allowsMultipleValues: false, defaultEditable: false, pickable: false, content: true, repeat: [], carryOver: true, matrixEmbeddable: false },
  { id: 6, code: "form", category: "basics", renderTypeId: 5, allowsMultipleValues: false, defaultEditable: true, pickable: true, content: false, repeat: ["event", "todo"], carryOver: false, matrixEmbeddable: true },
  { id: 7, code: "event_list", category: "organisation", renderTypeId: 5, allowsMultipleValues: false, defaultEditable: false, pickable: true, content: false, repeat: [], carryOver: false, matrixEmbeddable: true },
  { id: 8, code: "bullet_list", category: "basics", renderTypeId: 2, allowsMultipleValues: false, defaultEditable: true, pickable: false, content: false, repeat: [], carryOver: false, matrixEmbeddable: false },
  { id: 9, code: "attendance", category: "organisation", renderTypeId: 5, allowsMultipleValues: false, defaultEditable: false, pickable: true, content: false, repeat: [], carryOver: false, matrixEmbeddable: true },
  { id: 10, code: "session_date", category: "organisation", renderTypeId: 6, allowsMultipleValues: false, defaultEditable: true, pickable: true, content: false, repeat: [], carryOver: false, matrixEmbeddable: true },
  { id: 11, code: "matrix", category: "basics", renderTypeId: 5, allowsMultipleValues: false, defaultEditable: true, pickable: true, content: false, repeat: [], carryOver: false, matrixEmbeddable: false },
  { id: 12, code: "finance_balance", category: "finance", renderTypeId: 6, allowsMultipleValues: false, defaultEditable: true, pickable: true, content: false, repeat: [], carryOver: false, matrixEmbeddable: false },
  { id: 13, code: "finance_transactions", category: "finance", renderTypeId: 5, allowsMultipleValues: false, defaultEditable: true, pickable: true, content: false, repeat: [], carryOver: false, matrixEmbeddable: false },
  { id: 14, code: "fine_list", category: "finance", renderTypeId: 5, allowsMultipleValues: false, defaultEditable: true, pickable: true, content: false, repeat: [], carryOver: false, matrixEmbeddable: false },
  { id: 15, code: "chart", category: "organisation", renderTypeId: 6, allowsMultipleValues: false, defaultEditable: true, pickable: true, content: false, repeat: [], carryOver: false, matrixEmbeddable: false },
  { id: 16, code: "entry_exit", category: "organisation", renderTypeId: 5, allowsMultipleValues: false, defaultEditable: false, pickable: true, content: false, repeat: [], carryOver: false, matrixEmbeddable: false },
  { id: 17, code: "session_notes", category: "organisation", renderTypeId: 6, allowsMultipleValues: false, defaultEditable: true, pickable: true, content: false, repeat: [], carryOver: false, matrixEmbeddable: false },
];
