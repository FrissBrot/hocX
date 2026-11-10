// Zugriff auf die Elementtyp-Registry (generiert aus element-types/registry.json, siehe
// scripts/sync-element-types.py). Ersetzt die früher verstreuten id→Code-, id→Render-Typ- und
// Typ-Gruppen-Tabellen im Element-Editor und in protocol-editor-shared.tsx sowie die rund 60
// Vergleiche wie `element_type_id === "6"`.
import { ELEMENT_TYPES, type ElementTypeCategory, type ElementTypeCode, type ElementTypeInfo, type RepeatSource } from "./registry.generated";

export type { ElementTypeCategory, ElementTypeCode, ElementTypeInfo, RepeatSource };

const BY_ID = new Map<number, ElementTypeInfo>(ELEMENT_TYPES.map((entry) => [entry.id, entry]));
const BY_CODE = new Map<ElementTypeCode, ElementTypeInfo>(ELEMENT_TYPES.map((entry) => [entry.code, entry]));
const FALLBACK = BY_CODE.get("text") as ElementTypeInfo;

export const ELEMENT_TYPE_CATEGORIES: readonly ElementTypeCategory[] = ["basics", "finance", "organisation"];

export function elementType(id: number | string | null | undefined): ElementTypeInfo {
  return BY_ID.get(Number(id)) ?? FALLBACK;
}

export function isKnownElementType(id: number | string | null | undefined): boolean {
  return BY_ID.has(Number(id));
}

export function elementTypeCode(id: number | string | null | undefined): ElementTypeCode {
  return elementType(id).code;
}

export function elementTypeId(code: ElementTypeCode): number {
  return (BY_CODE.get(code) ?? FALLBACK).id;
}

/** Typen für die Typauswahl im Element-Editor, in Registry-Reihenfolge. */
export function pickableElementTypes(): ElementTypeInfo[] {
  return ELEMENT_TYPES.filter((entry) => entry.pickable);
}

/** Typen, die als eingebetteter Block in einer Matrix- oder Tabellenzeile wählbar sind. */
export function embeddableElementTypes(): ElementTypeInfo[] {
  return ELEMENT_TYPES.filter((entry) => entry.matrixEmbeddable);
}
