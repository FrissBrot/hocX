"use client";

// Arbeitsfläche des Visual Designers: Darstellung der Vorlage auf Seiten mit Rändern, Kopf- und
// Fusszeile, Titelseite und Seitenebenen. Verbindlich ist die Typst-Vorschau (preview-panel.tsx);
// die Fläche kommt ihr so nahe wie möglich:
// - Texte, Sichtbarkeiten und Wiederholungen stammen aus derselben Kompilierung wie die Vorschau
//   (canvas-data.ts, compiler.CanvasHints), Fachkomponenten, Tabellen und formatierter Text als
//   gerenderte Ausschnitte (SVG),
// - Schriften sind dieselben Dateien wie im Compile, Abstände folgen den Typst-Regeln
//   (Absatz-/Blockabstand, schwache Abstände der Stapel, siehe spacingBetween),
// - Kopf- und Fusszeile sitzen wie in Typst (header-ascent/footer-descent 30 %), seitenverankerte
//   Ebenen beziehen sich auf die Seitenecke.
// Auswahl per Klick oder Tastatur, Einfügen und Verschieben per Drag-and-drop (dnd-kit) in die
// markierten Zwischenräume.

import { createContext, CSSProperties, KeyboardEvent, ReactNode, useContext, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useDraggable, useDroppable } from "@dnd-kit/core";
import { useTranslations } from "next-intl";

import { BrandView, cssLength, gridTrack, mm, PT_TO_PX, registerDocumentFonts, resolvedBrandView, resolveColor, resolveFont } from "@/components/documents/designer/brand-preview";
import { diagnosticsFor, useDesigner } from "@/components/documents/designer/designer-context";
import { bindingLabel } from "@/components/documents/studio-labels";
import type { CanvasData } from "@/lib/documents/api";
import { Area, BoxStyle, Inline, pageDimensions, TemplateNode, TextContent, TextStyle } from "@/lib/documents/layout";

// Typst setzt Kopf- und Fusszeile um 30 % des Randes in den Rand hinein (header-ascent,
// footer-descent): Kopf endet bei 70 % des oberen Randes, Fuss beginnt 30 % unter dem unteren.
const HEADER_ASCENT = 0.3;
// Seitenzahl auf der Arbeitsfläche (eine Seite je Bereich)
const SAMPLE_PAGE = { page: 1, total: 2 };

export type DropTarget = { area: Area; parentId: string | null; index: number };

export function dropId(target: DropTarget): string {
  return `drop|${target.area}|${target.parentId ?? ""}|${target.index}`;
}

export function parseDropId(id: string): DropTarget | null {
  const [kind, area, parentId, index] = id.split("|");
  if (kind !== "drop") return null;
  return { area: area as Area, parentId: parentId || null, index: Number(index) };
}

// ── Kontext ─────────────────────────────────────────────────────────────────

type CanvasEnv = {
  zoom: number;
  look: BrandView;
  data: CanvasData | null;
  // Nummer je Überschriften-Index (compiler: headings), leer ohne Nummerierung
  numbers: string[];
};

const EnvContext = createContext<CanvasEnv | null>(null);
// Ebene der aktuellen Seite für seitenverankerte Ebenen (Portal)
const PageLayerContext = createContext<HTMLElement | null>(null);

function useEnv(): CanvasEnv {
  const env = useContext(EnvContext);
  if (!env) throw new Error("Arbeitsfläche ohne Kontext"); // i18n-ok: Programmierfehler, kein UI-Text
  return env;
}

const hintKey = (id: string, instance: string) => `${id}@${instance}`;
const childInstance = (instance: string, index: number) => (instance ? `${instance}.${index}` : `${index}`);

/** Nummern "1", "1.2" … wie Typsts heading(numbering: "1.1") für alle Überschriften. */
export function headingNumbers(headings: { level: number }[]): string[] {
  const counts: number[] = [];
  return headings.map((heading) => {
    const level = Math.max(1, heading.level);
    while (counts.length < level) counts.push(0);
    counts.length = level;
    counts[level - 1] += 1;
    return counts.join(".");
  });
}

// ── Abstände wie in Typst ───────────────────────────────────────────────────
//
// Gemessen am Compile (typst/main.typ, layout.typ): zwischen zwei Absätzen gilt der
// Absatzabstand, zwischen Absatz und Block der Abstand des Blocks, zwischen zwei Blöcken der
// grössere. Schwache Abstände (Lücke eines Stapels, Aussenabstand oben/unten) ersetzen diese
// Regeln; mehrere nebeneinander ergeben den grössten. Am Anfang und Ende eines Blocks entfallen
// sie. Ein fester Abstand (Leerraum) kommt immer dazu.

type Edge = { kind: "par" | "block"; above: number; below: number; before: number | null; after: number | null };
type Edges = { first: Edge; last: Edge };

function hasBox(style: BoxStyle | undefined): boolean {
  if (!style) return false;
  const padding = style.padding;
  return (
    (style.width !== undefined && style.width !== "auto") ||
    (style.height !== undefined && style.height !== null) ||
    !!(padding && (padding.top || padding.right || padding.bottom || padding.left)) ||
    !!style.background ||
    !!(style.border && style.border.width > 0)
  );
}

function maxOf(...values: (number | null)[]): number | null {
  const present = values.filter((value): value is number => value !== null);
  return present.length ? Math.max(...present) : null;
}

/** Füllt der Inhalt die verfügbare Breite? Sonst ist ein Kasten mit automatischer Breite in
 * Typst nur so breit wie sein Inhalt. */
function fillsWidth(node: TemplateNode): boolean {
  const width = node.style?.width;
  if (width && width !== "auto") return width === "fill" || width.endsWith("%") || width.endsWith("fr");
  if (node.style?.text?.align && node.style.text.align !== "left") return true;
  switch (node.type) {
    case "row":
      return (node.children ?? []).some((child) => { const value = child.style?.width; return value === "fill" || !!value?.endsWith("fr"); });
    case "grid":
    case "table":
    case "data_block":
    case "toc":
    case "divider":
    case "rich_text":
    case "verify_note":
      return true;
    case "metadata":
      return node.layout !== "inline";
    case "absolute_layer":
      return node.anchor !== "page";
    default:
      return (node.children ?? []).some(fillsWidth);
  }
}

export function spacingBetween(previous: Edge | null, next: Edge, gap: number | null, paragraph: number): number {
  if (!previous) return 0;
  const weak = maxOf(gap, previous.after, next.before);
  if (weak !== null) return weak;
  if (previous.kind === "par" && next.kind === "par") return paragraph;
  if (previous.kind === "par") return next.above;
  if (next.kind === "par") return previous.below;
  return Math.max(previous.below, next.above);
}

