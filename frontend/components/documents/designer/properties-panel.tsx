"use client";

// Rechte Seitenleiste: Eigenschaften des ausgewählten Elements, gruppiert nach den
// Editor-Metadaten des Knotentyps (components.py). Der Modus bestimmt, welche Gruppen und
// Felder sichtbar sind; die Daten bleiben in allen Modi dieselben.

import { useState } from "react";
import { useTranslations } from "next-intl";

import { AppearanceEditor } from "@/components/documents/appearance-editor";
import { isProtocolContent, ProtocolBlockList } from "@/components/documents/designer/block-appearance-panel";
import { AssetPicker } from "@/components/documents/asset-picker";
import { ComponentParamForm } from "@/components/documents/designer/component-params";
import { diagnosticsFor, modeAllows, useDesigner, useSelectedNode } from "@/components/documents/designer/designer-context";
import { BindingSelect, BorderField, CheckField, ColorField, ConditionEditor, Field, LengthField, NumberField, SpacingField, TextContentEditor, TextStyleFields } from "@/components/documents/designer/fields";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { apiErrorMessage, EditorMode, studioApi } from "@/lib/documents/api";
import { brandVariant } from "@/lib/documents/appearance";
import { AppearanceOverrides, BoxStyle, duplicateNode, locate, newNodeId, removeNode, repeatScope, TemplateContent, TemplateNode, TextContent } from "@/lib/documents/layout";

// Mindestmodus je Eigenschaftsgruppe (Gruppen aus components.py)
const GROUP_MODE: Record<string, EditorMode> = {
  content: "simple",
  image: "simple",
  data: "simple",
  list: "simple",
  divider: "simple",
  spacer: "simple",
  section: "simple",
  toc: "simple",
  metadata: "simple",
  pagenumber: "simple",
  pagebreak: "simple",
  typography: "simple",
  visibility: "simple",
  table: "advanced",
  qr: "advanced",
  verify: "advanced",
  watermark: "advanced",
  stack: "advanced",
  row: "advanced",
  grid: "advanced",
  container: "advanced",
  component: "advanced",
  size: "advanced",
  spacing: "advanced",
  background: "advanced",
  border: "advanced",
  align: "advanced",
  repeat: "advanced",
  pagination: "advanced",
  layer: "expert",
};

function Group({ title, children, open = false }: { title: string; children: React.ReactNode; open?: boolean }) {
  return (
    <details className="studio-prop-group" open={open}>
      <summary className="studio-prop-summary">{title}</summary>
      <div className="studio-prop-body">{children}</div>
    </details>
  );
}

