"use client";

// Arbeitsfläche des Visual Designers: angenäherte Darstellung der Vorlage auf Seiten mit
// Rändern, Kopf- und Fusszeile, Titelseite und Hilfslinien für Seitenumbrüche. Verbindlich ist
// die Typst-Vorschau (preview-panel.tsx). Auswahl per Klick oder Tastatur, Einfügen und
// Verschieben per Drag-and-drop (dnd-kit) in die markierten Zwischenräume.

import { CSSProperties, KeyboardEvent, ReactNode } from "react";
import { useDraggable, useDroppable } from "@dnd-kit/core";
import { useTranslations } from "next-intl";

import { cssLength, gridTrack, mm, resolveColor, resolveFont } from "@/components/documents/designer/brand-preview";
import { diagnosticsFor, useDesigner } from "@/components/documents/designer/designer-context";
import { bindingLabel } from "@/components/documents/studio-labels";
import { Area, BoxStyle, Inline, pageDimensions, TemplateNode, TextContent } from "@/lib/documents/layout";

const PT_TO_PX = 96 / 72;

export type DropTarget = { area: Area; parentId: string | null; index: number };

export function dropId(target: DropTarget): string {
  return `drop|${target.area}|${target.parentId ?? ""}|${target.index}`;
}

export function parseDropId(id: string): DropTarget | null {
  const [kind, area, parentId, index] = id.split("|");
  if (kind !== "drop") return null;
  return { area: area as Area, parentId: parentId || null, index: Number(index) };
}

function DropZone({ target, empty, label }: { target: DropTarget; empty?: boolean; label?: string }) {
  const { setNodeRef, isOver, active } = useDroppable({ id: dropId(target) });
  if (!active && !empty) return <div ref={setNodeRef} className="studio-drop-gap" />;
  return (
    <div ref={setNodeRef} className={["studio-drop", isOver ? "studio-drop-over" : "", empty ? "studio-drop-empty" : "", active ? "studio-drop-active" : ""].join(" ")}>
      {empty && label}
    </div>
  );
}

function boxStyle(style: BoxStyle | undefined, zoom: number, resolve: (ref?: string | null) => string | undefined, font: (ref?: string | null) => string | undefined): CSSProperties {
  if (!style) return {};
  const css: CSSProperties = {};
  const width = cssLength(style.width, zoom);
  if (width) css.width = width;
  const height = cssLength(style.height ?? undefined, zoom);
  if (height) css.minHeight = height;
  if (style.padding) css.padding = `${mm(style.padding.top, zoom)}px ${mm(style.padding.right, zoom)}px ${mm(style.padding.bottom, zoom)}px ${mm(style.padding.left, zoom)}px`;
  if (style.margin_top) css.marginTop = mm(style.margin_top, zoom);
  if (style.margin_bottom) css.marginBottom = mm(style.margin_bottom, zoom);
  if (style.background) css.background = resolve(style.background);
  if (style.border && style.border.width > 0) {
    const value = `${style.border.width * PT_TO_PX * zoom}px ${style.border.style} ${resolve(style.border.color) ?? "currentColor"}`;
    for (const side of style.border.sides ?? ["top", "right", "bottom", "left"]) css[`border${side[0].toUpperCase()}${side.slice(1)}` as "borderTop"] = value;
    css.borderRadius = mm(style.border.radius, zoom);
  }
  if (style.align === "center") {
    css.marginLeft = "auto";
    css.marginRight = "auto";
  } else if (style.align === "right") css.marginLeft = "auto";
  const text = style.text;
  if (text) {
    if (text.font) css.fontFamily = font(text.font);
    if (text.size) css.fontSize = text.size * PT_TO_PX * zoom;
    if (text.weight) css.fontWeight = text.weight === "bold" ? 700 : text.weight === "medium" ? 500 : 400;
    if (text.italic !== undefined && text.italic !== null) css.fontStyle = text.italic ? "italic" : "normal";
    if (text.color) css.color = resolve(text.color);
    if (text.align) css.textAlign = text.align;
    if (text.line_height) css.lineHeight = text.line_height;
    if (text.letter_spacing) css.letterSpacing = text.letter_spacing * PT_TO_PX * zoom;
    if (text.transform && text.transform !== "none") css.textTransform = text.transform === "upper" ? "uppercase" : "lowercase";
  }
  return css;
}

