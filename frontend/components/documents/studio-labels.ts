// Bezeichnungen des Document Studio, die aus Daten abgeleitet werden (Systemvorlagen, Bindungen,
// Bibliothek). Reine Hilfsfunktionen: sie bekommen ``t`` (Namespace documentStudio) übergeben.

import type { BindingInfo, DocumentTemplateInfo } from "@/lib/documents/api";

type TFunc = ((key: string, values?: Record<string, string | number>) => string) & { has?: (key: string) => boolean };

/** Name einer Vorlage: Systemvorlagen übersetzt, eigene Vorlagen mit ihrem Namen. */
export function templateDisplayName(t: TFunc, template: Pick<DocumentTemplateInfo, "origin" | "system_key" | "name">): string {
  if (template.origin === "system" && template.system_key) return t(`system.${template.system_key}.name`);
  return template.name;
}

export function templateDescription(t: TFunc, template: Pick<DocumentTemplateInfo, "origin" | "system_key" | "description">): string {
  if (template.origin === "system" && template.system_key) return t(`system.${template.system_key}.description`);
  return template.description ?? "";
}

/** Label einer Datenbindung (Pfad), auch für Elementfelder ``item.<feld>``. */
export function bindingLabel(t: TFunc, path: string): string {
  if (path.startsWith("item.")) return t(`bindingField.${path.slice(5)}`);
  if (path.startsWith("brand.images.")) return t("binding.brandImage", { key: path.slice(13) });
  return t(`binding.${path.replace(/\./g, "_")}`);
}

export function groupBindings(bindings: BindingInfo[]): Record<string, BindingInfo[]> {
  const groups: Record<string, BindingInfo[]> = {};
  for (const binding of bindings) (groups[binding.group] ??= []).push(binding);
  return groups;
}