type Entry = { node: TemplateNode; index: number; instance: string; ghost: boolean; hidden: boolean };

/** Knoten einer Ebene mit Wiederholungen aufgefaltet (eine Instanz je Datensatz). */
function expand(nodes: TemplateNode[], instance: string, ghost: boolean, data: CanvasData | null): Entry[] {
  const entries: Entry[] = [];
  nodes.forEach((node, index) => {
    const hiddenAt = (path: string) => node.enabled === false || (data ? data.hints.hidden[hintKey(node.id, path)] !== undefined : false);
    if (node.repeat && data) {
      const count = data.hints.repeats[hintKey(node.id, instance)];
      if (count === undefined || count === 0) {
        entries.push({ node, index, instance: childInstance(instance, 0), ghost, hidden: count === 0 || hiddenAt(childInstance(instance, 0)) });
        return;
      }
      for (let item = 0; item < count; item += 1) {
        const path = childInstance(instance, item);
        entries.push({ node, index, instance: path, ghost: ghost || item > 0, hidden: hiddenAt(path) });
      }
      return;
    }
    entries.push({ node, index, instance: node.repeat ? childInstance(instance, 0) : instance, ghost, hidden: hiddenAt(instance) });
  });
  return entries;
}

function headingSize(look: BrandView, level: number): number {
  const typography = look.tokens.typography;
  return [typography.size_h1, typography.size_h2, typography.size_h3][level - 1] ?? typography.base_size;
}

/** Absatzabstand (main.typ: paragraph_gap + 0.4em) in px. */
function paragraphSpacing(env: CanvasEnv): number {
  return mm(env.look.tokens.layout.paragraph_gap, env.zoom) + 0.4 * env.look.tokens.typography.base_size * PT_TO_PX * env.zoom;
}

function headingEdge(env: CanvasEnv, level: number): Edge {
  const gap = mm(env.look.tokens.layout.section_gap, env.zoom);
  return { kind: "block", above: level === 1 ? gap * 1.4 : gap, below: 0.65 * headingSize(env.look, level) * PT_TO_PX * env.zoom, before: null, after: null };
}

/** Erster und letzter Abstand eines Knotens im Fluss; null = nimmt keinen Platz ein. */
function edgesOf(entry: Entry, env: CanvasEnv): Edges | null {
  const { node, instance } = entry;
  if (entry.hidden) return null;
  const style = node.style;
  const before = style?.margin_top ? mm(style.margin_top, env.zoom) : null;
  const after = style?.margin_bottom ? mm(style.margin_bottom, env.zoom) : null;
  // em-Abstände gelten in der Schriftgrösse des Knotens (layout.typ: apply-text umschliesst ihn)
  const base = (style?.text?.size ?? env.look.tokens.typography.base_size) * PT_TO_PX * env.zoom;
  const paragraph = paragraphSpacing(env);
  const single = (edge: Omit<Edge, "before" | "after">): Edges => {
    const value = { ...edge, before, after };
    return { first: value, last: value };
  };
  if (hasBox(style) || (node.keep_together && node.type !== "section")) return single({ kind: "block", above: 0, below: 0 });
  const block = (above: number, below: number) => single({ kind: "block", above, below });
  // Elemente mit Standardabstand (Absatz, Raster, Tabelle, Liste, Linie …) verhalten sich gleich
  const par = () => single({ kind: "par", above: paragraph, below: paragraph });
  switch (node.type) {
    case "stack":
    case "column":
    case "container":
    case "header":
    case "footer":
    case "component_ref": {
      const children = node.type === "component_ref" ? [] : expand(node.children ?? [], instance, entry.ghost, env.data);
      const edges = children.map((child) => edgesOf(child, env)).filter((item): item is Edges => item !== null);
      if (node.type === "component_ref") return par();
      if (!edges.length) return null;
      return { first: { ...edges[0].first, before: maxOf(before, edges[0].first.before) }, last: { ...edges[edges.length - 1].last, after: maxOf(after, edges[edges.length - 1].last.after) } };
    }
    case "section": {
      const children = expand(node.children ?? [], instance, entry.ghost, env.data);
      const edges = children.map((child) => edgesOf(child, env)).filter((item): item is Edges => item !== null);
      const title = node.title ? { ...headingEdge(env, (node.level as number) ?? 1) } : null;
      const first = title ?? edges[0]?.first;
      const last = edges.length ? edges[edges.length - 1].last : title;
      if (!first || !last) return null;
      return { first: { ...first, before: maxOf(before, first.before) }, last: { ...last, after: maxOf(after, last.after) } };
    }
    case "text": {
      const role = (node.role as string) ?? "paragraph";
      if (role === "heading") return single(headingEdge(env, (node.level as number) ?? 1));
      if (role === "title") return block(0, 0.4 * base);
      if (role === "subtitle") return block(0, 0.6 * base);
      return par();
    }
    case "divider":
      return block(0.4 * base, 0.4 * base);
    case "image":
      return block(0, 0);
    case "spacer":
    case "page_break":
    case "watermark":
      return null;
    case "absolute_layer":
      return node.anchor === "page" ? null : par();
    default:
      return par();
  }
}

// ── Bausteine ───────────────────────────────────────────────────────────────

function DropZone({ target, empty, label }: { target: DropTarget; empty?: boolean; label?: string }) {
  const { setNodeRef, isOver, active } = useDroppable({ id: dropId(target) });
  if (!active && !empty) return <div ref={setNodeRef} className="studio-drop-gap" />;
  return (
    <div ref={setNodeRef} className={["studio-drop", isOver ? "studio-drop-over" : "", empty ? "studio-drop-empty" : "", active ? "studio-drop-active" : ""].join(" ")}>
      {empty && label}
    </div>
  );
}

function textCss(text: TextStyle | undefined, env: CanvasEnv): CSSProperties {
  const css: CSSProperties = {};
  if (!text) return css;
  const { zoom, look } = env;
  if (text.font) css.fontFamily = resolveFont(text.font, look);
  if (text.size) css.fontSize = text.size * PT_TO_PX * zoom;
  if (text.weight) css.fontWeight = text.weight === "bold" ? 700 : text.weight === "medium" ? 500 : 400;
  if (text.italic !== undefined && text.italic !== null) css.fontStyle = text.italic ? "italic" : "normal";
  if (text.color) css.color = resolveColor(text.color, look);
  if (text.align) css.textAlign = text.align;
  if (text.line_height) css.lineHeight = text.line_height;
  if (text.letter_spacing) css.letterSpacing = text.letter_spacing * PT_TO_PX * zoom;
  if (text.transform && text.transform !== "none") css.textTransform = text.transform === "upper" ? "uppercase" : "lowercase";
  return css;
}

