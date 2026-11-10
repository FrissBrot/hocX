"use client";

// Modus «Einfach» des Dokument-Designers: links drei Schritte (Aussehen, Inhalt, Seite), rechts
// die PDF-Vorschau als Arbeitsfläche - ein Klick auf einen Bereich öffnet links den passenden
// Baustein. Bearbeitet dieselbe Vorlage wie «Erweitert» (Knoten der obersten Ebene, Brand-
// Übersteuerungen der Vorlage), beschrieben in backend/app/documents/simple.py. Knoten, die der
// Einfach-Modus nicht kennt, bleiben als «Eigener Bereich» erhalten (Ein/Aus, Reihenfolge).

import { ReactNode, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { AppearanceEditor } from "@/components/documents/appearance-editor";
import { AssetPicker } from "@/components/documents/asset-picker";
import { isProtocolContent } from "@/components/documents/designer/block-appearance-panel";
import { useDesigner } from "@/components/documents/designer/designer-context";
import { PreviewPanel } from "@/components/documents/designer/preview-panel";
import { ColorInput, normalizeHex } from "@/components/ui/color-input";
import { Popover } from "@/components/ui/popover";
import { Select } from "@/components/ui/select";
import { useConfirm } from "@/contexts/confirm-context";
import { Diagnostic, SimpleBlock, SimpleSetting, studioApi } from "@/lib/documents/api";
import { brandVariant } from "@/lib/documents/appearance";
import { AppearanceOverrides, BrandOverrides, insertNode, moveWithinParent, removeNode, TemplateContent, TemplateNode, TextContent, updateNode, withFreshIds } from "@/lib/documents/layout";
import { conditionPreset, getPath, matchSimpleBlock, plainText, setPath, setVariant, textContent, toggleValue, variantValue } from "@/lib/documents/simple";

type Step = "look" | "content" | "page";
type Props = { brandId: string | null; onDiagnostics: (items: Diagnostic[]) => void; onOpenAdvanced: () => void };

const SOURCE_PREFIX = "source:";
// Schriften im Einfach-Modus: serifenlos oder mit Serifen (Überschrift und Text gleich)
const FONT_CHOICES = { sans: "liberation_sans", serif: "liberation_serif" } as const;

export function SimpleDesigner({ brandId, onDiagnostics, onOpenAdvanced }: Props) {
  const t = useTranslations("documentStudio");
  const { content, protocolStructure } = useDesigner();
  const [open, setOpen] = useState<Record<Step, boolean>>({ look: true, content: true, page: false });
  // Ausgewählter Knoten (oberste Ebene) und ggf. Baustein des Protokollinhalts («source:…»)
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const names = useBlockNames();

  const titlePageIds = useMemo(() => new Set(content.title_page.children.map((node) => node.id)), [content.title_page.children]);
  const protocolNode = content.body.find(isProtocolContent) ?? null;

  function sourceTitle(key: string): string | null {
    for (const element of protocolStructure?.elements ?? []) {
      const block = element.blocks.find((item) => item.key === key);
      if (block) return block.title || element.title;
    }
    return null;
  }

  function labelFor(nodeId: string): string | null {
    if (nodeId.startsWith(SOURCE_PREFIX)) return sourceTitle(nodeId.slice(SOURCE_PREFIX.length)) ?? (protocolNode ? names.label(protocolNode) : null);
    if (titlePageIds.has(nodeId)) return t("simple.titlePage");
    const node = content.body.find((item) => item.id === nodeId);
    return node ? names.label(node) : null;
  }

  function reveal(nodeId: string) {
    window.setTimeout(() => {
      const row = panelRef.current?.querySelector<HTMLElement>(`[data-simple-node="${CSS.escape(nodeId)}"]`);
      row?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
    }, 0);
  }

  function pick(nodeId: string) {
    if (titlePageIds.has(nodeId)) {
      setOpen((current) => ({ ...current, page: true }));
      return;
    }
    if (nodeId.startsWith(SOURCE_PREFIX)) {
      if (!protocolNode) return;
      setSelected(protocolNode.id);
      setSelectedSource(nodeId.slice(SOURCE_PREFIX.length));
      setOpen((current) => ({ ...current, content: true }));
      reveal(protocolNode.id);
      return;
    }
    setSelected(nodeId);
    setSelectedSource(null);
    setOpen((current) => ({ ...current, content: true }));
    reveal(nodeId);
  }

  const steps: { key: Step; title: string; summary: string; body: ReactNode }[] = [
    { key: "look", title: t("simple.step.look"), summary: useLookSummary(), body: <LookStep /> },
    {
      key: "content",
      title: t("simple.step.content"),
      summary: t("simple.contentSummary", { visible: content.body.filter((node) => node.enabled !== false).length, total: content.body.length }),
      body: (
        <ContentStep
          selected={selected}
          selectedSource={selectedSource}
          onSelect={(id) => {
            setSelected((current) => (current === id ? null : id));
            setSelectedSource(null);
          }}
          onOpenAdvanced={onOpenAdvanced}
        />
      ),
    },
    { key: "page", title: t("simple.step.page"), summary: usePageSummary(), body: <PageStep /> },
  ];

  return (
    <div className="studio-simple">
      <aside ref={panelRef} className="studio-simple-panel" aria-label={t("simple.title")}>
        {steps.map((step, index) => (
          <section key={step.key} className="studio-simple-step">
            <button
              type="button"
              className="studio-simple-step-head"
              aria-expanded={open[step.key]}
              onClick={() => setOpen((current) => ({ ...current, [step.key]: !current[step.key] }))}
            >
              <span className={open[step.key] ? "studio-simple-step-number studio-simple-step-number-open" : "studio-simple-step-number"}>{index + 1}</span>
              <span className="studio-simple-step-text">
                <span className="studio-simple-step-title">{step.title}</span>
                <span className="studio-simple-step-summary">{step.summary}</span>
              </span>
              <span aria-hidden="true">{open[step.key] ? "⌃" : "⌄"}</span>
            </button>
            {open[step.key] ? <div className="studio-simple-step-body">{step.body}</div> : null}
          </section>
        ))}
      </aside>
      <main className="studio-simple-preview" aria-label={t("designer.workspace")}>
        <PreviewPanel brandId={brandId} onDiagnostics={onDiagnostics} picking={{ selected: selectedSource ? `${SOURCE_PREFIX}${selectedSource}` : selected, onPick: pick, labelFor }} />
      </main>
    </div>
  );
}

// ── Namen ───────────────────────────────────────────────────────────────────

function useBlockNames() {
  const t = useTranslations("documentStudio");
  const { catalog } = useDesigner();
  return useMemo(
    () => ({
      block: (node: TemplateNode) => matchSimpleBlock(catalog.simple, node),
      label: (node: TemplateNode) => {
        const block = matchSimpleBlock(catalog.simple, node);
        if (node.name) return node.name;
        // Abschnitte und Kästen mit Titel heissen wie ihr Titel
        const title = plainText(node.title as TextContent | undefined);
        if (title) return title;
        if (block && block.key !== "group" && block.key !== "data") return t(`simple.block.${block.key}.name`);
        if (node.type === "data_block") return t(`component.${String(node.component)}`);
        return t(`nodeType.${node.type}`);
      },
    }),
    [catalog.simple, t]
  );
}

// ── Schritt 1: Aussehen ─────────────────────────────────────────────────────

function useOverrides() {
  const { content, setContent } = useDesigner();
  const overrides: BrandOverrides = content.settings.brand_overrides ?? {};
  const set = (patch: Partial<BrandOverrides>, key: string) =>
    setContent({ ...content, settings: { ...content.settings, brand_overrides: { ...overrides, ...patch } } }, `simple:overrides:${key}`);
  return { overrides, set };
}

function useLookSummary(): string {
  const t = useTranslations("documentStudio");
  const { overrides } = useOverrides();
  const style = overrides.appearance_base ? t(`appearance.base.${overrides.appearance_base}.name`) : t("simple.look.styleFromBrandShort");
  const font = overrides.body_font === FONT_CHOICES.serif ? t("simple.look.fontSerif") : overrides.body_font === FONT_CHOICES.sans ? t("simple.look.fontSans") : t("simple.look.fontFromBrandShort");
  return `${style} · ${font}`;
}

function LookStep() {
  const t = useTranslations("documentStudio");
  const { catalog, brand, assets, setAssets, capabilities } = useDesigner();
  const { overrides, set } = useOverrides();
  const [logoPicker, setLogoPicker] = useState(false);
  const brandPrimary = brand.tokens.colors.primary;
  const primary = overrides.primary ?? brandPrimary;
  // Vorschläge: Farben des Profils, ohne Doppelte
  const swatches = [brandPrimary, brand.tokens.colors.secondary, brand.tokens.colors.accent, brand.tokens.colors.heading]
    .map((value) => normalizeHex(value))
    .filter((value, index, all): value is string => value !== null && all.indexOf(value) === index);
  const setPrimary = (value: string | null) => set({ primary: value, heading: value }, "primary");
  const fontChoice = overrides.body_font === FONT_CHOICES.serif ? "serif" : overrides.body_font === FONT_CHOICES.sans ? "sans" : "";
  const logo = overrides.logo_asset_id ? assets.find((asset) => asset.id === overrides.logo_asset_id) : null;

  return (
    <div className="studio-simple-fields">
      <div className="field-stack">
        <span className="field-label">{t("simple.look.style")}</span>
        <div className="studio-variant-list studio-simple-styles" role="radiogroup" aria-label={t("simple.look.style")}>
          <button type="button" role="radio" aria-checked={!overrides.appearance_base} className={!overrides.appearance_base ? "studio-variant studio-variant-active" : "studio-variant"} onClick={() => set({ appearance_base: null }, "style")}>
            <span className="studio-variant-name">{t("simple.look.fromBrand")}</span>
            <span className="field-help">{t("simple.look.fromBrandHelp")}</span>
          </button>
          {catalog.simple.styles.map((key) => (
            <button key={key} type="button" role="radio" aria-checked={overrides.appearance_base === key} className={overrides.appearance_base === key ? "studio-variant studio-variant-active" : "studio-variant"} title={t(`appearance.base.${key}.help`)} onClick={() => set({ appearance_base: key }, "style")}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img className="studio-variant-thumb studio-simple-style-thumb" src={studioApi.exampleThumbnailUrl(key)} alt="" loading="lazy" />
              <span className="studio-variant-name">{t(`appearance.base.${key}.name`)}</span>
            </button>
          ))}
        </div>
        <span className="field-help">{overrides.appearance_base ? t(`appearance.base.${overrides.appearance_base}.help`) : t("simple.look.styleHelp")}</span>
      </div>

      <div className="field-stack">
        <span className="field-label">{t("document.logo")}</span>
        <div className="studio-inline-actions">
          <button type="button" className="button-secondary" onClick={() => setLogoPicker(true)}>
            {logo ? logo.name : overrides.logo_asset_id ? t("props.imageMissing") : t("document.logoFromBrand")}
          </button>
          {overrides.logo_asset_id && (
            <button type="button" className="button-ghost" onClick={() => set({ logo_asset_id: null }, "logo")}>
              {t("document.reset")}
            </button>
          )}
        </div>
        <AssetPicker open={logoPicker} onClose={() => setLogoPicker(false)} assets={assets} onAssetsChange={setAssets} canUpload={capabilities.manage_brand} defaultCategory="logo" onPick={(asset) => set({ logo_asset_id: asset.id }, "logo")} />
      </div>

      <div className="field-stack">
        <span className="field-label">{t("simple.look.color")}</span>
        <div className="studio-simple-swatches" role="radiogroup" aria-label={t("simple.look.color")}>
          {swatches.map((value) => {
            const active = normalizeHex(primary) === value;
            const isBrand = value === normalizeHex(brandPrimary);
            return (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={active}
                className={active ? "studio-simple-swatch studio-simple-swatch-active" : "studio-simple-swatch"}
                style={{ background: value }}
                aria-label={isBrand ? t("simple.look.colorBrand") : value}
                title={isBrand ? t("simple.look.colorBrand") : value}
                onClick={() => setPrimary(isBrand ? null : value)}
              />
            );
          })}
          <ColorInput aria-label={t("simple.look.colorCustom")} value={primary} swatches={swatches.map((value) => ({ value, label: value }))} onChange={(value) => setPrimary(value)} />
        </div>
      </div>

      <div className="field-stack">
        <span className="field-label">{t("simple.look.font")}</span>
        <div className="studio-variant-list studio-simple-fonts" role="radiogroup" aria-label={t("simple.look.font")}>
          {(["", "sans", "serif"] as const).map((choice) => (
            <button
              key={choice || "brand"}
              type="button"
              role="radio"
              aria-checked={fontChoice === choice}
              className={fontChoice === choice ? "studio-variant studio-variant-active" : "studio-variant"}
              onClick={() => {
                const font = choice ? FONT_CHOICES[choice] : null;
                set({ body_font: font, heading_font: font }, "font");
              }}
            >
              <span className={choice === "serif" ? "studio-simple-font-sample studio-simple-font-serif" : "studio-simple-font-sample"} aria-hidden="true">
                Aa
              </span>
              <span className="studio-variant-name">{choice === "serif" ? t("simple.look.fontSerif") : choice === "sans" ? t("simple.look.fontSans") : t("simple.look.fontBrand")}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Schritt 2: Inhalt ───────────────────────────────────────────────────────

function ContentStep({ selected, selectedSource, onSelect, onOpenAdvanced }: { selected: string | null; selectedSource: string | null; onSelect: (id: string) => void; onOpenAdvanced: () => void }) {
  const t = useTranslations("documentStudio");
  const { content, setContent, catalog, editable } = useDesigner();
  const names = useBlockNames();
  const confirm = useConfirm();
  const [addOpen, setAddOpen] = useState(false);
  const addRef = useRef<HTMLButtonElement | null>(null);
  const body = content.body;

  function add(key: string) {
    const entry = catalog.library.find((item) => item.key === key);
    if (!entry) return;
    const node = withFreshIds(entry.node);
    const after = selected ? body.findIndex((item) => item.id === selected) : -1;
    setContent(insertNode(content, "body", null, after >= 0 ? after + 1 : body.length, node));
    setAddOpen(false);
    onSelect(node.id);
  }

  async function remove(node: TemplateNode) {
    if (!(await confirm({ message: t("simple.removeConfirm", { name: names.label(node) }), tone: "danger", confirmLabel: t("simple.remove") }))) return;
    setContent(removeNode(content, node.id));
  }

  return (
    <div className="studio-simple-fields">
      <p className="field-help">{t("simple.contentHelp")}</p>
      <ol className="studio-simple-blocks">
        {body.map((node, index) => {
          const block = names.block(node);
          const isOpen = selected === node.id;
          const on = node.enabled !== false;
          return (
            <li key={node.id} data-simple-node={node.id} className={isOpen ? "studio-simple-block studio-simple-block-open" : "studio-simple-block"}>
              <div className="studio-simple-block-row">
                <span className="studio-simple-block-move">
                  <button type="button" className="button-icon-soft button-icon-soft-sm" aria-label={t("structure.moveUp")} disabled={!editable || index === 0} onClick={() => setContent(moveWithinParent(content, node.id, -1))}>
                    ▴
                  </button>
                  <button type="button" className="button-icon-soft button-icon-soft-sm" aria-label={t("structure.moveDown")} disabled={!editable || index === body.length - 1} onClick={() => setContent(moveWithinParent(content, node.id, 1))}>
                    ▾
                  </button>
                </span>
                <button type="button" className="studio-simple-block-name" aria-expanded={isOpen} onClick={() => onSelect(node.id)}>
                  <span className={on ? "studio-simple-block-title" : "studio-simple-block-title studio-simple-block-title-off"}>{names.label(node)}</span>
                  <span className="studio-simple-block-desc">{on ? <BlockSummary node={node} block={block} /> : t("simple.hidden")}</span>
                </button>
                <button
                  type="button"
                  role="switch"
                  aria-checked={on}
                  aria-label={t("simple.visible", { name: names.label(node) })}
                  className={on ? "studio-simple-switch studio-simple-switch-on" : "studio-simple-switch"}
                  disabled={!editable}
                  onClick={() => setContent(updateNode(content, node.id, { enabled: !on }))}
                >
                  <span className="studio-simple-switch-knob" />
                </button>
              </div>
              {isOpen ? (
                <div className="studio-simple-block-settings">
                  {block ? (
                    block.settings.map((setting) => <SettingField key={setting.key} node={node} block={block} setting={setting} />)
                  ) : (
                    <p className="field-help">{t("simple.custom")}</p>
                  )}
                  {block?.key === "group" || !block ? (
                    <button type="button" className="button-secondary" onClick={onOpenAdvanced}>
                      {t("simple.openAdvanced")}
                    </button>
                  ) : null}
                  {isProtocolContent(node) && selectedSource ? <SourceAppearance node={node} sourceKey={selectedSource} /> : null}
                  {editable && !node.locked ? (
                    <button type="button" className="button-ghost studio-simple-remove" onClick={() => void remove(node)}>
                      {t("simple.remove")}
                    </button>
                  ) : null}
                </div>
              ) : null}
            </li>
          );
        })}
      </ol>
      {editable && (
        <>
          <button ref={addRef} type="button" className="button-secondary studio-simple-add" aria-expanded={addOpen} onClick={() => setAddOpen((current) => !current)}>
            {t("simple.add")}
          </button>
          <Popover open={addOpen} onOpenChange={setAddOpen} anchorRef={addRef} className="studio-simple-add-menu">
            {catalog.simple.add.map((key) => (
              <button key={key} type="button" role="menuitem" className="studio-simple-add-option" onClick={() => add(key)}>
                <span className="studio-simple-add-name">{t(`library.entry.${key}`)}</span>
                <span className="field-help">{t(`library.help.${key}`)}</span>
              </button>
            ))}
          </Popover>
        </>
      )}
    </div>
  );
}

function BlockSummary({ node, block }: { node: TemplateNode; block: SimpleBlock | null }) {
  const t = useTranslations("documentStudio");
  const { catalog } = useDesigner();
  if (!block) return <>{t("simple.customShort")}</>;
  const text = block.settings.find((setting): setting is Extract<SimpleSetting, { kind: "text" | "markdown" }> => setting.kind === "text" || setting.kind === "markdown");
  if (text) {
    const value = text.kind === "markdown" ? String(getPath(node, text.path) ?? "") : plainText(getPath(node, text.path) as never);
    if (value) return <>{value.length > 60 ? `${value.slice(0, 60)}…` : value}</>;
  }
  const preset = conditionPreset(catalog.simple, node);
  if (preset && preset !== "custom") return <>{t(`simple.condition.${preset}`)}</>;
  return <>{t(`simple.block.${block.key}.help`)}</>;
}

function SettingField({ node, block, setting }: { node: TemplateNode; block: SimpleBlock; setting: SimpleSetting }) {
  const t = useTranslations("documentStudio");
  const { content, setContent, catalog, brand, assets, setAssets, capabilities, editable } = useDesigner();
  const [picker, setPicker] = useState(false);
  const label = (suffix = "label") => t(`simple.setting.${block.key}.${setting.key}.${suffix}`);
  const replace = (next: TemplateNode, mergeKey?: string) => setContent(updateNode(content, node.id, () => next), mergeKey ? `simple:${node.id}:${mergeKey}` : undefined);

  switch (setting.kind) {
    case "toggle":
      return (
        <label className="studio-simple-check">
          <input type="checkbox" checked={toggleValue(node, setting)} disabled={!editable} onChange={(event) => replace(setPath(node, setting.path, event.target.checked))} />
          <span>
            {label()}
            <span className="field-help">{label("help")}</span>
          </span>
        </label>
      );
    case "variant": {
      const inherited = brandVariant(brand.tokens, catalog.appearance, setting.appearance);
      return (
        <label className="field-stack">
          <span className="field-label">{label()}</span>
          <Select value={variantValue(node, setting.appearance)} disabled={!editable} onChange={(event) => replace(setVariant(node, setting.appearance, event.target.value))}>
            <option value="">{t("simple.variantInherit", { value: t(`appearance.variant.${setting.appearance}.${inherited}`) })}</option>
            {setting.options.map((option) => (
              <option key={option} value={option}>
                {t(`appearance.variant.${setting.appearance}.${option}`)}
              </option>
            ))}
          </Select>
        </label>
      );
    }
    case "text": {
      const value = plainText(getPath(node, setting.path) as never);
      if (value === null) return <p className="field-help">{t("simple.textWithFields")}</p>;
      const multiline = node.type === "text" && (node.role ?? "paragraph") === "paragraph";
      return (
        <label className="field-stack">
          <span className="field-label">{label()}</span>
          {multiline ? (
            <textarea rows={3} value={value} disabled={!editable} onChange={(event) => replace(setPath(node, setting.path, textContent(event.target.value)), setting.key)} />
          ) : (
            <input value={value} disabled={!editable} onChange={(event) => replace(setPath(node, setting.path, textContent(event.target.value)), setting.key)} />
          )}
        </label>
      );
    }
    case "markdown":
      return (
        <label className="field-stack">
          <span className="field-label">{label()}</span>
          <textarea rows={5} value={String(getPath(node, setting.path) ?? "")} disabled={!editable} onChange={(event) => replace(setPath(node, setting.path, event.target.value), setting.key)} />
          <span className="field-help">{label("help")}</span>
        </label>
      );
    case "names": {
      const fields = (getPath(node, setting.path) as { label?: string | null; name?: string | null }[] | undefined) ?? [{}, {}];
      const write = (next: typeof fields) => replace(setPath(node, setting.path, next), setting.key);
      return (
        <div className="field-stack">
          <span className="field-label">{label()}</span>
          {fields.map((field, index) => (
            <div key={index} className="studio-simple-name-row">
              <input value={field.label ?? ""} placeholder={label("placeholder")} aria-label={t("simple.signatureLabel", { number: index + 1 })} disabled={!editable} onChange={(event) => write(fields.map((item, itemIndex) => (itemIndex === index ? { ...item, label: event.target.value || null } : item)))} />
              <button type="button" className="button-icon-soft button-icon-soft-sm" aria-label={t("simple.signatureRemove", { number: index + 1 })} disabled={!editable || fields.length <= 1} onClick={() => write(fields.filter((_, itemIndex) => itemIndex !== index))}>
                ✕
              </button>
            </div>
          ))}
          <button type="button" className="button-ghost studio-simple-inline-add" disabled={!editable || fields.length >= 12} onClick={() => write([...fields, { label: null, name: null }])}>
            {t("simple.signatureAdd")}
          </button>
        </div>
      );
    }
    case "multi": {
      const current = (getPath(node, setting.path) as string[] | undefined) ?? setting.default;
      return (
        <fieldset className="studio-simple-multi">
          <legend className="field-label">{label()}</legend>
          {setting.options.map((option) => (
            <label key={option} className="studio-simple-check">
              <input
                type="checkbox"
                checked={current.includes(option)}
                disabled={!editable}
                onChange={(event) => replace(setPath(node, setting.path, event.target.checked ? setting.options.filter((item) => item === option || current.includes(item)) : current.filter((item) => item !== option)))}
              />
              <span>{t(`metadataField.${option}`)}</span>
            </label>
          ))}
        </fieldset>
      );
    }
    case "image": {
      const source = getPath(node, setting.path) as { kind?: string; asset_id?: string | null; path?: string } | undefined;
      const asset = source?.kind === "asset" ? assets.find((item) => item.id === source.asset_id) : null;
      return (
        <div className="field-stack">
          <span className="field-label">{label()}</span>
          <button type="button" className="button-secondary" disabled={!editable} onClick={() => setPicker(true)}>
            {asset ? asset.name : source?.kind === "binding" ? t(`binding.${String(source.path ?? "").replace(/\./g, "_")}`) : t("simple.imageChoose")}
          </button>
          <AssetPicker open={picker} onClose={() => setPicker(false)} assets={assets} onAssetsChange={setAssets} canUpload={capabilities.manage_brand} defaultCategory="image" onPick={(picked) => replace(setPath(node, setting.path, { kind: "asset", asset_id: picked.id }))} />
        </div>
      );
    }
    case "condition": {
      const preset = conditionPreset(catalog.simple, node);
      if (preset === "custom") return <p className="field-help">{t("simple.conditionCustom")}</p>;
      if (!preset) return null;
      return (
        <label className="studio-simple-check">
          <input type="checkbox" checked={!!node.visible_if} disabled={!editable} onChange={(event) => replace({ ...node, visible_if: event.target.checked ? catalog.simple.conditions[preset] : null })} />
          <span>{t(`simple.condition.${preset}`)}</span>
        </label>
      );
    }
  }
}

/** Darstellung eines einzelnen Bausteins des Protokollinhalts (Klick in der Vorschau). */
function SourceAppearance({ node, sourceKey }: { node: TemplateNode; sourceKey: string }) {
  const t = useTranslations("documentStudio");
  const { content, setContent, catalog, brand, protocolStructure, editable } = useDesigner();
  const block = protocolStructure?.elements.flatMap((element) => element.blocks.map((item) => ({ ...item, element: element.title }))).find((item) => item.key === sourceKey);
  if (!block || !catalog.appearance || block.appearance_kinds.length === 0) return null;
  const overrides = (node.block_appearance as Record<string, AppearanceOverrides> | undefined) ?? {};
  const nodeAppearance = node.appearance as AppearanceOverrides | undefined;
  return (
    <div className="studio-simple-source">
      <span className="field-label">{t("simple.sourceTitle", { name: block.title || block.element })}</span>
      <AppearanceEditor
        catalog={catalog.appearance}
        kinds={block.appearance_kinds}
        value={overrides[sourceKey]}
        inherited={(kind) => nodeAppearance?.[kind]?.variant ?? brandVariant(brand.tokens, catalog.appearance, kind)}
        inheritLabel={(value) => t("blockAppearance.inherit", { value })}
        disabled={!editable}
        onChange={(value) => {
          const all = { ...overrides };
          if (Object.keys(value).length > 0) all[sourceKey] = value;
          else delete all[sourceKey];
          setContent(updateNode(content, node.id, { block_appearance: all }), `simple:${node.id}:source:${sourceKey}`);
        }}
      />
    </div>
  );
}

// ── Schritt 3: Seite ────────────────────────────────────────────────────────

/** Titelseite sichtbar: eingeschaltet und ohne Bedingung bzw. mit der Bedingung der
 * mitgelieferten Vorlagen («Titelseite laut Profil»), die das Profil erfüllt. Der Schalter
 * entfernt die Bedingung: danach gilt er für diese Vorlage allein. */
function titlePageVisible(content: TemplateContent, brandTitlePage: boolean): boolean {
  if (!content.title_page.enabled) return false;
  const condition = content.title_page.visible_if as { op?: string; path?: string } | null | undefined;
  if (!condition) return true;
  return condition.path === "brand.title_page" && brandTitlePage;
}

type HeaderFooterKey = "header_show_logo" | "header_show_title" | "header_show_date" | "footer_show_pages" | "footer_show_number";

function usePageSummary(): string {
  const t = useTranslations("documentStudio");
  const { content } = useDesigner();
  const { brand } = useDesigner();
  return [titlePageVisible(content, brand.tokens.layout.title_page) ? t("simple.page.withTitlePage") : t("simple.page.withoutTitlePage"), content.page.orientation === "landscape" ? t("simple.page.landscape") : t("simple.page.portrait")].join(" · ");
}

function PageStep() {
  const t = useTranslations("documentStudio");
  const { content, setContent, brand, editable } = useDesigner();
  const { overrides, set } = useOverrides();
  const headerFooter = brand.tokens.layout.header_footer as Record<string, unknown>;
  const value = (key: HeaderFooterKey) => overrides[key] ?? headerFooter[key] !== false;
  const titlePageOn = titlePageVisible(content, brand.tokens.layout.title_page);
  const setTitlePage = (on: boolean) => setContent({ ...content, title_page: { ...content.title_page, enabled: on, visible_if: null } } as TemplateContent);
  const groups: { title: string; items: { key: HeaderFooterKey; label: string }[] }[] = [
    {
      title: t("simple.page.header"),
      items: [
        { key: "header_show_logo", label: t("simple.page.headerLogo") },
        { key: "header_show_title", label: t("simple.page.headerTitle") },
        { key: "header_show_date", label: t("simple.page.headerDate") },
      ],
    },
    {
      title: t("simple.page.footer"),
      items: [
        { key: "footer_show_pages", label: t("simple.page.footerPages") },
        { key: "footer_show_number", label: t("simple.page.footerNumber") },
      ],
    },
  ];
  return (
    <div className="studio-simple-fields">
      <SwitchRow label={t("simple.page.titlePage")} help={t("simple.page.titlePageHelp")} on={titlePageOn} disabled={!editable} onToggle={() => setTitlePage(!titlePageOn)} />
      {groups.map((group) => (
        <div key={group.title} className="field-stack">
          <span className="field-label">{group.title}</span>
          <div className="studio-simple-switch-list">
            {group.items.map((item) => (
              <SwitchRow key={item.key} label={item.label} on={value(item.key)} disabled={!editable} onToggle={() => set({ [item.key]: !value(item.key) }, item.key)} />
            ))}
          </div>
        </div>
      ))}
      <label className="field-stack">
        <span className="field-label">{t("simple.page.footerText")}</span>
        <input value={overrides.footer_text ?? String(headerFooter.footer_text ?? "")} maxLength={300} disabled={!editable} onChange={(event) => set({ footer_text: event.target.value }, "footerText")} />
      </label>
      <div className="field-stack">
        <span className="field-label">{t("simple.page.format")}</span>
        <div className="studio-segmented" role="radiogroup" aria-label={t("simple.page.format")}>
          {(["portrait", "landscape"] as const).map((orientation) => (
            <button key={orientation} type="button" role="radio" aria-checked={content.page.orientation === orientation} disabled={!editable} className={content.page.orientation === orientation ? "button-toggle button-toggle-active" : "button-toggle"} onClick={() => setContent({ ...content, page: { ...content.page, orientation } })}>
              {t(`simple.page.${orientation}`)}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function SwitchRow({ label, help, on, disabled, onToggle }: { label: string; help?: string; on: boolean; disabled?: boolean; onToggle: () => void }) {
  return (
    <div className="studio-simple-switch-row">
      <span className="studio-simple-switch-text">
        <span>{label}</span>
        {help ? <span className="field-help">{help}</span> : null}
      </span>
      <button type="button" role="switch" aria-checked={on} aria-label={label} className={on ? "studio-simple-switch studio-simple-switch-on" : "studio-simple-switch"} disabled={disabled} onClick={onToggle}>
        <span className="studio-simple-switch-knob" />
      </button>
    </div>
  );
}