function Spans({ content }: { content?: TextContent | null }) {
  const t = useTranslations("documentStudio");
  const tPdf = useTranslations("documentPdf");
  if (!content?.default?.length) return <span className="studio-placeholder">{t("canvas.emptyText")}</span>;
  return (
    <>
      {content.default.map((inline: Inline, index) => {
        if (inline.t === "br") return <br key={index} />;
        const style: CSSProperties = { fontWeight: inline.b ? 700 : undefined, fontStyle: inline.i ? "italic" : undefined };
        if (inline.t === "text") return <span key={index} style={style}>{inline.v}</span>;
        if (inline.t === "key") return <span key={index} style={style}>{tPdf.has(inline.key) ? tPdf(inline.key) : inline.key}</span>;
        return (
          <span key={index} className="studio-binding-chip" style={style}>
            {bindingLabel(t, inline.path)}
          </span>
        );
      })}
    </>
  );
}

export function NodeView({ node, area, zoom }: { node: TemplateNode; area: Area; zoom: number }) {
  const t = useTranslations("documentStudio");
  const tPdf = useTranslations("documentPdf");
  const designer = useDesigner();
  const { brand, selectedId, select, diagnostics, editable, assets, components } = designer;
  const resolve = (ref?: string | null) => resolveColor(ref, brand);
  const font = (ref?: string | null) => resolveFont(ref, brand);
  const drag = useDraggable({ id: `node|${node.id}`, disabled: !editable || node.locked === true, data: { kind: "node", id: node.id } });
  const issues = diagnosticsFor(diagnostics, node.id);
  const typography = brand.tokens.typography;
  const selected = selectedId === node.id;
  const disabled = node.enabled === false;

  const children = (container: TemplateNode, layout: "stack" | "row" | "grid" | "layer" = "stack") => {
    const items = container.children ?? [];
    if (layout === "layer") {
      return items.map((child) => (
        <div
          key={child.id}
          className="studio-layer-item"
          style={{ left: mm(child.frame?.x, zoom), top: mm(child.frame?.y, zoom), width: child.frame?.width ? mm(child.frame.width, zoom) : undefined, transform: child.frame?.rotate ? `rotate(${child.frame.rotate}deg)` : undefined }}
        >
          <NodeView node={child} area={area} zoom={zoom} />
        </div>
      ));
    }
    if (items.length === 0) return <DropZone target={{ area, parentId: container.id, index: 0 }} empty label={t("canvas.dropHere")} />;
    const result: ReactNode[] = [];
    items.forEach((child, index) => {
      if (layout === "stack") result.push(<DropZone key={`gap-${index}`} target={{ area, parentId: container.id, index }} />);
      result.push(<NodeView key={child.id} node={child} area={area} zoom={zoom} />);
    });
    if (layout === "stack") result.push(<DropZone key="gap-end" target={{ area, parentId: container.id, index: items.length }} />);
    else result.push(<DropZone key="gap-end" target={{ area, parentId: container.id, index: items.length }} />);
    return result;
  };

  let body: ReactNode;
  const style = boxStyle(node.style, zoom, resolve, font);
  switch (node.type) {
    case "stack":
    case "column":
    case "header":
    case "footer":
      body = <div className="studio-node-stack" style={{ gap: mm((node.gap as number) ?? 3, zoom) }}>{children(node)}</div>;
      break;
    case "container":
      body = <div className="studio-node-stack" style={{ gap: mm((node.gap as number) ?? 3, zoom) }}>{children(node)}</div>;
      break;
    case "section":
      body = (
        <div className="studio-node-stack" style={{ gap: mm((node.gap as number) ?? 3, zoom) }}>
          {node.title ? (
            <div className="studio-heading" style={{ fontFamily: brand.headingFont, color: brand.colors.heading, fontSize: typography[`size_h${Math.min((node.level as number) ?? 1, 3)}` as "size_h1"] * PT_TO_PX * zoom }}>
              <Spans content={node.title as TextContent} />
            </div>
          ) : null}
          {children(node)}
        </div>
      );
      break;
    case "row":
      body = (
        <div className="studio-node-row" style={{ gridTemplateColumns: (node.children ?? []).map((child) => gridTrack(child.style?.width, zoom)).join(" ") || "1fr", columnGap: mm((node.gap as number) ?? 5, zoom), alignItems: node.valign === "middle" ? "center" : node.valign === "bottom" ? "end" : "start" }}>
          {children(node, "row")}
        </div>
      );
      break;
    case "grid": {
      const widths = (node.column_widths as string[] | undefined) ?? [];
      const columns = (node.columns as number) ?? 2;
      body = (
        <div className="studio-node-row" style={{ gridTemplateColumns: widths.length === columns ? widths.map((value) => gridTrack(value, zoom)).join(" ") : `repeat(${columns}, 1fr)`, columnGap: mm((node.gap_x as number) ?? 5, zoom), rowGap: mm((node.gap_y as number) ?? 4, zoom) }}>
          {children(node, "grid")}
        </div>
      );
      break;
    }
    case "absolute_layer":
      body = <div className="studio-node-layer" style={{ height: node.anchor === "page" ? undefined : mm((node.height as number) ?? 60, zoom) }}>{children(node, "layer")}</div>;
      break;
    case "text": {
      const role = (node.role as string) ?? "paragraph";
      const roleStyle: CSSProperties =
        role === "title" ? { fontFamily: brand.headingFont, fontSize: typography.size_title * PT_TO_PX * zoom, fontWeight: 700, color: brand.colors.heading, lineHeight: 1.15 }
        : role === "subtitle" ? { fontFamily: brand.headingFont, fontSize: typography.size_subtitle * PT_TO_PX * zoom, color: brand.colors.secondary }
        : role === "heading" ? { fontFamily: brand.headingFont, fontSize: typography[`size_h${Math.min((node.level as number) ?? 1, 3)}` as "size_h1"] * PT_TO_PX * zoom, fontWeight: 700, color: brand.colors.heading }
        : role === "caption" ? { fontSize: typography.size_small * PT_TO_PX * zoom, fontStyle: "italic", color: brand.colors.muted }
        : role === "label" ? { fontSize: typography.size_small * PT_TO_PX * zoom, fontWeight: 700, color: brand.colors.muted }
        : role === "small" ? { fontSize: typography.size_small * PT_TO_PX * zoom }
        : {};
      body = <div style={roleStyle}><Spans content={node.content as TextContent} /></div>;
      break;
    }
    case "rich_text":
      body = <div className="studio-node-rich">{(node.markdown as string) || <span className="studio-placeholder">{t("canvas.emptyRichText")}</span>}</div>;
      break;
    case "image": {
      const source = node.source as { kind: string; asset_id?: string | null; path?: string } | undefined;
      let url: string | null = null;
      if (source?.kind === "asset" && source.asset_id) url = assets.find((asset) => asset.id === source.asset_id)?.content_url ?? null;
      if (source?.kind === "binding" && source.path?.startsWith("brand.")) {
        const key = source.path.slice(6) as keyof typeof brand.tokens.assets;
        const assetId = key === "logo" && designer.content.settings.brand_overrides.logo_asset_id ? designer.content.settings.brand_overrides.logo_asset_id : (brand.tokens.assets[key] as string | null);
        url = assets.find((asset) => asset.id === assetId)?.content_url ?? null;
      }
      body = url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img className="studio-node-image" src={url} alt="" />
      ) : (
        <div className="studio-node-placeholder">{source?.kind === "binding" ? bindingLabel(t, source.path ?? "") : t("canvas.noImage")}</div>
      );
      break;
    }
    case "divider":
      body = <hr className="studio-node-divider" style={{ borderTopColor: resolve(node.color as string) ?? brand.colors.border, borderTopWidth: Math.max(1, ((node.thickness as number) ?? 0.6) * PT_TO_PX * zoom), borderTopStyle: (node.line_style as "solid") ?? "solid", width: cssLength(node.length as string, zoom) ?? "100%" }} />;
      break;
    case "spacer":
      body = <div className={node.flexible ? "studio-node-spacer studio-node-spacer-flex" : "studio-node-spacer"} style={{ height: mm((node.size as number) ?? 6, zoom) }} />;
      break;
    case "page_break":
      body = <div className="studio-node-pagebreak">{t("canvas.pageBreak")}</div>;
      break;
    case "page_number":
      body = <span>{tPdf("page.of", { page: 1, total: 2 })}</span>;
      break;
    case "toc":
      body = (
        <div className="studio-node-toc">
          {node.show_title !== false && <div className="studio-heading" style={{ color: brand.colors.primary }}>{tPdf("toc.title")}</div>}
          <div className="studio-toc-line" />
          <div className="studio-toc-line studio-toc-line-indent" />
          <div className="studio-toc-line" />
        </div>
      );
      break;
    case "qr_code":
      body = <div className="studio-node-qr" style={{ width: mm((node.size as number) ?? 22, zoom), height: mm((node.size as number) ?? 22, zoom) }}>QR</div>;
      break;
    case "verify_note":
      body = <div className="studio-node-verify">{tPdf("verify.urlAndId", { url: "abgabe.hocx.ch/verify", id: "7F3A-91C2" })}</div>;
      break;
    case "metadata":
      body = (
        <div className="studio-node-meta">
          {((node.fields as string[]) ?? ["number", "date", "status", "version"]).map((field) => (
            <div key={field}>
              <strong>{t(`metadataField.${field}`)}</strong> <span className="studio-binding-chip">{t(`metadataField.${field}`)}</span>
            </div>
          ))}
        </div>
      );
      break;
    case "watermark":
      body = <div className="studio-node-watermark">{tPdf("watermark.draft")}</div>;
      break;
    case "list":
      body = (
        <ul className="studio-node-list">
          {node.source ? (
            <>
              <li><Spans content={node.item as TextContent} /></li>
              <li><Spans content={node.item as TextContent} /></li>
            </>
          ) : (
            ((node.items as string[]) ?? []).map((item, index) => <li key={index}>{item || <span className="studio-placeholder">{t("canvas.emptyItem")}</span>}</li>)
          )}
        </ul>
      );
      break;
    case "table": {
      const columns = (node.columns as { id: string; header?: TextContent; cell?: TextContent; width?: string; align?: string }[]) ?? [];
      const rows = node.source ? [0, 1] : ((node.rows as string[][]) ?? []);
      body = (
        <table className="studio-node-table">
          <thead>
            <tr style={{ background: brand.colors.table_header_background, color: brand.colors.table_header_text }}>
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
      break;
    }
    case "data_block":
      body = (
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
          <span className="studio-node-data-kind">{t("canvas.reusable", { name: component.name })}</span>
          <NodeView node={component.node} area={area} zoom={zoom} />
        </div>
      ) : (
        <div className="studio-node-placeholder">{t("canvas.componentMissing")}</div>
      );
      break;
    }
    default:
      body = <div className="studio-node-placeholder">{t(`nodeType.${node.type}`)}</div>;
  }

  const label = node.name || t(`nodeType.${node.type}`);
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      select(node.id);
    }
  };
  return (
    <div
      ref={drag.setNodeRef}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      aria-label={label}
      onKeyDown={onKeyDown}
      onClick={(event) => {
        event.stopPropagation();
        select(node.id);
      }}
      className={[
        "studio-node",
        selected ? "studio-node-selected" : "",
        disabled ? "studio-node-disabled" : "",
        node.visible_if ? "studio-node-conditional" : "",
        node.repeat ? "studio-node-repeat" : "",
        issues.some((item) => item.severity === "error") ? "studio-node-error" : issues.length ? "studio-node-warning" : "",
        drag.isDragging ? "studio-node-dragging" : "",
      ].join(" ")}
      style={style}
    >
      {selected && editable && !node.locked && (
        <span className="studio-node-handle" {...drag.listeners} {...drag.attributes} aria-label={t("canvas.dragHandle", { name: label })} role="button">
          ⠿
        </span>
      )}
      {(selected || issues.length > 0) && <span className="studio-node-tag">{label}{issues.length ? ` · ${t(`diagnosticShort.${issues[0].severity}`)}` : ""}</span>}
      {body}
    </div>
  );
}