function boxCss(node: TemplateNode, env: CanvasEnv): CSSProperties {
  const style = node.style;
  if (!style) return {};
  const { zoom, look } = env;
  const css: CSSProperties = textCss(style.text, env);
  // Bilder setzen Breite und Höhe am Bild selbst (layout.typ: image)
  if (node.type !== "image") {
    const width = cssLength(style.width, zoom);
    if (width) css.width = width;
    // Typst: ein Block mit automatischer Breite ist so breit wie sein Inhalt
    else if (hasBox(style) && !fillsWidth(node)) {
      css.width = "fit-content";
      css.maxWidth = "100%";
      css.alignSelf = "flex-start";
    }
    const height = cssLength(style.height ?? undefined, zoom);
    if (height) css.height = height;
  }
  if (style.padding) css.padding = `${mm(style.padding.top, zoom)}px ${mm(style.padding.right, zoom)}px ${mm(style.padding.bottom, zoom)}px ${mm(style.padding.left, zoom)}px`;
  if (style.background) css.background = resolveColor(style.background, look);
  if (style.border && style.border.width > 0) {
    const value = `${style.border.width * PT_TO_PX * zoom}px ${style.border.style} ${resolveColor(style.border.color, look) ?? "currentColor"}`;
    for (const side of style.border.sides ?? ["top", "right", "bottom", "left"]) css[`border${side[0].toUpperCase()}${side.slice(1)}` as "borderTop"] = value;
    // Wie im Compile: ohne sichtbaren Rahmen keine Rundung
    css.borderRadius = mm(style.border.radius, zoom);
  }
  if (style.align === "center") {
    css.marginLeft = "auto";
    css.marginRight = "auto";
  } else if (style.align === "right") css.marginLeft = "auto";
  return css;
}

/** Text einer Vorlage: aufgelöste Werte (Vorschau-Daten) oder Bindungen als Platzhalter. */
function Spans({ content, valueKey }: { content?: TextContent | null; valueKey?: string }) {
  const t = useTranslations("documentStudio");
  const tPdf = useTranslations("documentPdf");
  const { data } = useEnv();
  const values = valueKey && data ? data.hints.texts[valueKey] : undefined;
  if (values?.text !== undefined) return <>{values.text}</>;
  if (!content?.default?.length) return <span className="studio-placeholder">{t("canvas.emptyText")}</span>;
  return (
    <>
      {content.default.map((inline: Inline, index) => {
        if (inline.t === "br") return <br key={index} />;
        const style: CSSProperties = { fontWeight: inline.b ? 700 : undefined, fontStyle: inline.i ? "italic" : undefined };
        const value = values?.inlines?.[index];
        if (inline.t === "text") return <span key={index} style={style}>{inline.v}</span>;
        if (inline.t === "key") return <span key={index} style={style}>{value ?? (tPdf.has(inline.key) ? tPdf(inline.key) : inline.key)}</span>;
        if (typeof value === "string") {
          return value ? (
            <span key={index} className="studio-bound" style={style} title={bindingLabel(t, inline.path)}>
              {value}
            </span>
          ) : null;
        }
        return (
          <span key={index} className="studio-binding-chip" style={style}>
            {bindingLabel(t, inline.path)}
          </span>
        );
      })}
    </>
  );
}

/** Überschrift wie theme.typ: heading-rule (Grösse je Ebene, Stil der ersten Ebene, Nummer). */
function HeadingView({ level, number, color, children }: { level: number; number?: string; color?: string; children: ReactNode }) {
  const { look, zoom } = useEnv();
  const typography = look.tokens.typography;
  const size = headingSize(look, level) * PT_TO_PX * zoom;
  const primary = look.colors.primary;
  const css: CSSProperties = {
    fontFamily: look.headingFont,
    fontSize: size,
    fontWeight: look.weights.heading,
    letterSpacing: typography.letter_spacing_heading * PT_TO_PX * zoom,
    color: color ?? (level === 1 ? look.colors.heading : `color-mix(in srgb, ${look.colors.secondary} 90%, black)`),
    textTransform: typography.heading_transform === "upper" ? "uppercase" : undefined,
  };
  const variant = level > 1 ? "plain" : look.headingLook.variant;
  if (variant === "underline") {
    css.borderBottom = `${0.6 * PT_TO_PX * zoom}px solid color-mix(in srgb, ${primary} 45%, white)`;
    css.paddingBottom = 0.3 * size;
  } else if (variant === "bar") {
    css.borderLeft = `${3 * PT_TO_PX * zoom}px solid ${primary}`;
    css.padding = `${0.15 * size}px 0 ${0.15 * size}px ${0.5 * size}px`;
  } else if (variant === "boxed") {
    css.background = `color-mix(in srgb, ${primary} 12%, white)`;
    css.padding = `${0.35 * size}px ${0.5 * size}px`;
    css.borderRadius = mm(look.headingLook.radius, zoom);
  }
  return (
    <div className="studio-heading studio-text" style={css}>
      {number ? `${number} ` : null}
      {children}
    </div>
  );
}

function snippetFor(node: TemplateNode, instance: string, env: CanvasEnv): ReactNode {
  const url = env.data?.snippets[hintKey(node.id, instance)];
  if (!url) return null;
  const pad = mm(env.data?.snippet_pad ?? 0, env.zoom);
  // eslint-disable-next-line @next/next/no-img-element
  return <img className="studio-node-snippet" src={url} alt="" style={{ marginTop: -pad, marginBottom: -pad }} />;
}

// Tastatur in der Arbeitsfläche wie in einer Baumansicht (STUDIO-016): Pfeil hoch/runter = vorheriger/
// nächster Knoten, rechts = erstes Kind, links = übergeordneter Knoten, Pos1/Ende; Enter/Leertaste wählt.
function moveFocus(event: KeyboardEvent<HTMLElement>): boolean {
  const current = event.currentTarget;
  const tree = current.closest('[role="tree"]');
  if (!tree) return false;
  const items = Array.from(tree.querySelectorAll<HTMLElement>('[role="treeitem"]'));
  const index = items.indexOf(current);
  let target: HTMLElement | null | undefined = null;
  if (event.key === "ArrowDown") target = items[index + 1];
  else if (event.key === "ArrowUp") target = items[index - 1];
  else if (event.key === "Home") target = items[0];
  else if (event.key === "End") target = items[items.length - 1];
  else if (event.key === "ArrowRight") target = items.slice(index + 1).find((item) => item.parentElement?.closest('[role="treeitem"]') === current);
  else if (event.key === "ArrowLeft") target = current.parentElement?.closest<HTMLElement>('[role="treeitem"]');
  else return false;
  event.preventDefault();
  target?.focus();
  return true;
}

