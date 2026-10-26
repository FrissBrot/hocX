// Layoutbaum des Document Studio (Spiegel von backend/app/documents/layout.py) und reine
// Baum-Operationen für den Visual Designer. Alle Operationen sind unveränderlich (neue
// Objekte), damit Undo/Redo und Autosave einfache Schnappschüsse vergleichen können.

export type Spacing = { top: number; right: number; bottom: number; left: number };

export type TextStyle = {
  font?: string | null;
  size?: number | null;
  weight?: "regular" | "medium" | "bold" | null;
  italic?: boolean | null;
  color?: string | null;
  align?: "left" | "center" | "right" | "justify" | null;
  line_height?: number | null;
  letter_spacing?: number | null;
  transform?: "none" | "upper" | "lower" | null;
};

export type Border = { width: number; color: string; style: "solid" | "dashed" | "dotted"; sides: ("top" | "right" | "bottom" | "left")[]; radius: number };

export type BoxStyle = {
  width?: string;
  height?: string | null;
  padding?: Spacing;
  margin_top?: number;
  margin_bottom?: number;
  background?: string | null;
  border?: Border | null;
  align?: "left" | "center" | "right";
  text?: TextStyle;
};

export type FormatSpec = { date?: "short" | "long" | "weekday" | "month_year" | "year"; number?: "integer" | "decimal" | "percent" | "amount"; transform?: "none" | "upper" | "lower"; prefix?: string; suffix?: string };

export type Inline =
  | { t: "text"; v: string; b?: boolean; i?: boolean }
  | { t: "bind"; path: string; format?: FormatSpec; fallback?: string; b?: boolean; i?: boolean }
  | { t: "key"; key: string; b?: boolean; i?: boolean }
  | { t: "br" };

export type TextContent = { default: Inline[]; translations?: Record<string, Inline[]> };

export type Condition =
  | { op: "exists" | "empty"; path: string }
  | { op: "eq" | "ne" | "gt" | "gte" | "lt" | "lte" | "contains"; path: string; value: string | number | boolean | null }
  | { op: "in" | "not_in"; path: string; values: (string | number | boolean | null)[] }
  | { op: "count"; path: string; cmp: "eq" | "ne" | "gt" | "gte" | "lt" | "lte"; value: number }
  | { op: "all" | "any"; items: Condition[] }
  | { op: "not"; item: Condition };

export type Frame = { x: number; y: number; width?: number | null; height?: number | null; rotate?: number; opacity?: number; valign?: "top" | "middle" | "bottom" };

export type TemplateNode = {
  id: string;
  type: string;
  name?: string | null;
  style?: BoxStyle;
  enabled?: boolean;
  visible_if?: Condition | null;
  keep_together?: boolean;
  break_before?: boolean;
  repeat?: { source: string; limit?: number; empty_text?: string | null } | null;
  frame?: Frame | null;
  locked?: boolean;
  children?: TemplateNode[];
  // typabhängige Felder
  [key: string]: unknown;
};

export type PageMaster = { id: string; name?: string; header?: TemplateNode | null; footer?: TemplateNode | null; background?: TemplateNode[]; orientation?: "portrait" | "landscape" | null; margins?: Spacing | null };

export type PageSetup = { size: "A3" | "A4" | "A5" | "Letter" | "Legal" | "custom"; width: number; height: number; orientation: "portrait" | "landscape"; margins: Spacing; columns: number; column_gap: number };

export type BrandOverrides = {
  primary?: string | null;
  secondary?: string | null;
  accent?: string | null;
  heading?: string | null;
  logo_asset_id?: string | null;
  body_font?: string | null;
  heading_font?: string | null;
  base_size?: number | null;
};

export type TemplateSettings = {
  first_page_master: string | null;
  default_master: string;
  heading_numbering: boolean | null;
  justify: boolean;
  hyphenate: boolean;
  language: string | null;
  auto_verify_note: boolean;
  brand_overrides: BrandOverrides;
};

