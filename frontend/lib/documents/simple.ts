// Modus «Einfach» des Designers: ordnet Knoten der obersten Ebene einem Baustein der
// Beschreibung aus dem Backend zu (backend/app/documents/simple.py) und liest/schreibt deren
// Einstellungen über Pfade. Bearbeitet wird dieselbe Vorlage wie im Modus «Erweitert».

import type { SimpleBlock, SimpleCatalog, SimpleSetting } from "@/lib/documents/api";
import type { Condition, Inline, TemplateNode, TextContent } from "@/lib/documents/layout";

/** Erster passender Baustein oder null («Eigener Bereich»). */
export function matchSimpleBlock(catalog: SimpleCatalog, node: TemplateNode): SimpleBlock | null {
  return (
    catalog.blocks.find((block) => {
      const types = Array.isArray(block.match.type) ? block.match.type : [block.match.type];
      if (!types.includes(node.type)) return false;
      if (block.match.component && !block.match.component.includes(String(node.component ?? ""))) return false;
      if (block.match.role && !block.match.role.includes(String(node.role ?? "paragraph"))) return false;
      return true;
    }) ?? null
  );
}

export function getPath(node: TemplateNode, path: string): unknown {
  return path.split(".").reduce<unknown>((value, key) => (value && typeof value === "object" ? (value as Record<string, unknown>)[key] : undefined), node);
}

/** Wert an einem Pfad setzen (unveränderlich: nur die Objekte auf dem Pfad werden kopiert). */
export function setPath(node: TemplateNode, path: string, value: unknown): TemplateNode {
  const [head, ...rest] = path.split(".");
  const current = (node as Record<string, unknown>)[head];
  const next = rest.length ? setPath((current && typeof current === "object" ? current : {}) as TemplateNode, rest.join("."), value) : value;
  return { ...node, [head]: next };
}

/** Schalter-Einstellung: aktueller Wert mit Standard. */
export function toggleValue(node: TemplateNode, setting: Extract<SimpleSetting, { kind: "toggle" }>): boolean {
  const value = getPath(node, setting.path);
  return typeof value === "boolean" ? value : setting.default;
}

function sameCondition(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

/** Name der fertigen Bedingung des Knotens; «custom» bei einer anderen Regel, null ohne Regel. */
export function conditionPreset(catalog: SimpleCatalog, node: TemplateNode): string | "custom" | null {
  if (!node.visible_if) return null;
  return Object.entries(catalog.conditions).find(([, condition]) => sameCondition(condition, node.visible_if))?.[0] ?? "custom";
}

export function conditionFor(catalog: SimpleCatalog, name: string): Condition {
  return catalog.conditions[name];
}

/** Reiner Text einer TextContent, oder null, wenn sie Datenfelder/Schlüssel enthält (dann
 * nur im Modus «Erweitert» bearbeitbar). */
export function plainText(content: TextContent | undefined | null): string | null {
  if (!content) return "";
  if (content.translations && Object.keys(content.translations).length > 0) return null;
  let text = "";
  for (const inline of content.default) {
    if (inline.t === "text" && !inline.b && !inline.i) text += inline.v;
    else if (inline.t === "br") text += "\n";
    else return null;
  }
  return text;
}

export function textContent(text: string): TextContent {
  const parts: Inline[] = [];
  text.split("\n").forEach((line, index) => {
    if (index > 0) parts.push({ t: "br" });
    if (line) parts.push({ t: "text", v: line });
  });
  return { default: parts };
}

/** Darstellung einer Elementart dieses Blocks (Übersteuerung im Knoten), leer = geerbt. */
export function variantValue(node: TemplateNode, kind: string): string {
  const appearance = node.appearance as Record<string, { variant?: string | null }> | undefined;
  return appearance?.[kind]?.variant ?? "";
}

export function setVariant(node: TemplateNode, kind: string, variant: string): TemplateNode {
  const appearance = { ...((node.appearance as Record<string, { variant?: string | null; corners?: string | null }>) ?? {}) };
  const merged = { ...(appearance[kind] ?? {}), variant: variant || null };
  if (!merged.variant && !merged.corners) delete appearance[kind];
  else appearance[kind] = merged;
  return { ...node, appearance };
}