// ── Fluss ───────────────────────────────────────────────────────────────────

type FlowProps = { nodes: TemplateNode[]; area: Area; parentId: string | null; instance: string; ghost: boolean; gap: number | null; level: number; styled?: boolean };

/** Kinder eines Stapels bzw. eines Bereichs untereinander, mit Typst-Abständen und Ablagezonen. */
function Flow({ nodes, area, parentId, instance, ghost, gap, level, styled = false }: FlowProps) {
  const t = useTranslations("documentStudio");
  const env = useEnv();
  // Leere gestaltete Container (Farbfläche, Punkt) bleiben wie im PDF leer; Ablage nur beim Ziehen
  if (nodes.length === 0) return ghost ? null : styled ? <DropZone target={{ area, parentId, index: 0 }} /> : <DropZone target={{ area, parentId, index: 0 }} empty label={t("canvas.dropHere")} />;
  const paragraph = paragraphSpacing(env);
  const gapPx = gap === null ? null : mm(gap, env.zoom);
  const result: ReactNode[] = [];
  let previous: Edge | null = null;
  // Ein fester Leerraum ist für die Abstandsregeln durchsichtig; in einem Stapel steht die
  // schwache Lücke aber auch zwischen Leerraum und Nachbarn.
  let afterSpacer = false;
  let zoneIndex = -1;
  for (const entry of expand(nodes, instance, ghost, env.data)) {
    if (!entry.ghost && entry.index !== zoneIndex) {
      zoneIndex = entry.index;
      result.push(<DropZone key={`gap-${entry.index}`} target={{ area, parentId, index: entry.index }} />);
    }
    const key = `${entry.node.id}-${entry.instance}`;
    if (entry.node.type === "spacer" && !entry.hidden) {
      result.push(<NodeView key={key} entry={entry} area={area} level={level} marginTop={(previous || afterSpacer) && gapPx !== null ? gapPx : 0} />);
      afterSpacer = true;
      continue;
    }
    const edges = edgesOf(entry, env);
    let top = 0;
    if (edges) {
      top = previous ? spacingBetween(previous, edges.first, gapPx, paragraph) : afterSpacer && gapPx !== null ? gapPx : 0;
      previous = edges.last;
      afterSpacer = false;
    }
    result.push(<NodeView key={key} entry={entry} area={area} level={level} marginTop={top} />);
  }
  if (!ghost) result.push(<DropZone key="gap-end" target={{ area, parentId, index: nodes.length }} />);
  return <>{result}</>;
}

// ── Knoten ──────────────────────────────────────────────────────────────────

type NodeViewProps = { entry: Entry; area: Area; level: number; marginTop?: number; cell?: boolean };