export type TemplateContent = {
  schema_version: number;
  page: PageSetup;
  masters: PageMaster[];
  title_page: { enabled: boolean; visible_if?: Condition | null; master: string | null; background: string | null; children: TemplateNode[] };
  body: TemplateNode[];
  settings: TemplateSettings;
};

// Brand-Profil (backend/app/documents/brand.py), für Formulare im Brand Studio
/** Übersteuerung einer Elementart (Brand-Profil oder einzelner Block im Designer). */
export type ElementAppearance = { variant?: string | null; corners?: "square" | "rounded" | null };
export type AppearanceOverrides = Record<string, ElementAppearance>;

export type BrandTokens = {
  derive_colors?: boolean;
  appearance?: { base: string; elements: AppearanceOverrides };
  colors: Record<string, string> & { custom: { key: string; label: string; value: string }[] };
  typography: {
    body: { builtin: string | null; asset_ids: string[] };
    heading: { builtin: string | null; asset_ids: string[] };
    fallbacks: string[];
    base_size: number;
    size_title: number;
    size_subtitle: number;
    size_h1: number;
    size_h2: number;
    size_h3: number;
    size_small: number;
    weight_body: "regular" | "medium";
    weight_heading: "medium" | "bold";
    line_height: number;
    letter_spacing_heading: number;
    heading_transform: "none" | "upper";
  };
  assets: { logo: string | null; logo_alt: string | null; letterhead: string | null; background: string | null; watermark: string | null; footer_image: string | null; images: { key: string; label: string; asset_id: string }[] };
  layout: {
    page_size: "A4" | "A5" | "Letter";
    orientation: "portrait" | "landscape";
    margins: Spacing;
    paragraph_gap: number;
    section_gap: number;
    heading_style: "plain" | "underline" | "bar" | "boxed";
    table_style: "lines" | "grid" | "zebra" | "minimal";
    border_width: number;
    radius: number;
    header_footer: Record<string, boolean | string>;
    title_page: boolean;
    toc: boolean;
    heading_numbering: boolean;
    heading_number_style: "plain" | "accent" | "badge" | "paragraph";
    responsible_display: "title" | "right" | "below";
    empty_blocks: "note" | "hide";
    show_metadata: boolean;
    watermark_draft: boolean;
  };
  organization: { name: string; address: string; contact: string; website: string; place: string };
  verify: { show_url: boolean; show_id: boolean; show_qr: boolean };
};

export type Area = "body" | "title_page" | `master:${string}:header` | `master:${string}:footer` | `master:${string}:background`;

// ── IDs ────────────────────────────────────────────────────────────────────

export function newNodeId(): string {
  const random = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID().replace(/-/g, "") : Math.random().toString(16).slice(2) + Date.now().toString(16);
  return random.slice(0, 12);
}

/** Tiefe Kopie mit neuen IDs (Einfügen aus der Bibliothek, Duplizieren). */
export function withFreshIds<T extends Partial<TemplateNode>>(node: T): TemplateNode {
  const copy = structuredClone(node) as TemplateNode;
  const walk = (item: TemplateNode) => {
    item.id = newNodeId();
    if (Array.isArray(item.columns)) {
      item.columns = (item.columns as { id?: string }[]).map((column) => ({ ...column, id: newNodeId() }));
    }
    for (const child of item.children ?? []) walk(child);
  };
  walk(copy);
  return copy;
}

// ── Bereiche ───────────────────────────────────────────────────────────────

export function areaNodes(content: TemplateContent, area: Area): TemplateNode[] {
  if (area === "body") return content.body;
  if (area === "title_page") return content.title_page.children;
  const [, masterId, slot] = area.split(":");
  const master = content.masters.find((item) => item.id === masterId);
  if (!master) return [];
  if (slot === "background") return master.background ?? [];
  const holder = slot === "header" ? master.header : master.footer;
  return holder?.children ?? [];
}

