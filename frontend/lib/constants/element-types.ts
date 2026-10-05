// Canonical list of template element types (element_type_id -> label/description).
//
// Previously duplicated as two independently-maintained maps:
//   - ELEMENT_TYPE_LABELS in components/template/template-builder.tsx (id -> label only)
//   - elementTypeOptions in components/template/element-definition-manager.tsx (id -> label + description)
// A new element type added to one map but not the other silently showed as "Block #<id>" /
// "Unbekannt (<id>)" in the other screen. Both now import from here instead.
//
// Functions, not constants: this module has no React component to call useTranslations() in,
// so each caller passes its own `t` (usually `useTranslations("templates")`) - see
// components/ui/section-tabs.ts for the same pattern.
type TFunc = (key: string) => string;

export type ElementTypeOption = {
  value: string;
  label: string;
  description: string;
};

const ELEMENT_TYPE_IDS = ["1", "2", "3", "6", "7", "9", "10", "11", "12", "13", "14", "15", "16", "17"] as const;

export function elementTypeOptions(t: TFunc): ElementTypeOption[] {
  return ELEMENT_TYPE_IDS.map((value) => ({
    value,
    label: t(`elementTypes.${value}.label`),
    description: t(`elementTypes.${value}.description`),
  }));
}

// id -> label only, for spots that just need a display label (e.g. a fallback block title)
// rather than the full option/description list used by the element-type picker.
export function elementTypeLabels(t: TFunc): Record<number, string> {
  const result: Record<number, string> = {};
  for (const value of ELEMENT_TYPE_IDS) {
    result[Number(value)] = t(`elementTypes.${value}.label`);
  }
  return result;
}