export function NodeView({ entry, area, level, marginTop = 0, cell = false }: NodeViewProps) {
  const t = useTranslations("documentStudio");
  const tPdf = useTranslations("documentPdf");
  const designer = useDesigner();
  const env = useEnv();
  const pageLayer = useContext(PageLayerContext);
  const { selectedId, select, diagnostics, editable, components } = designer;
  const { node, instance, ghost } = entry;
  const { zoom, look, data } = env;
  const drag = useDraggable({ id: ghost ? `ghost|${node.id}|${instance}` : `node|${node.id}`, disabled: ghost || !editable || node.locked === true, data: { kind: "node", id: node.id } });
  const issues = ghost ? [] : diagnosticsFor(diagnostics, node.id);
  const typography = look.tokens.typography;
  const selected = !ghost && selectedId === node.id;
  const key = hintKey(node.id, instance);
  const label = node.name || t(`nodeType.${node.type}`);
  const hidden = entry.hidden;

  const flow = (gap: number | null) => <Flow nodes={node.children ?? []} area={area} parentId={node.id} instance={instance} ghost={ghost} gap={gap} level={level + 1} styled={hasBox(node.style)} />;
  const cells = () => {
    const items = expand(node.children ?? [], instance, ghost, data);
    const result: ReactNode[] = items.map((child) => <NodeView key={`${child.node.id}-${child.instance}`} entry={child} area={area} level={level + 1} cell />);
    if (!ghost) result.push(<DropZone key="gap-end" target={{ area, parentId: node.id, index: (node.children ?? []).length }} empty={items.length === 0} label={t("canvas.dropHere")} />);
    return { items, nodes: result };
  };

  let body: ReactNode = null;
  if (!hidden || selected) {
    switch (node.type) {
      case "stack":
      case "column":
      case "header":
      case "footer":
      case "container":
        body = (
          <div className="studio-node-stack" role="group">
            {flow((node.gap as number) ?? 3)}
          </div>
        );
        break;
      case "section": {
        const index = data?.hints.heading_index[key];
        const sectionLevel = Math.min((node.level as number) ?? 1, 4);
        const title = node.title ? (
          <HeadingView level={sectionLevel} number={index !== undefined ? env.numbers[index] : undefined}>
            <Spans content={node.title as TextContent} valueKey={key} />
          </HeadingView>
        ) : null;
        const firstChild = expand(node.children ?? [], instance, ghost, data).map((child) => edgesOf(child, env)).find((item) => item !== null);
        const headingBelow = node.title && firstChild ? spacingBetween(headingEdge(env, sectionLevel), firstChild.first, null, paragraphSpacing(env)) : 0;
        body = (
          <div className="studio-node-stack" role="group">
            {title}
            <div className="studio-node-stack" style={{ marginTop: headingBelow }}>
              {flow((node.gap as number) ?? 3)}
            </div>
          </div>
        );
        break;
      }
      case "row": {
        const { items, nodes } = cells();
        body = (
          <div
            className="studio-node-row"
            role="group"
            style={{
              gridTemplateColumns: items.map((child) => gridTrack(child.node.style?.width, zoom)).join(" ") || "1fr",
              columnGap: mm((node.gap as number) ?? 5, zoom),
              alignItems: node.valign === "middle" ? "center" : node.valign === "bottom" ? "end" : "start",
            }}
          >
            {nodes}
          </div>
        );
        break;
      }
      case "grid": {
        const widths = (node.column_widths as string[] | undefined) ?? [];
        const columns = (node.columns as number) ?? 2;
        body = (
          <div className="studio-node-row" role="group" style={{ gridTemplateColumns: widths.length === columns ? widths.map((value) => gridTrack(value, zoom)).join(" ") : `repeat(${columns}, 1fr)`, columnGap: mm((node.gap_x as number) ?? 5, zoom), rowGap: mm((node.gap_y as number) ?? 4, zoom) }}>
            {cells().nodes}
          </div>
        );
        break;
      }
      case "absolute_layer": {
        const items = expand(node.children ?? [], instance, ghost, data).map((child) => (
          <LayerItem key={`${child.node.id}-${child.instance}`} entry={child} area={area} level={level + 1} />
        ));
        if (node.anchor === "page") {
          // Typst: place() relativ zur Seitenecke (compiler: offset = -Ränder)
          body = pageLayer ? createPortal(<div className="studio-page-anchored">{items}</div>, pageLayer) : null;
        } else {
          body = <div className="studio-node-layer" role="group" style={{ height: mm((node.height as number) ?? 60, zoom) }}>{items}</div>;
        }
        break;
      }
      case "text": {
        const role = (node.role as string) ?? "paragraph";
        if (role === "heading") {
          const index = data?.hints.heading_index[key];
          body = (
            <HeadingView level={Math.min((node.level as number) ?? 1, 4)} number={index !== undefined ? env.numbers[index] : undefined}>
              <Spans content={node.content as TextContent} valueKey={key} />
            </HeadingView>
          );
          break;
        }
        const small = typography.size_small * PT_TO_PX * zoom;
        const roleStyle: CSSProperties =
          role === "title" ? { fontFamily: look.headingFont, fontSize: typography.size_title * PT_TO_PX * zoom, fontWeight: look.weights.heading, color: look.colors.heading }
          : role === "subtitle" ? { fontFamily: look.headingFont, fontSize: typography.size_subtitle * PT_TO_PX * zoom, color: look.colors.secondary }
          : role === "caption" ? { fontSize: small, fontStyle: "italic", color: look.colors.muted }
          : role === "label" ? { fontSize: small, fontWeight: 700, color: look.colors.muted }
          : role === "small" ? { fontSize: small }
          : {};
        // Eigene Textstile haben Vorrang vor den Rollen-Standards (layout.typ: text-role)
        const own = textCss(node.style?.text, env);
        for (const property of Object.keys(own)) delete roleStyle[property as keyof CSSProperties];
        body = <div className="studio-text" style={roleStyle}><Spans content={node.content as TextContent} valueKey={key} /></div>;
        break;
      }
      case "rich_text":
        body = snippetFor(node, instance, env) ?? <div className="studio-node-rich studio-text">{(node.markdown as string) || <span className="studio-placeholder">{t("canvas.emptyRichText")}</span>}</div>;
        break;
      case "image":
        body = <ImageView node={node} />;
        break;
      case "divider":
        body = <hr className="studio-node-divider" style={{ borderTopColor: resolveColor(node.color as string, look) ?? look.colors.border, borderTopWidth: Math.max(1, ((node.thickness as number) ?? 0.6) * PT_TO_PX * zoom), borderTopStyle: (node.line_style as "solid") ?? "solid", width: cssLength(node.length as string, zoom) ?? "100%" }} />;
        break;
      case "spacer":
        body = <div className={node.flexible ? "studio-node-spacer studio-node-spacer-flex" : "studio-node-spacer"} style={{ height: node.flexible ? undefined : mm((node.size as number) ?? 6, zoom), minHeight: node.flexible ? mm(4, zoom) : undefined }} />;
        break;
      case "page_break":
        body = <div className="studio-node-pagebreak">{t("canvas.pageBreak")}</div>;
        break;
      case "page_number":
        body = <span className="studio-text">{node.format === "page" ? String(SAMPLE_PAGE.page) : tPdf("page.of", SAMPLE_PAGE)}</span>;
        break;
      case "toc":
        body = <TocView node={node} />;
        break;
      case "qr_code": {
        const size = mm((node.size as number) ?? 22, zoom);
        body = (
          <div>
            <div className="studio-node-qr" style={{ width: size, height: size, borderColor: look.colors.border, color: look.colors.muted }}>QR</div>
          </div>
        );
        break;
      }
      case "verify_note":
        body = <VerifyView node={node} />;
        break;
      case "metadata":
        body = <MetadataView node={node} valueKey={key} />;
        break;
      case "watermark":
        body = (
          <div className="studio-node-watermark" style={{ color: resolveColor(node.color as string, look) ?? look.colors.watermark, fontSize: ((node.size as number) ?? 96) * PT_TO_PX * zoom, transform: `rotate(${(node.angle as number) ?? -35}deg)` }}>
            {tPdf("watermark.draft")}
          </div>
        );
        break;
      case "list":
        body = <ListView node={node} valueKey={key} />;
        break;
      case "table":
        body = snippetFor(node, instance, env) ?? <TableView node={node} />;
        break;
      case "data_block":
        body = snippetFor(node, instance, env) ?? (
          <div className="studio-node-data">
            <span className="studio-node-data-kind">{t("canvas.dataComponent")}</span>
            <span className="studio-node-data-name">{t(`component.${node.component as string}`)}</span>
            {node.title_mode === "custom" && node.title ? <span className="studio-node-data-title"><Spans content={node.title as TextContent} /></span> : null}
          </div>
        );
        break;
      case "component_ref": {
        const component = components.find((item) => item.id === node.component_id);
        body = component ? (
          <div className="studio-node-ref">
            <span className="studio-node-ref-badge">{t("canvas.reusable", { name: component.name })}</span>
            <NodeView entry={{ node: component.node, index: 0, instance, ghost: true, hidden: false }} area={area} level={level + 1} />
          </div>
        ) : (
          <div className="studio-node-placeholder">{t("canvas.componentMissing")}</div>
        );
        break;
      }
      default:
        body = <div className="studio-node-placeholder">{t(`nodeType.${node.type}`)}</div>;
    }
  }

  const style: CSSProperties = { ...boxCss(node, env), marginTop: cell ? 0 : marginTop };
  if (node.type === "spacer" && node.flexible) style.flexGrow = 1;
  const className = [
    "studio-node",
    hidden ? (selected ? "studio-node-hidden-selected" : "studio-node-hidden") : "",
    selected ? "studio-node-selected" : "",
    node.visible_if ? "studio-node-conditional" : "",
    node.repeat ? "studio-node-repeat" : "",
    issues.some((item) => item.severity === "error") ? "studio-node-error" : issues.length ? "studio-node-warning" : "",
    drag.isDragging ? "studio-node-dragging" : "",
    ghost ? "studio-node-ghost" : "",
  ].join(" ");

  if (ghost) {
    // Weitere Instanzen einer Wiederholung: nur Darstellung, ein Klick wählt die Vorlage
    return (
      <div
        className={className}
        style={style}
        aria-hidden="true"
        onClick={(event) => {
          event.stopPropagation();
          select(node.id);
        }}
      >
        {body}
      </div>
    );
  }

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      select(node.id);
      return;
    }
    moveFocus(event);
  };
  const tag = hidden ? `${label} · ${t(node.enabled === false ? "canvas.disabledNode" : "canvas.hiddenNode")}` : label;
  return (
    <div
      ref={drag.setNodeRef}
      role="treeitem"
      // Roving tabindex: nur der gewählte Knoten liegt in der Tab-Reihenfolge, den Einstieg ohne
      // Auswahl übernimmt der Baum (AreaNodes).
      tabIndex={selected ? 0 : -1}
      aria-selected={selected}
      aria-level={level}
      aria-expanded={node.children !== undefined ? true : undefined}
      aria-label={label}
      onKeyDown={onKeyDown}
      onClick={(event) => {
        event.stopPropagation();
        select(node.id);
      }}
      className={className}
      style={hidden && !selected ? { marginTop: 0 } : style}
    >
      {selected && editable && !node.locked && (
        <span className="studio-node-handle" {...drag.listeners} {...drag.attributes} aria-label={t("canvas.dragHandle", { name: label })} role="button">
          ⠿
        </span>
      )}
      {(selected || issues.length > 0) && <span className="studio-node-tag">{tag}{issues.length ? ` · ${t(`diagnosticShort.${issues[0].severity}`)}` : ""}</span>}
      {body}
    </div>
  );
}