export function PropertiesPanel() {
  const t = useTranslations("documentStudio");
  const toast = useToast();
  const confirm = useConfirm();
  const designer = useDesigner();
  const { content, setContent, select, mode, catalog, diagnostics, editable, assets, setAssets, capabilities, components, setComponents, brand } = designer;
  const { node, change } = useSelectedNode();
  const [assetPickerOpen, setAssetPickerOpen] = useState(false);
  if (!node) return null;
  const meta = catalog.node_types[node.type];
  const scope = repeatScope(content, node.id);
  const issues = diagnosticsFor(diagnostics, node.id);
  const style: BoxStyle = node.style ?? {};
  const setStyle = (patch: Partial<BoxStyle>, key: string) => change({ style: { ...style, ...patch } }, `style:${key}`);
  const groups = (meta?.groups ?? []).filter((group) => modeAllows(mode, GROUP_MODE[group] ?? "advanced"));
  const disabled = !editable;

  async function saveAsComponent() {
    try {
      const created = await studioApi.createComponent({ name: node!.name || t(`nodeType.${node!.type}`), node: node! });
      setComponents([...components, created]);
      toast(t("components.saved"), "success");
    } catch (error) {
      toast(apiErrorMessage(error, t("common.actionFailed")), "error");
    }
  }

  const sectionFor = (group: string) => {
    switch (group) {
      case "content":
        if (node.type === "rich_text")
          return (
            <Field label={t("props.richText")} help={t("props.richTextHelp")}>
              <textarea rows={8} value={(node.markdown as string) ?? ""} onChange={(event) => change({ markdown: event.target.value }, "markdown")} />
            </Field>
          );
        return (
          <>
            <Field label={t("props.role")}>
              <select value={(node.role as string) ?? "paragraph"} onChange={(event) => change({ role: event.target.value })}>
                {["paragraph", "title", "subtitle", "heading", "caption", "label", "small"].map((role) => (
                  <option key={role} value={role}>
                    {t(`props.roleValue.${role}`)}
                  </option>
                ))}
              </select>
            </Field>
            {node.role === "heading" && <NumberField label={t("props.level")} value={(node.level as number) ?? 1} min={1} max={4} onChange={(level) => change({ level })} />}
            <TextContentEditor label={t("props.text")} value={node.content as TextContent} scope={scope} mergeKey="content" onChange={(value, key) => change({ content: value }, key)} />
          </>
        );
      case "image": {
        const source = (node.source as { kind: "asset" | "binding"; asset_id?: string | null; path?: string }) ?? { kind: "binding", path: "brand.logo" };
        return (
          <>
            <Field label={t("props.imageSource")}>
              <select value={source.kind} onChange={(event) => change({ source: event.target.value === "asset" ? { kind: "asset", asset_id: null } : { kind: "binding", path: "brand.logo" } })}>
                <option value="binding">{t("props.imageFromBrand")}</option>
                <option value="asset">{t("props.imageFromAssets")}</option>
              </select>
            </Field>
            {source.kind === "binding" ? (
              <BindingSelect label={t("props.brandImage")} value={source.path} allowEmpty={false} types={["image"]} scope={scope} onChange={(path) => path && change({ source: { kind: "binding", path } })} />
            ) : (
              <div className="field-stack">
                <span className="field-label">{t("props.image")}</span>
                <button type="button" className="button-secondary" onClick={() => setAssetPickerOpen(true)}>
                  {source.asset_id ? assets.find((asset) => asset.id === source.asset_id)?.name ?? t("props.imageMissing") : t("props.chooseImage")}
                </button>
              </div>
            )}
            <Field label={t("props.fit")}>
              <select value={(node.fit as string) ?? "contain"} onChange={(event) => change({ fit: event.target.value })}>
                {["contain", "cover", "stretch"].map((fit) => (
                  <option key={fit} value={fit}>
                    {t(`props.fitValue.${fit}`)}
                  </option>
                ))}
              </select>
            </Field>
            <TextContentEditor label={t("props.caption")} value={node.caption as TextContent} scope={scope} mergeKey="caption" onChange={(value, key) => change({ caption: value }, key)} />
            <AssetPicker open={assetPickerOpen} onClose={() => setAssetPickerOpen(false)} assets={assets} onAssetsChange={setAssets} canUpload={capabilities.manage_brand} onPick={(asset) => change({ source: { kind: "asset", asset_id: asset.id } })} />
          </>
        );
      }
      case "data": {
        const component = catalog.data_components.find((item) => item.type === node.component);
        return (
          <>
            <p className="studio-prop-lead">{t(`component.${node.component as string}`)}</p>
            <p className="field-help">{t(`componentHelp.${node.component as string}`)}</p>
            {component?.access === "finance" && !capabilities.finance_data && <StatusBanner tone="neutral" message={t("props.financeRestricted")} />}
            {component?.access === "writer" && !capabilities.personal_data && <StatusBanner tone="neutral" message={t("props.personalRestricted")} />}
            <Field label={t("props.titleMode")}>
              <select value={(node.title_mode as string) ?? "none"} onChange={(event) => change({ title_mode: event.target.value, title: event.target.value === "custom" ? node.title ?? { default: [{ t: "text", v: "" }] } : node.title })}>
                {["none", "auto", "custom"].map((value) => (
                  <option key={value} value={value}>
                    {t(`props.titleModeValue.${value}`)}
                  </option>
                ))}
              </select>
            </Field>
            {node.title_mode === "custom" && <TextContentEditor label={t("props.customTitle")} value={node.title as TextContent} scope={scope} mergeKey="title" onChange={(value, key) => change({ title: value }, key)} />}
            <CheckField label={t("props.hideIfEmpty")} checked={node.hide_if_empty !== false} onChange={(value) => change({ hide_if_empty: value })} />
            {modeAllows(mode, "advanced") && <NumberField label={t("props.outlineLevel")} value={(node.level as number) ?? 1} min={1} max={4} onChange={(level) => change({ level })} />}
            {modeAllows(mode, "advanced") && component && (
              <ComponentParamForm schema={component.params_schema} params={(node.params as Record<string, unknown>) ?? {}} onChange={(params) => change({ params }, "params")} />
            )}
            {component && component.appearance_kinds.length > 0 && catalog.appearance && (
              <>
                <h4 className="studio-subtitle">{t("appearance.designerTitle")}</h4>
                <p className="field-help">{t("appearance.designerHelp")}</p>
                <AppearanceEditor
                  catalog={catalog.appearance}
                  kinds={component.appearance_kinds}
                  value={node.appearance as AppearanceOverrides | undefined}
                  inherited={(kind) => brandVariant(brand.tokens, catalog.appearance, kind)}
                  inheritLabel={(value) => t("appearance.inheritBrand", { value })}
                  onChange={(appearance) => change({ appearance })}
                />
              </>
            )}
            {isProtocolContent(node) && (
              <>
                <h4 className="studio-subtitle">{t("blockAppearance.listTitle")}</h4>
                <p className="field-help">{t("blockAppearance.listHelp")}</p>
                <ProtocolBlockList node={node} />
              </>
            )}
          </>
        );
      }
      case "list":
        return (
          <>
            <Field label={t("props.marker")}>
              <select value={(node.marker as string) ?? "bullet"} onChange={(event) => change({ marker: event.target.value })}>
                {["bullet", "number", "none"].map((value) => (
                  <option key={value} value={value}>
                    {t(`props.markerValue.${value}`)}
                  </option>
                ))}
              </select>
            </Field>
            <BindingSelect label={t("props.listSource")} value={(node.source as string) ?? null} types={["list"]} onChange={(source) => change({ source, item: source ? { default: [{ t: "bind", path: `item.${catalog.bindings.find((item) => item.path === source)?.item_fields[0]?.key ?? "title"}` }] } : node.item })} />
            {node.source ? (
              <TextContentEditor label={t("props.listItem")} value={node.item as TextContent} scope={node.source as string} mergeKey="item" onChange={(value, key) => change({ item: value }, key)} />
            ) : (
              <Field label={t("props.listItems")} help={t("props.oneItemPerLine")}>
                <textarea rows={5} value={((node.items as string[]) ?? []).join("\n")} onChange={(event) => change({ items: event.target.value.split("\n") }, "items")} />
              </Field>
            )}
          </>
        );
      case "table":
        return <TableEditor node={node} change={change} />;
      case "divider":
        return (
          <>
            <NumberField label={t("props.thickness")} value={(node.thickness as number) ?? 0.6} min={0.1} max={10} step={0.1} suffix={t("brand.unitPt")} onChange={(thickness) => change({ thickness }, "thickness")} />
            <Field label={t("fields.borderStyle")}>
              <select value={(node.line_style as string) ?? "solid"} onChange={(event) => change({ line_style: event.target.value })}>
                {["solid", "dashed", "dotted"].map((value) => (
                  <option key={value} value={value}>
                    {t(`fields.lineStyle.${value}`)}
                  </option>
                ))}
              </select>
            </Field>
            <LengthField label={t("props.length")} value={(node.length as string) ?? "fill"} onChange={(length) => change({ length: length ?? "fill" })} />
            <ColorField label={t("props.lineColor")} value={(node.color as string) ?? "$brand.border"} allowEmpty={false} onChange={(color) => change({ color: color ?? "$brand.border" })} />
          </>
        );
      case "spacer":
        return (
          <>
            <NumberField label={t("props.spacerSize")} value={(node.size as number) ?? 6} min={0} max={300} suffix={t("brand.unitMm")} onChange={(size) => change({ size }, "size")} />
            <CheckField label={t("props.flexible")} help={t("props.flexibleHelp")} checked={node.flexible === true} onChange={(flexible) => change({ flexible })} />
          </>
        );
      case "section":
        return (
          <>
            <TextContentEditor label={t("props.sectionTitle")} value={node.title as TextContent} scope={scope} mergeKey="title" onChange={(value, key) => change({ title: value }, key)} />
            <NumberField label={t("props.level")} value={(node.level as number) ?? 1} min={1} max={4} onChange={(level) => change({ level })} />
            <CheckField label={t("props.outlined")} checked={node.outlined !== false} onChange={(outlined) => change({ outlined })} />
          </>
        );
      case "toc":
        return (
          <>
            <NumberField label={t("props.tocDepth")} value={(node.depth as number) ?? 2} min={1} max={4} onChange={(depth) => change({ depth })} />
            <CheckField label={t("props.tocTitle")} checked={node.show_title !== false} onChange={(show_title) => change({ show_title })} />
            <Field label={t("props.density")}>
              <select value={(node.density as string) ?? "normal"} onChange={(event) => change({ density: event.target.value })}>
                {["normal", "compact", "very_compact"].map((value) => (
                  <option key={value} value={value}>
                    {t(`props.densityValue.${value}`)}
                  </option>
                ))}
              </select>
            </Field>
          </>
        );
      case "metadata": {
        const fields = (node.fields as string[]) ?? ["number", "date", "status", "version"];
        return (
          <>
            {["number", "date", "status", "version", "place", "type", "organization"].map((field) => (
              <CheckField key={field} label={t(`metadataField.${field}`)} checked={fields.includes(field)} onChange={(checked) => change({ fields: checked ? [...fields, field] : fields.filter((item) => item !== field) })} />
            ))}
            <Field label={t("props.metadataLayout")}>
              <select value={(node.layout as string) ?? "list"} onChange={(event) => change({ layout: event.target.value })}>
                <option value="list">{t("props.metadataList")}</option>
                <option value="inline">{t("props.metadataInline")}</option>
              </select>
            </Field>
          </>
        );
      }
      case "pagenumber":
        return (
          <Field label={t("props.pageNumberFormat")}>
            <select value={(node.format as string) ?? "page_of"} onChange={(event) => change({ format: event.target.value })}>
              <option value="page_of">{t("props.pageOf")}</option>
              <option value="page">{t("props.pageOnly")}</option>
            </select>
          </Field>
        );
      case "pagebreak":
        return modeAllows(mode, "expert") ? (
          <Field label={t("props.nextMaster")} help={t("props.nextMasterHelp")}>
            <select value={(node.master as string) ?? ""} onChange={(event) => change({ master: event.target.value || null })}>
              <option value="">{t("props.sameMaster")}</option>
              {content.masters.map((master) => (
                <option key={master.id} value={master.id}>
                  {master.name || master.id}
                </option>
              ))}
            </select>
          </Field>
        ) : (
          <p className="field-help">{t("props.pageBreakHelp")}</p>
        );
      case "qr":
        return (
          <>
            <Field label={t("props.qrTarget")}>
              <select value={(node.target as string) ?? "verify"} onChange={(event) => change({ target: event.target.value })}>
                {["verify", "protocol", "url"].map((value) => (
                  <option key={value} value={value}>
                    {t(`props.qrTargetValue.${value}`)}
                  </option>
                ))}
              </select>
            </Field>
            {node.target === "url" && (
              <Field label={t("props.url")}>
                <input value={(node.url as string) ?? ""} placeholder="https://" onChange={(event) => change({ url: event.target.value }, "url")} />
              </Field>
            )}
            <NumberField label={t("props.qrSize")} value={(node.size as number) ?? 22} min={10} max={80} suffix={t("brand.unitMm")} onChange={(size) => change({ size }, "size")} />
          </>
        );
      case "verify":
        return (
          <>
            <CheckField label={t("props.verifyUrl")} checked={node.show_url !== false} onChange={(show_url) => change({ show_url })} />
            <CheckField label={t("props.verifyId")} checked={node.show_id !== false} onChange={(show_id) => change({ show_id })} />
            <CheckField label={t("props.verifyQr")} checked={node.show_qr === true} onChange={(show_qr) => change({ show_qr })} />
          </>
        );
      case "watermark":
        return (
          <>
            <Field label={t("props.watermarkWhen")}>
              <select value={(node.when as string) ?? "draft"} onChange={(event) => change({ when: event.target.value })}>
                <option value="draft">{t("props.watermarkDraft")}</option>
                <option value="always">{t("props.watermarkAlways")}</option>
              </select>
            </Field>
            <TextContentEditor label={t("props.watermarkText")} value={node.text as TextContent} mergeKey="text" onChange={(value, key) => change({ text: value }, key)} />
            <NumberField label={t("props.watermarkSize")} value={(node.size as number) ?? 96} min={8} max={300} suffix={t("brand.unitPt")} onChange={(size) => change({ size }, "size")} />
            <NumberField label={t("props.angle")} value={(node.angle as number) ?? -35} min={-90} max={90} suffix="°" onChange={(angle) => change({ angle }, "angle")} />
            <ColorField label={t("props.watermarkColor")} value={(node.color as string) ?? "$brand.watermark"} allowEmpty={false} onChange={(color) => change({ color: color ?? "$brand.watermark" })} />
          </>
        );
      case "stack":
      case "container":
        return (
          <>
            <NumberField label={t("props.gap")} value={(node.gap as number) ?? 3} min={0} max={100} step={0.5} suffix={t("brand.unitMm")} onChange={(gap) => change({ gap }, "gap")} />
            {node.type === "container" && <CheckField label={t("props.breakable")} checked={node.breakable !== false} onChange={(breakable) => change({ breakable })} />}
          </>
        );
      case "row":
        return (
          <>
            <NumberField label={t("props.gap")} value={(node.gap as number) ?? 5} min={0} max={100} step={0.5} suffix={t("brand.unitMm")} onChange={(gap) => change({ gap }, "gap")} />
            <Field label={t("props.valign")}>
              <select value={(node.valign as string) ?? "top"} onChange={(event) => change({ valign: event.target.value })}>
                {["top", "middle", "bottom"].map((value) => (
                  <option key={value} value={value}>
                    {t(`props.valignValue.${value}`)}
                  </option>
                ))}
              </select>
            </Field>
            <button type="button" className="button-secondary button-ghost" onClick={() => change({ children: [...(node.children ?? []), { id: newNodeId(), type: "column", style: { width: "1fr" }, children: [] }] })}>
              {t("props.addColumn")}
            </button>
            <p className="field-help">{t("props.columnWidthHelp")}</p>
          </>
        );
      case "grid":
        return (
          <>
            <NumberField label={t("props.columns")} value={(node.columns as number) ?? 2} min={1} max={6} onChange={(columns) => change({ columns })} />
            <NumberField label={t("props.gapX")} value={(node.gap_x as number) ?? 5} min={0} max={100} suffix={t("brand.unitMm")} onChange={(gap_x) => change({ gap_x }, "gapX")} />
            <NumberField label={t("props.gapY")} value={(node.gap_y as number) ?? 4} min={0} max={100} suffix={t("brand.unitMm")} onChange={(gap_y) => change({ gap_y }, "gapY")} />
          </>
        );
      case "layer":
        return (
          <>
            <Field label={t("props.anchor")} help={t("props.anchorHelp")}>
              <select value={(node.anchor as string) ?? "flow"} onChange={(event) => change({ anchor: event.target.value })}>
                <option value="flow">{t("props.anchorFlow")}</option>
                <option value="page">{t("props.anchorPage")}</option>
              </select>
            </Field>
            {node.anchor !== "page" && <NumberField label={t("props.layerHeight")} value={(node.height as number) ?? 60} min={5} max={1000} suffix={t("brand.unitMm")} onChange={(height) => change({ height }, "height")} />}
          </>
        );
      case "component":
        return (
          <Field label={t("props.reusable")}>
            <select value={(node.component_id as string) ?? ""} onChange={(event) => change({ component_id: event.target.value })}>
              {components.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </Field>
        );
      case "size":
        return (
          <div className="studio-field-grid">
            <LengthField label={t("fields.width")} value={style.width ?? "auto"} allowFr={isRowChild(content, node.id)} onChange={(width) => setStyle({ width: width ?? "auto" }, "width")} />
            <LengthField label={t("fields.height")} value={style.height ?? null} allowNull onChange={(height) => setStyle({ height }, "height")} />
          </div>
        );
      case "spacing":
        return (
          <>
            <SpacingField label={t("fields.padding")} value={style.padding} onChange={(padding) => setStyle({ padding }, "padding")} />
            <div className="studio-field-grid">
              <NumberField label={t("fields.marginTop")} value={style.margin_top ?? 0} min={0} max={200} step={0.5} suffix={t("brand.unitMm")} onChange={(margin_top) => setStyle({ margin_top }, "marginTop")} />
              <NumberField label={t("fields.marginBottom")} value={style.margin_bottom ?? 0} min={0} max={200} step={0.5} suffix={t("brand.unitMm")} onChange={(margin_bottom) => setStyle({ margin_bottom }, "marginBottom")} />
            </div>
          </>
        );
      case "background":
        return <ColorField label={t("fields.background")} value={style.background} onChange={(background) => setStyle({ background }, "background")} />;
      case "border":
        return <BorderField value={style.border} onChange={(border) => setStyle({ border }, "border")} />;
      case "align":
        return (
          <Field label={t("fields.blockAlign")}>
            <select value={style.align ?? "left"} onChange={(event) => setStyle({ align: event.target.value as BoxStyle["align"] }, "align")}>
              {["left", "center", "right"].map((value) => (
                <option key={value} value={value}>
                  {t(`fields.alignValue.${value}`)}
                </option>
              ))}
            </select>
          </Field>
        );
      case "typography":
        return <TextStyleFields value={style.text} onChange={(text, key) => change({ style: { ...style, text } }, key)} mergeKey="typography" />;
      case "visibility":
        return (
          <>
            <CheckField label={t("props.enabled")} help={t("props.enabledHelp")} checked={node.enabled !== false} onChange={(enabled) => change({ enabled })} />
            {modeAllows(mode, "advanced") && <ConditionEditor value={node.visible_if ?? null} scope={scope} onChange={(visible_if) => change({ visible_if })} />}
          </>
        );
      case "repeat":
        return (
          <>
            <BindingSelect label={t("props.repeatSource")} value={node.repeat?.source ?? null} types={["list"]} onChange={(source) => change({ repeat: source ? { source, limit: node.repeat?.limit ?? 200, empty_text: node.repeat?.empty_text ?? null } : null })} />
            {node.repeat && (
              <>
                <NumberField label={t("props.repeatLimit")} value={node.repeat.limit ?? 200} min={1} max={1000} onChange={(limit) => change({ repeat: { ...node.repeat!, limit } }, "repeatLimit")} />
                <Field label={t("props.emptyText")}>
                  <input value={node.repeat.empty_text ?? ""} maxLength={300} onChange={(event) => change({ repeat: { ...node.repeat!, empty_text: event.target.value || null } }, "repeatEmpty")} />
                </Field>
              </>
            )}
            <p className="field-help">{t("props.repeatHelp")}</p>
          </>
        );
      case "pagination":
        return (
          <>
            <CheckField label={t("props.keepTogether")} help={t("props.keepTogetherHelp")} checked={node.keep_together === true} onChange={(keep_together) => change({ keep_together })} />
            <CheckField label={t("props.breakBefore")} checked={node.break_before === true} onChange={(break_before) => change({ break_before })} />
          </>
        );
      default:
        return null;
    }
  };

  const frameEditor = node.frame && modeAllows(mode, "expert") ? (
    <Group title={t("props.group.frame")} open>
      <div className="studio-field-grid">
        {(["x", "y", "width", "height"] as const).map((key) => (
          <NumberField key={key} label={t(`props.frame.${key}`)} value={(node.frame?.[key] as number | null) ?? null} min={0} max={1000} step={0.5} suffix={t("brand.unitMm")} onChange={(value) => change({ frame: { ...node.frame!, [key]: value } }, `frame:${key}`)} />
        ))}
        <NumberField label={t("props.frame.rotate")} value={node.frame.rotate ?? 0} min={-180} max={180} suffix="°" onChange={(rotate) => change({ frame: { ...node.frame!, rotate } }, "frame:rotate")} />
        <Field label={t("props.valign")}>
          <select value={node.frame.valign ?? "top"} onChange={(event) => change({ frame: { ...node.frame!, valign: event.target.value as "top" | "middle" | "bottom" } })}>
            {(["top", "middle", "bottom"] as const).map((value) => (
              <option key={value} value={value}>
                {t(`props.valignValue.${value}`)}
              </option>
            ))}
          </select>
        </Field>
      </div>
    </Group>
  ) : null;

  return (
    <div className="studio-properties" aria-label={t("props.title")}>
      <div className="studio-prop-header">
        <div>
          <span className="studio-prop-type">{t(`nodeType.${node.type}`)}</span>
          {modeAllows(mode, "advanced") ? (
            <input className="studio-prop-name" value={node.name ?? ""} placeholder={t("props.namePlaceholder")} aria-label={t("props.name")} onChange={(event) => change({ name: event.target.value || null }, "name")} disabled={disabled} />
          ) : null}
        </div>
        {editable && (
          <div className="studio-prop-actions">
            <button type="button" className="button-icon-soft" aria-label={t("props.duplicate")} title={t("props.duplicate")} onClick={() => { const result = duplicateNode(content, node.id); setContent(result.content); if (result.newId) select(result.newId); }}>
              ⧉
            </button>
            {modeAllows(mode, "advanced") && node.type !== "component_ref" && (
              <button type="button" className="button-icon-soft" aria-label={t("props.saveAsComponent")} title={t("props.saveAsComponent")} onClick={() => void saveAsComponent()}>
                ★
              </button>
            )}
            {!node.locked && (
              <button
                type="button"
                className="button-icon-soft button-icon-soft-danger"
                aria-label={t("props.delete")}
                title={t("props.delete")}
                onClick={async () => {
                  if ((node.children?.length ?? 0) > 0 && !(await confirm({ message: t("props.deleteConfirm"), tone: "danger", confirmLabel: t("props.delete") }))) return;
                  setContent(removeNode(content, node.id));
                  select(null);
                }}
              >
                ✕
              </button>
            )}
          </div>
        )}
      </div>
      {node.locked && <StatusBanner tone="neutral" message={t("props.locked")} />}
      {issues.map((issue, index) => (
        <StatusBanner key={index} tone={issue.severity === "error" ? "error" : "neutral"} message={`${t(`diagnosticCode.${issue.code}`)}${issue.detail ? ` (${issue.detail})` : ""}`} />
      ))}
      <fieldset className="studio-prop-fieldset" disabled={disabled}>
        {frameEditor}
        {groups.map((group, index) => {
          const section = sectionFor(group);
          if (!section) return null;
          return (
            <Group key={group} title={t(`props.group.${group}`)} open={index < 2}>
              {section}
            </Group>
          );
        })}
      </fieldset>
    </div>
  );
}

function isRowChild(content: TemplateContent, id: string): boolean {
  const location = locate(content, id);
  if (!location?.parentId) return false;
  const parent = locate(content, location.parentId);
  return parent?.node.type === "row";
}

type TableColumn = { id: string; header?: TextContent; width?: string; align?: string; cell?: TextContent };

function TableEditor({ node, change }: { node: TemplateNode; change: (patch: Partial<TemplateNode>, mergeKey?: string) => void }) {
  const t = useTranslations("documentStudio");
  const { mode, catalog } = useDesigner();
  const columns = (node.columns as TableColumn[]) ?? [];
  const source = (node.source as string | null) ?? null;
  const rows = (node.rows as string[][]) ?? [];
  const setColumn = (index: number, patch: Partial<TableColumn>, key: string) => change({ columns: columns.map((column, columnIndex) => (columnIndex === index ? { ...column, ...patch } : column)) }, `column:${index}:${key}`);
  const firstField = (path: string | null) => catalog.bindings.find((item) => item.path === path)?.item_fields;
  return (
    <>
      <BindingSelect
        label={t("props.tableSource")}
        value={source}
        types={["list"]}
        onChange={(next) => {
          const fields = firstField(next) ?? [];
          change({
            source: next,
            columns: next ? fields.slice(0, 4).map((field) => ({ id: newNodeId(), header: { default: [{ t: "text", v: "" }] }, cell: { default: [{ t: "bind", path: `item.${field.key}` }] }, width: "auto", align: "left" })) : columns,
          });
        }}
      />
      <p className="field-help">{source ? t("props.tableBoundHelp") : t("props.tableStaticHelp")}</p>
      {columns.map((column, index) => (
        <fieldset key={column.id} className="studio-fieldset">
          <legend className="field-label">{t("props.column", { number: index + 1 })}</legend>
          <TextContentEditor label={t("props.columnHeader")} value={column.header} mergeKey={`column:${index}:header`} onChange={(header, key) => change({ columns: columns.map((item, itemIndex) => (itemIndex === index ? { ...item, header } : item)) }, key)} />
          {source && <TextContentEditor label={t("props.columnCell")} value={column.cell} scope={source} mergeKey={`column:${index}:cell`} onChange={(cell, key) => change({ columns: columns.map((item, itemIndex) => (itemIndex === index ? { ...item, cell } : item)) }, key)} />}
          <div className="studio-field-grid">
            <LengthField label={t("fields.width")} value={column.width ?? "auto"} allowFr onChange={(width) => setColumn(index, { width: width ?? "auto" }, "width")} />
            <Field label={t("fields.align")}>
              <select value={column.align ?? "left"} onChange={(event) => setColumn(index, { align: event.target.value }, "align")}>
                {["left", "center", "right"].map((value) => (
                  <option key={value} value={value}>
                    {t(`fields.alignValue.${value}`)}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <button type="button" className="button-secondary button-ghost" onClick={() => change({ columns: columns.filter((_, columnIndex) => columnIndex !== index), rows: rows.map((row) => row.filter((_, cellIndex) => cellIndex !== index)) })}>
            {t("props.removeColumn")}
          </button>
        </fieldset>
      ))}
      <button type="button" className="button-secondary button-ghost" onClick={() => change({ columns: [...columns, { id: newNodeId(), header: { default: [{ t: "text", v: "" }] }, cell: { default: [] }, width: "auto", align: "left" }] })}>
        {t("props.addColumn")}
      </button>
      {!source && (
        <Field label={t("props.tableRows")} help={t("props.tableRowsHelp")}>
          <textarea
            rows={5}
            value={rows.map((row) => row.join(" | ")).join("\n")}
            onChange={(event) => change({ rows: event.target.value.split("\n").filter((line) => line.trim()).map((line) => line.split("|").map((cell) => cell.trim()).slice(0, columns.length)) }, "rows")}
          />
        </Field>
      )}
      <CheckField label={t("props.showHeader")} checked={node.show_header !== false} onChange={(show_header) => change({ show_header })} />
      {modeAllows(mode, "advanced") && <CheckField label={t("props.repeatHeader")} help={t("props.repeatHeaderHelp")} checked={node.repeat_header !== false} onChange={(repeat_header) => change({ repeat_header })} />}
      <Field label={t("props.zebra")}>
        <select value={node.zebra === true ? "on" : node.zebra === false ? "off" : ""} onChange={(event) => change({ zebra: event.target.value === "" ? null : event.target.value === "on" })}>
          <option value="">{t("props.zebraBrand")}</option>
          <option value="on">{t("props.zebraOn")}</option>
          <option value="off">{t("props.zebraOff")}</option>
        </select>
      </Field>
      {source && <NumberField label={t("props.rowLimit")} value={(node.limit as number) ?? 500} min={1} max={2000} onChange={(limit) => change({ limit }, "limit")} />}
      <Field label={t("props.emptyText")}>
        <input value={(node.empty_text as string) ?? ""} maxLength={300} onChange={(event) => change({ empty_text: event.target.value || null }, "emptyText")} />
      </Field>
    </>
  );
}