export function withAreaNodes(content: TemplateContent, area: Area, nodes: TemplateNode[]): TemplateContent {
  if (area === "body") return { ...content, body: nodes };
  if (area === "title_page") return { ...content, title_page: { ...content.title_page, children: nodes } };
  const [, masterId, slot] = area.split(":");
  return {
    ...content,
    masters: content.masters.map((master) => {
      if (master.id !== masterId) return master;
      if (slot === "background") return { ...master, background: nodes };
      const key = slot === "header" ? "header" : "footer";
      const holder = master[key] ?? { id: newNodeId(), type: key, children: [] };
      return { ...master, [key]: { ...holder, children: nodes } };
    }),
  };
}

export function allAreas(content: TemplateContent): Area[] {
  const areas: Area[] = ["body", "title_page"];
  for (const master of content.masters) areas.push(`master:${master.id}:header`, `master:${master.id}:footer`, `master:${master.id}:background`);
  return areas;
}

// ── Suchen ─────────────────────────────────────────────────────────────────

export type NodeLocation = { area: Area; parentId: string | null; index: number; node: TemplateNode; depth: number };

export function locate(content: TemplateContent, id: string): NodeLocation | null {
  for (const area of allAreas(content)) {
    const found = locateIn(areaNodes(content, area), id, null, 0);
    if (found) return { ...found, area };
  }
  return null;
}

function locateIn(nodes: TemplateNode[], id: string, parentId: string | null, depth: number): Omit<NodeLocation, "area"> | null {
  for (let index = 0; index < nodes.length; index += 1) {
    const node = nodes[index];
    if (node.id === id) return { parentId, index, node, depth };
    if (node.children?.length) {
      const found = locateIn(node.children, id, node.id, depth + 1);
      if (found) return found;
    }
  }
  return null;
}

export function walkNodes(nodes: TemplateNode[], visit: (node: TemplateNode, depth: number, parent: TemplateNode | null) => void, depth = 0, parent: TemplateNode | null = null) {
  for (const node of nodes) {
    visit(node, depth, parent);
    if (node.children?.length) walkNodes(node.children, visit, depth + 1, node);
  }
}

export function isAncestor(content: TemplateContent, ancestorId: string, nodeId: string): boolean {
  const ancestor = locate(content, ancestorId)?.node;
  if (!ancestor) return false;
  let found = false;
  walkNodes(ancestor.children ?? [], (node) => {
    if (node.id === nodeId) found = true;
  });
  return found;
}

// ── Ändern ─────────────────────────────────────────────────────────────────

function mapNodes(nodes: TemplateNode[], id: string, update: (node: TemplateNode) => TemplateNode | null): TemplateNode[] {
  const result: TemplateNode[] = [];
  for (const node of nodes) {
    if (node.id === id) {
      const next = update(node);
      if (next) result.push(next);
      continue;
    }
    result.push(node.children ? { ...node, children: mapNodes(node.children, id, update) } : node);
  }
  return result;
}

export function updateNode(content: TemplateContent, id: string, patch: Partial<TemplateNode> | ((node: TemplateNode) => TemplateNode)): TemplateContent {
  const location = locate(content, id);
  if (!location) return content;
  const nodes = mapNodes(areaNodes(content, location.area), id, (node) => (typeof patch === "function" ? patch(node) : { ...node, ...patch }));
  return withAreaNodes(content, location.area, nodes);
}

export function removeNode(content: TemplateContent, id: string): TemplateContent {
  const location = locate(content, id);
  if (!location || location.node.locked) return content;
  return withAreaNodes(content, location.area, mapNodes(areaNodes(content, location.area), id, () => null));
}