/** Element einer Ebene: Rahmen (Position, Grösse, vertikale Ausrichtung, Drehung) wie layout.typ. */
function LayerItem({ entry, area, level }: { entry: Entry; area: Area; level: number }) {
  const { zoom } = useEnv();
  const frame = entry.node.frame;
  const valign = frame?.valign ?? "top";
  return (
    <div
      className="studio-layer-item"
      style={{
        left: mm(frame?.x, zoom),
        top: mm(frame?.y, zoom),
        width: frame?.width ? mm(frame.width, zoom) : undefined,
        height: frame?.height ? mm(frame.height, zoom) : undefined,
        justifyContent: frame?.height && valign !== "top" ? (valign === "bottom" ? "flex-end" : "center") : undefined,
        transform: frame?.rotate ? `rotate(${frame.rotate}deg)` : undefined,
      }}
    >
      <NodeView entry={entry} area={area} level={level} cell />
    </div>
  );
}

function ImageView({ node }: { node: TemplateNode }) {
  const t = useTranslations("documentStudio");
  const tPdf = useTranslations("documentPdf");
  const { assets, content } = useDesigner();
  const { zoom, look } = useEnv();
  const source = node.source as { kind: string; asset_id?: string | null; path?: string } | undefined;
  let url: string | null = null;
  if (source?.kind === "asset" && source.asset_id) url = assets.find((asset) => asset.id === source.asset_id)?.content_url ?? null;
  if (source?.kind === "binding" && source.path?.startsWith("brand.")) {
    const key = source.path.slice(6) as keyof typeof look.tokens.assets;
    const assetId = key === "logo" && content.settings.brand_overrides.logo_asset_id ? content.settings.brand_overrides.logo_asset_id : (look.tokens.assets[key] as string | null);
    url = assets.find((asset) => asset.id === assetId)?.content_url ?? null;
  }
  const width = cssLength(node.style?.width, zoom);
  const height = cssLength(node.style?.height ?? undefined, zoom);
  const fit = (node.fit as string) ?? "contain";
  const caption = node.caption as TextContent | undefined;
  return (
    <>
      {url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img className="studio-node-image" src={url} alt="" style={{ width: width ?? (height ? "auto" : undefined), height: height ?? "auto", objectFit: width && height ? (fit === "stretch" ? "fill" : (fit as "contain")) : undefined }} />
      ) : (
        <div className="studio-node-placeholder" style={{ width: width ?? mm(40, zoom), height: height ?? mm(20, zoom), color: look.colors.muted }}>
          {source?.kind === "binding" ? `${tPdf("label.imageMissing")} · ${bindingLabel(t, source.path ?? "")}` : t("canvas.noImage")}
        </div>
      )}
      {caption?.default?.length ? (
        <div className="studio-text studio-node-caption" style={{ color: look.colors.muted }}>
          <Spans content={caption} />
        </div>
      ) : null}
    </>
  );
}

function TocView({ node }: { node: TemplateNode }) {
  const tPdf = useTranslations("documentPdf");
  const env = useEnv();
  const { look, zoom, data } = env;
  const density = (node.density as string) ?? "normal";
  const spacing = { normal: { size: 1, above: 0.7 }, compact: { size: 0.85, above: 0.35 }, very_compact: { size: 0.8, above: 0.28 } }[density] ?? { size: 1, above: 0.7 };
  const depth = (node.depth as number) ?? 2;
  const size = look.tokens.typography.base_size * spacing.size * PT_TO_PX * zoom;
  const headings = (data?.hints.headings ?? []).map((heading, index) => ({ ...heading, number: env.numbers[index] })).filter((heading) => heading.outlined && heading.level <= depth);
  const titleGap = headingEdge(env, 1).below;
  return (
    <div className="studio-node-toc">
      {node.show_title !== false && (
        <HeadingView level={1} color={look.colors.primary}>
          {tPdf("toc.title")}
        </HeadingView>
      )}
      <div className="studio-toc-entries" style={{ fontSize: size, marginTop: node.show_title !== false ? titleGap : 0, rowGap: spacing.above * size }}>
        {data ? (
          headings.map((heading, index) => (
            <div key={index} className="studio-toc-entry" style={{ paddingLeft: (heading.level - 1) * 1.5 * size }}>
              {heading.number ? <span className="studio-text">{heading.number}</span> : null}
              <span className="studio-text">{heading.text}</span>
              <span className="studio-toc-fill" />
            </div>
          ))
        ) : (
          <>
            <div className="studio-toc-line" />
            <div className="studio-toc-line studio-toc-line-indent" />
            <div className="studio-toc-line" />
          </>
        )}
      </div>
    </div>
  );
}