function AreaNodes({ area, nodes, zoom, emptyLabel }: { area: Area; nodes: TemplateNode[]; zoom: number; emptyLabel: string }) {
  if (nodes.length === 0) return <DropZone target={{ area, parentId: null, index: 0 }} empty label={emptyLabel} />;
  const result: ReactNode[] = [];
  nodes.forEach((node, index) => {
    result.push(<DropZone key={`gap-${index}`} target={{ area, parentId: null, index }} />);
    result.push(<NodeView key={node.id} node={node} area={area} zoom={zoom} />);
  });
  result.push(<DropZone key="gap-end" target={{ area, parentId: null, index: nodes.length }} />);
  return <>{result}</>;
}

export function Canvas({ zoom }: { zoom: number }) {
  const t = useTranslations("documentStudio");
  const { content, brand, select, activeArea, setActiveArea } = useDesigner();
  const master = content.masters.find((item) => item.id === content.settings.default_master) ?? content.masters[0];
  const [widthMm, heightMm] = pageDimensions(content.page, master?.orientation);
  const margins = master?.margins ?? content.page.margins;
  const pageStyle: CSSProperties = {
    width: mm(widthMm, zoom),
    minHeight: mm(heightMm, zoom),
    fontFamily: brand.bodyFont,
    fontSize: brand.tokens.typography.base_size * PT_TO_PX * zoom,
    lineHeight: brand.tokens.typography.line_height,
    color: brand.colors.text,
    background: brand.colors.background,
  };
  const titlePage = content.title_page;
  // Bereichsbeschriftungen stehen links neben der Seite; der Inhaltsbereich beginnt unter dem oberen Rand.
  const areaButton = (area: Area, label: string, style?: CSSProperties) => (
    <button type="button" style={style} className={activeArea === area ? "studio-area-label studio-area-label-active" : "studio-area-label"} onClick={(event) => { event.stopPropagation(); setActiveArea(area); select(null); }}>
      {label}
    </button>
  );

  return (
    <div className="studio-canvas" onClick={() => select(null)}>
      {titlePage.enabled && (
        <div className="studio-page studio-page-title" style={{ ...pageStyle, height: mm(heightMm, zoom), background: resolveColor(titlePage.background, brand) ?? pageStyle.background }}>
          {areaButton("title_page", titlePage.visible_if ? t("canvas.titlePageConditional") : t("canvas.titlePage"))}
          <div className="studio-page-content" style={{ padding: `${mm(margins.top, zoom)}px ${mm(margins.right, zoom)}px ${mm(margins.bottom, zoom)}px ${mm(margins.left, zoom)}px` }}>
            <AreaNodes area="title_page" nodes={titlePage.children} zoom={zoom} emptyLabel={t("canvas.dropTitlePage")} />
          </div>
        </div>
      )}
      <div className="studio-page" style={pageStyle}>
        <div className="studio-page-margins" style={{ top: mm(margins.top, zoom), right: mm(margins.right, zoom), bottom: mm(margins.bottom, zoom), left: mm(margins.left, zoom) }} aria-hidden="true" />
        {master && (
          <div className="studio-page-header" style={{ height: mm(margins.top, zoom), paddingLeft: mm(margins.left, zoom), paddingRight: mm(margins.right, zoom) }}>
            {areaButton(`master:${master.id}:header`, t("canvas.header"))}
            <div className="studio-page-slot">
              <AreaNodes area={`master:${master.id}:header`} nodes={master.header?.children ?? []} zoom={zoom} emptyLabel={t("canvas.dropHeader")} />
            </div>
          </div>
        )}
        <div className="studio-page-content" style={{ padding: `${mm(margins.top, zoom)}px ${mm(margins.right, zoom)}px ${mm(margins.bottom, zoom)}px ${mm(margins.left, zoom)}px`, columnCount: content.page.columns > 1 ? content.page.columns : undefined, columnGap: mm(content.page.column_gap, zoom) }}>
          {areaButton("body", t("canvas.body"), { top: mm(margins.top, zoom) })}
          <AreaNodes area="body" nodes={content.body} zoom={zoom} emptyLabel={t("canvas.dropBody")} />
        </div>
        {master && (
          <div className="studio-page-footer" style={{ height: mm(margins.bottom, zoom), paddingLeft: mm(margins.left, zoom), paddingRight: mm(margins.right, zoom) }}>
            {areaButton(`master:${master.id}:footer`, t("canvas.footer"))}
            <div className="studio-page-slot">
              <AreaNodes area={`master:${master.id}:footer`} nodes={master.footer?.children ?? []} zoom={zoom} emptyLabel={t("canvas.dropFooter")} />
            </div>
          </div>
        )}
        {master && (master.background?.length ?? 0) > 0 && (
          <div className="studio-page-background" aria-hidden="true">
            {(master.background ?? []).map((node) => (node.type === "watermark" ? <div key={node.id} className="studio-node-watermark studio-node-watermark-page">{t("canvas.watermark")}</div> : null))}
          </div>
        )}
      </div>
      <p className="studio-canvas-hint">{t("canvas.approximateHint")}</p>
    </div>
  );
}