/** Knoten einfügen: in ``parentId`` (Container) an ``index`` bzw. auf oberster Ebene des Bereichs. */
export function insertNode(content: TemplateContent, area: Area, parentId: string | null, index: number, node: TemplateNode): TemplateContent {
  if (!parentId) {
    const nodes = [...areaNodes(content, area)];
    nodes.splice(Math.max(0, Math.min(index, nodes.length)), 0, node);
    return withAreaNodes(content, area, nodes);
  }
  return updateNode(content, parentId, (parent) => {
    const children = [...(parent.children ?? [])];
    children.splice(Math.max(0, Math.min(index, children.length)), 0, node);
    return { ...parent, children };
  });
}

export function moveNode(content: TemplateContent, id: string, area: Area, parentId: string | null, index: number): TemplateContent {
  const location = locate(content, id);
  if (!location || id === parentId || (parentId && isAncestor(content, id, parentId))) return content;
  let targetIndex = index;
  if (location.area === area && location.parentId === parentId && location.index < index) targetIndex -= 1;
  const without = withAreaNodes(content, location.area, mapNodes(areaNodes(content, location.area), id, () => null));
  return insertNode(without, area, parentId, targetIndex, location.node);
}

export function duplicateNode(content: TemplateContent, id: string): { content: TemplateContent; newId: string | null } {
  const location = locate(content, id);
  if (!location) return { content, newId: null };
  const copy = withFreshIds(location.node);
  copy.locked = false;
  return { content: insertNode(content, location.area, location.parentId, location.index + 1, copy), newId: copy.id };
}

export function moveWithinParent(content: TemplateContent, id: string, delta: -1 | 1): TemplateContent {
  const location = locate(content, id);
  if (!location) return content;
  const siblings = location.parentId ? locate(content, location.parentId)?.node.children ?? [] : areaNodes(content, location.area);
  const target = location.index + delta;
  if (target < 0 || target >= siblings.length) return content;
  return moveNode(content, id, location.area, location.parentId, delta > 0 ? target + 1 : target);
}

// ── Texte ──────────────────────────────────────────────────────────────────

export function plainText(value: string): TextContent {
  return { default: [{ t: "text", v: value }] };
}

/** Lesbarer Kurztext eines Knotens (Ebenenansicht, Vorschau). */
export function inlineSummary(content: TextContent | undefined | null, resolveKey: (key: string) => string, resolveBinding: (path: string) => string): string {
  if (!content) return "";
  return content.default
    .map((inline) => {
      if (inline.t === "text") return inline.v;
      if (inline.t === "key") return resolveKey(inline.key);
      if (inline.t === "bind") return `[${resolveBinding(inline.path)}]`;
      return " ";
    })
    .join("")
    .trim();
}

export function countNodes(content: TemplateContent): number {
  let count = 0;
  for (const area of allAreas(content)) walkNodes(areaNodes(content, area), () => (count += 1));
  return count;
}

/** Repeat-Kontext eines Knotens: die nächste Listenbindung oberhalb (für item.*-Felder). */
export function repeatScope(content: TemplateContent, id: string): string | null {
  const location = locate(content, id);
  if (!location) return null;
  if (location.node.repeat?.source) return location.node.repeat.source;
  let parentId = location.parentId;
  while (parentId) {
    const parent = locate(content, parentId);
    if (!parent) break;
    if (parent.node.repeat?.source) return parent.node.repeat.source;
    parentId = parent.parentId;
  }
  return null;
}

export const PAPER_SIZES_MM: Record<string, [number, number]> = { A3: [297, 420], A4: [210, 297], A5: [148, 210], Letter: [215.9, 279.4], Legal: [215.9, 355.6] };

export function pageDimensions(page: PageSetup, orientationOverride?: "portrait" | "landscape" | null): [number, number] {
  const [rawW, rawH] = page.size === "custom" ? [page.width, page.height] : PAPER_SIZES_MM[page.size] ?? [210, 297];
  const orientation = orientationOverride ?? page.orientation;
  return orientation === "landscape" ? [Math.max(rawW, rawH), Math.min(rawW, rawH)] : [Math.min(rawW, rawH), Math.max(rawW, rawH)];
}