function MetadataView({ node, valueKey }: { node: TemplateNode; valueKey: string }) {
  const t = useTranslations("documentStudio");
  const { data } = useEnv();
  const rows = (data?.hints.rows[valueKey] as string[][] | undefined) ?? ((node.fields as string[]) ?? ["number", "date", "status", "version"]).map((field) => [t(`metadataField.${field}`), ""]);
  if (node.layout === "inline") {
    return (
      <div className="studio-text">
        {rows.map(([label, value], index) => (
          <span key={index}>
            {index > 0 ? " · " : null}
            <strong>{label}:</strong> {value || <span className="studio-binding-chip">{label}</span>}
          </span>
        ))}
      </div>
    );
  }
  return (
    <div className="studio-node-meta">
      {rows.map(([label, value], index) => (
        <div key={index} className="studio-node-meta-row">
          <strong className="studio-text">{label}</strong>
          <span className="studio-text">{value || <span className="studio-binding-chip">{label}</span>}</span>
        </div>
      ))}
    </div>
  );
}

function ListView({ node, valueKey }: { node: TemplateNode; valueKey: string }) {
  const t = useTranslations("documentStudio");
  const { data, look } = useEnv();
  const resolved = data?.hints.rows[valueKey] as string[] | undefined;
  const marker = (node.marker as string) ?? "bullet";
  const items: ReactNode[] = resolved ?? (node.source ? [<Spans key="a" content={node.item as TextContent} />, <Spans key="b" content={node.item as TextContent} />] : ((node.items as string[]) ?? []).map((item) => item || <span className="studio-placeholder">{t("canvas.emptyItem")}</span>));
  // Zeilenabstand der Einträge wie ein enger Typst-Absatz (leading = Zeilenhöhe - 0.7em)
  const leading = Math.max(look.tokens.typography.line_height - 0.7, 0.1);
  return (
    <div className="studio-node-list" style={{ rowGap: `${leading}em` }}>
      {items.map((item, index) => (
        <div key={index} className="studio-node-list-item">
          <span className="studio-text">{marker === "number" ? `${index + 1}.` : marker === "none" ? "" : "•"}</span>
          <span className="studio-text">{item}</span>
        </div>
      ))}
    </div>
  );
}

function TableView({ node }: { node: TemplateNode }) {
  const { look, zoom } = useEnv();
  const columns = (node.columns as { id: string; header?: TextContent; cell?: TextContent; width?: string; align?: string }[]) ?? [];
  const rows = node.source ? [0, 1] : ((node.rows as string[][]) ?? []);
  return (
    <table className="studio-node-table">
      <thead>
        <tr style={{ background: look.colors.table_header_background, color: look.colors.table_header_text }}>
          {columns.map((column) => <th key={column.id} style={{ width: column.width && column.width !== "auto" ? cssLength(column.width, zoom) : undefined, textAlign: (column.align as "left") ?? "left" }}><Spans content={column.header} /></th>)}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, rowIndex) => (
          <tr key={rowIndex}>
            {columns.map((column, columnIndex) => (
              <td key={column.id} style={{ textAlign: (column.align as "left") ?? "left" }}>
                {node.source ? <Spans content={column.cell} /> : (row as string[])[columnIndex] ?? ""}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function VerifyView({ node }: { node: TemplateNode }) {
  const tPdf = useTranslations("documentPdf");
  const { look, zoom } = useEnv();
  const text = tPdf("verify.urlAndId", { url: "verify.hocx.ch", id: tPdf("verify.previewId") });
  const qr = node.show_qr !== false;
  return (
    <div className="studio-node-verify" style={{ color: look.colors.muted }}>
      {qr && <div className="studio-node-qr" style={{ width: mm(16, zoom), height: mm(16, zoom), borderColor: look.colors.border }}>QR</div>}
      <span className="studio-text">{text}</span>
    </div>
  );
}

// ── Bereiche und Seiten ─────────────────────────────────────────────────────

function containsNode(nodes: TemplateNode[], id: string | null): boolean {
  if (!id) return false;
  return nodes.some((node) => node.id === id || containsNode(node.children ?? [], id));
}

function AreaNodes({ area, nodes, emptyLabel, label, gap = null }: { area: Area; nodes: TemplateNode[]; emptyLabel: string; label: string; gap?: number | null }) {
  const { selectedId } = useDesigner();
  if (nodes.length === 0) return <DropZone target={{ area, parentId: null, index: 0 }} empty label={emptyLabel} />;
  // Ein Baum je Bereich (STUDIO-016): ohne Auswahl ist der Baum selbst das Tab-Ziel und gibt den
  // Fokus an den ersten Knoten weiter.
  const hasSelection = containsNode(nodes, selectedId);
  return (
    <div
      role="tree"
      aria-label={label}
      tabIndex={hasSelection ? -1 : 0}
      className="studio-node-tree"
      onFocus={(event) => {
        if (event.target === event.currentTarget) event.currentTarget.querySelector<HTMLElement>('[role="treeitem"]')?.focus();
      }}
    >
      <Flow nodes={nodes} area={area} parentId={null} instance="" ghost={false} gap={gap} level={1} />
    </div>
  );
}

/** Seite mit eigener Ebene für seitenverankerte Elemente (Portal-Ziel). */
function Page({ className, style, children, background }: { className: string; style: CSSProperties; children: ReactNode; background?: ReactNode }) {
  const [layer, setLayer] = useState<HTMLDivElement | null>(null);
  // Die Ebene liegt vor dem Inhalt: wie in Typst zeichnet der Fluss über platzierte Elemente
  return (
    <div className={className} style={style}>
      <div ref={setLayer} className="studio-page-layer" />
      <PageLayerContext.Provider value={layer}>
        {background}
        {children}
      </PageLayerContext.Provider>
    </div>
  );
}

export function Canvas({ zoom }: { zoom: number }) {
  const t = useTranslations("documentStudio");
  const { content, brand, assets, select, activeArea, setActiveArea, canvasData } = useDesigner();
  const look = useMemo(() => (canvasData ? resolvedBrandView(canvasData.brand, brand) : brand), [canvasData, brand]);
  const env = useMemo<CanvasEnv>(
    () => ({ zoom, look, data: canvasData, numbers: canvasData?.numbering ? headingNumbers(canvasData.hints.headings) : [] }),
    [zoom, look, canvasData]
  );
  const fontKey = canvasData ? [...canvasData.brand.fonts.body, ...canvasData.brand.fonts.heading].join("|") : "";
  useEffect(() => {
    if (canvasData) registerDocumentFonts([...new Set([...canvasData.brand.fonts.body, ...canvasData.brand.fonts.heading])], assets);
    // Nur bei geänderten Schriften neu registrieren
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fontKey, assets]);

  const master = content.masters.find((item) => item.id === content.settings.default_master) ?? content.masters[0];
  const [widthMm, heightMm] = pageDimensions(content.page, master?.orientation);
  const margins = master?.margins ?? content.page.margins;
  const titleMaster = content.title_page.master ? content.masters.find((item) => item.id === content.title_page.master) : null;
  const titleMargins = titleMaster?.margins ?? margins;
  const pageStyle: CSSProperties = {
    width: mm(widthMm, zoom),
    minHeight: mm(heightMm, zoom),
    fontFamily: look.bodyFont,
    fontSize: look.tokens.typography.base_size * PT_TO_PX * zoom,
    fontWeight: look.weights.body,
    lineHeight: look.tokens.typography.line_height,
    color: look.colors.text,
    background: look.colors.background,
    textAlign: content.settings.justify ? "justify" : undefined,
    hyphens: content.settings.hyphenate ? "auto" : undefined,
  };
  const padding = (value: typeof margins) => `${mm(value.top, zoom)}px ${mm(value.right, zoom)}px ${mm(value.bottom, zoom)}px ${mm(value.left, zoom)}px`;
  const titlePage = content.title_page;
  const autoVerify = content.settings.auto_verify_note && !content.body.some(function hasVerify(node: TemplateNode): boolean {
    return node.type === "verify_note" || (node.children ?? []).some(hasVerify);
  });
  const titleHidden = canvasData !== null && titlePage.enabled && titlePage.visible_if != null && canvasData.hints.hidden["title_page@"] !== undefined;
  // Bereichsbeschriftungen stehen links neben der Seite; der Inhaltsbereich beginnt unter dem oberen Rand.
  const areaButton = (area: Area, label: string, style?: CSSProperties) => (
    <button type="button" style={style} className={activeArea === area ? "studio-area-label studio-area-label-active" : "studio-area-label"} onClick={(event) => { event.stopPropagation(); setActiveArea(area); select(null); }}>
      {label}
    </button>
  );
  const slots = (pageMaster: typeof master, pageMargins: typeof margins) =>
    pageMaster && (
      <>
        <div className="studio-page-header" style={{ height: mm(pageMargins.top * (1 - HEADER_ASCENT), zoom), paddingLeft: mm(pageMargins.left, zoom), paddingRight: mm(pageMargins.right, zoom) }}>
          {areaButton(`master:${pageMaster.id}:header`, t("canvas.header"))}
          <div className="studio-page-slot">
            <AreaNodes area={`master:${pageMaster.id}:header`} nodes={pageMaster.header?.children ?? []} gap={(pageMaster.header?.gap as number) ?? 3} emptyLabel={t("canvas.dropHeader")} label={t("canvas.header")} />
          </div>
        </div>
        <div className="studio-page-footer" style={{ height: mm(pageMargins.bottom * (1 - HEADER_ASCENT), zoom), paddingLeft: mm(pageMargins.left, zoom), paddingRight: mm(pageMargins.right, zoom) }}>
          {areaButton(`master:${pageMaster.id}:footer`, t("canvas.footer"))}
          <div className="studio-page-slot">
            <AreaNodes area={`master:${pageMaster.id}:footer`} nodes={pageMaster.footer?.children ?? []} gap={(pageMaster.footer?.gap as number) ?? 3} emptyLabel={t("canvas.dropFooter")} label={t("canvas.footer")} />
          </div>
        </div>
      </>
    );
  const background = (pageMaster: typeof master) =>
    pageMaster && (pageMaster.background?.length ?? 0) > 0 ? (
      <div className="studio-page-background">
        <AreaNodes area={`master:${pageMaster.id}:background`} nodes={pageMaster.background ?? []} emptyLabel="" label={t("canvas.background")} />
      </div>
    ) : null;

  return (
    <EnvContext.Provider value={env}>
      <div className="studio-canvas" onClick={() => select(null)} lang={content.settings.language ?? undefined}>
        {titlePage.enabled && (
          <Page className={titleHidden ? "studio-page studio-page-title studio-page-hidden" : "studio-page studio-page-title"} style={{ ...pageStyle, height: mm(heightMm, zoom), background: resolveColor(titlePage.background, look) ?? pageStyle.background }} background={titleMaster ? background(titleMaster) : null}>
            {areaButton("title_page", titlePage.visible_if ? t("canvas.titlePageConditional") : t("canvas.titlePage"))}
            {titleMaster ? slots(titleMaster, titleMargins) : null}
            <div className="studio-page-content" style={{ padding: padding(titleMargins), minHeight: mm(heightMm, zoom) }}>
              <AreaNodes area="title_page" nodes={titlePage.children} emptyLabel={t("canvas.dropTitlePage")} label={t("canvas.titlePage")} />
            </div>
          </Page>
        )}
        <Page className="studio-page" style={pageStyle} background={background(master)}>
          <div className="studio-page-margins" style={{ top: mm(margins.top, zoom), right: mm(margins.right, zoom), bottom: mm(margins.bottom, zoom), left: mm(margins.left, zoom) }} aria-hidden="true" />
          {slots(master, margins)}
          <div
            className={content.page.columns > 1 ? "studio-page-content studio-page-content-columns" : "studio-page-content"}
            style={{ padding: padding(margins), minHeight: mm(heightMm, zoom), columnCount: content.page.columns > 1 ? content.page.columns : undefined, columnGap: mm(content.page.column_gap, zoom) }}
          >
            {areaButton("body", t("canvas.body"), { top: mm(margins.top, zoom) })}
            <AreaNodes area="body" nodes={content.body} emptyLabel={t("canvas.dropBody")} label={t("canvas.body")} />
            {autoVerify && (
              // Automatischer Prüfvermerk am Ende der letzten Seite (main.typ: verify.auto)
              <div className="studio-auto-verify" aria-hidden="true">
                <VerifyView node={{ id: "auto-verify", type: "verify_note", show_qr: look.tokens.verify?.show_qr !== false }} />
              </div>
            )}
          </div>
        </Page>
        <p className="studio-canvas-hint">{t("canvas.approximateHint")}</p>
      </div>
    </EnvContext.Provider>
  );
}
