"use client";

// Einstellungen des ganzen Dokuments (wenn kein Element ausgewählt ist): Seitenformat, Ränder,
// Spalten, Seitenvorlagen (Kopf/Fuss, abweichende erste Seite), Titelseite, Nummerierung,
// Sprache, Brand-Profil und - für den Modus «Einfach» - Logo, Farben, Schriften sowie die
// Abschnitte zum Ein-/Ausschalten und Sortieren.

import { useState } from "react";
import { useTranslations } from "next-intl";

import { AssetPicker } from "@/components/documents/asset-picker";
import { modeAllows, useDesigner } from "@/components/documents/designer/designer-context";
import { CheckField, ColorField, ConditionEditor, Field, NumberField, SpacingField } from "@/components/documents/designer/fields";
import { locales } from "@/i18n/locale-config.generated";
import { bindingLabel } from "@/components/documents/studio-labels";
import { BrandOverrides, inlineSummary, moveWithinParent, newNodeId, PageMaster, PageSetup, TemplateContent, TextContent, updateNode } from "@/lib/documents/layout";

type Props = {
  brandId: string | null;
  brandMode: "follow" | "pinned";
  onBrandChange: (brandId: string | null) => void;
  onBrandModeChange: (mode: "follow" | "pinned") => void;
  // Profilwechsel erfordert bei veröffentlichten Vorlagen das Veröffentlichungsrecht
  brandLocked?: boolean;
};

const FONT_KEYS = ["inter", "liberation_sans", "liberation_serif", "noto_sans"];

function Section({ title, children, open = false }: { title: string; children: React.ReactNode; open?: boolean }) {
  return (
    <details className="studio-prop-group" open={open}>
      <summary className="studio-prop-summary">{title}</summary>
      <div className="studio-prop-body">{children}</div>
    </details>
  );
}

export function DocumentPanel({ brandId, brandMode, onBrandChange, onBrandModeChange, brandLocked = false }: Props) {
  const t = useTranslations("documentStudio");
  const tPdf = useTranslations("documentPdf");
  const { content, setContent, mode, brands, assets, setAssets, capabilities, editable, select } = useDesigner();
  const [logoPicker, setLogoPicker] = useState(false);
  const page = content.page;
  const settings = content.settings;
  const overrides = settings.brand_overrides ?? {};
  const setPage = (patch: Partial<PageSetup>, key: string) => setContent({ ...content, page: { ...page, ...patch } }, `page:${key}`);
  const setSettings = (patch: Partial<TemplateContent["settings"]>, key: string) => setContent({ ...content, settings: { ...settings, ...patch } }, `settings:${key}`);
  const setOverrides = (patch: Partial<BrandOverrides>, key: string) => setSettings({ brand_overrides: { ...overrides, ...patch } }, `overrides:${key}`);
  const setMaster = (id: string, patch: Partial<PageMaster>) => setContent({ ...content, masters: content.masters.map((master) => (master.id === id ? { ...master, ...patch } : master)) });

  const sections = content.body;
  const label = (node: (typeof sections)[number]) =>
    node.name ||
    inlineSummary((node.title ?? node.content) as TextContent | undefined, (key) => (tPdf.has(key) ? tPdf(key) : key), (path) => bindingLabel(t, path)) ||
    (node.type === "data_block" ? t(`component.${node.component as string}`) : t(`nodeType.${node.type}`));

  return (
    <div className="studio-properties" aria-label={t("document.title")}>
      <div className="studio-prop-header">
        <div>
          <span className="studio-prop-type">{t("document.title")}</span>
          <p className="field-help">{t("document.help")}</p>
        </div>
      </div>
      <fieldset className="studio-prop-fieldset" disabled={!editable}>
        <Section title={t("document.sections")} open>
          <p className="field-help">{t("document.sectionsHelp")}</p>
          <ol className="studio-section-list">
            {sections.map((node, index) => (
              <li key={node.id} className={node.enabled === false ? "studio-section-item studio-section-item-off" : "studio-section-item"}>
                <input type="checkbox" checked={node.enabled !== false} aria-label={t("document.sectionEnabled", { name: label(node) })} onChange={(event) => setContent(updateNode(content, node.id, { enabled: event.target.checked }))} />
                <button type="button" className="studio-section-name" onClick={() => select(node.id)}>
                  {label(node)}
                </button>
                <button type="button" className="button-icon-soft button-icon-soft-sm" aria-label={t("structure.moveUp")} disabled={index === 0} onClick={() => setContent(moveWithinParent(content, node.id, -1))}>
                  ↑
                </button>
                <button type="button" className="button-icon-soft button-icon-soft-sm" aria-label={t("structure.moveDown")} disabled={index === sections.length - 1} onClick={() => setContent(moveWithinParent(content, node.id, 1))}>
                  ↓
                </button>
              </li>
            ))}
          </ol>
        </Section>

        <Section title={t("document.design")} open={mode === "simple"}>
          <Field label={t("document.brand")} help={brandLocked ? t("document.brandLocked") : t("document.brandHelp")}>
            <select value={brandId ?? ""} disabled={brandLocked} onChange={(event) => onBrandChange(event.target.value || null)}>
              <option value="">{t("document.brandDefault")}</option>
              {brands.map((brand) => (
                <option key={brand.id} value={brand.id}>
                  {brand.name}
                </option>
              ))}
            </select>
          </Field>
          {modeAllows(mode, "advanced") && (
            <Field label={t("document.brandMode")} help={t("document.brandModeHelp")}>
              <select value={brandMode} onChange={(event) => onBrandModeChange(event.target.value as "follow" | "pinned")}>
                <option value="follow">{t("document.brandFollow")}</option>
                <option value="pinned">{t("document.brandPinned")}</option>
              </select>
            </Field>
          )}
          <div className="field-stack">
            <span className="field-label">{t("document.logo")}</span>
            <div className="studio-inline-actions">
              <button type="button" className="button-secondary" onClick={() => setLogoPicker(true)}>
                {overrides.logo_asset_id ? assets.find((asset) => asset.id === overrides.logo_asset_id)?.name ?? t("props.imageMissing") : t("document.logoFromBrand")}
              </button>
              {overrides.logo_asset_id && (
                <button type="button" className="button-ghost" onClick={() => setOverrides({ logo_asset_id: null }, "logo")}>
                  {t("document.reset")}
                </button>
              )}
            </div>
          </div>
          <ColorOverride label={t("document.primary")} value={overrides.primary} onChange={(primary) => setOverrides({ primary }, "primary")} />
          <ColorOverride label={t("document.secondary")} value={overrides.secondary} onChange={(secondary) => setOverrides({ secondary }, "secondary")} />
          <ColorOverride label={t("document.headingColor")} value={overrides.heading} onChange={(heading) => setOverrides({ heading }, "heading")} />
          <Field label={t("document.bodyFont")}>
            <select value={overrides.body_font ?? ""} onChange={(event) => setOverrides({ body_font: event.target.value || null }, "bodyFont")}>
              <option value="">{t("document.fromBrand")}</option>
              {FONT_KEYS.map((key) => (
                <option key={key} value={key}>
                  {t(`font.${key}`)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("document.headingFont")}>
            <select value={overrides.heading_font ?? ""} onChange={(event) => setOverrides({ heading_font: event.target.value || null }, "headingFont")}>
              <option value="">{t("document.fromBrand")}</option>
              {FONT_KEYS.map((key) => (
                <option key={key} value={key}>
                  {t(`font.${key}`)}
                </option>
              ))}
            </select>
          </Field>
          <AssetPicker open={logoPicker} onClose={() => setLogoPicker(false)} assets={assets} onAssetsChange={setAssets} canUpload={capabilities.manage_brand} defaultCategory="logo" onPick={(asset) => setOverrides({ logo_asset_id: asset.id }, "logo")} />
        </Section>

        <Section title={t("document.page")} open={mode !== "simple"}>
          <Field label={t("document.size")}>
            <select value={page.size} onChange={(event) => setPage({ size: event.target.value as PageSetup["size"] }, "size")}>
              {["A4", "A5", "A3", "Letter", "Legal", ...(modeAllows(mode, "expert") ? ["custom"] : [])].map((size) => (
                <option key={size} value={size}>
                  {t(`document.sizeValue.${size}`)}
                </option>
              ))}
            </select>
          </Field>
          {page.size === "custom" && (
            <div className="studio-field-grid">
              <NumberField label={t("document.width")} value={page.width} min={50} max={1200} suffix={t("brand.unitMm")} onChange={(width) => setPage({ width }, "width")} />
              <NumberField label={t("document.height")} value={page.height} min={50} max={1200} suffix={t("brand.unitMm")} onChange={(height) => setPage({ height }, "height")} />
            </div>
          )}
          <Field label={t("document.orientation")}>
            <select value={page.orientation} onChange={(event) => setPage({ orientation: event.target.value as PageSetup["orientation"] }, "orientation")}>
              <option value="portrait">{t("document.portrait")}</option>
              <option value="landscape">{t("document.landscape")}</option>
            </select>
          </Field>
          {modeAllows(mode, "advanced") && <SpacingField label={t("document.margins")} value={page.margins} onChange={(margins) => setPage({ margins }, "margins")} />}
          {modeAllows(mode, "advanced") && (
            <div className="studio-field-grid">
              <NumberField label={t("document.columns")} value={page.columns} min={1} max={3} onChange={(columns) => setPage({ columns }, "columns")} />
              <NumberField label={t("document.columnGap")} value={page.column_gap} min={0} max={40} suffix={t("brand.unitMm")} onChange={(column_gap) => setPage({ column_gap }, "columnGap")} />
            </div>
          )}
        </Section>

        <Section title={t("document.titlePage")}>
          <CheckField label={t("document.titlePageEnabled")} checked={content.title_page.enabled} onChange={(enabled) => setContent({ ...content, title_page: { ...content.title_page, enabled } })} />
          {content.title_page.enabled && modeAllows(mode, "advanced") && (
            <>
              <ColorField label={t("document.titlePageBackground")} value={content.title_page.background} onChange={(background) => setContent({ ...content, title_page: { ...content.title_page, background } })} />
              <ConditionEditor value={content.title_page.visible_if ?? null} onChange={(visible_if) => setContent({ ...content, title_page: { ...content.title_page, visible_if } })} />
            </>
          )}
        </Section>

        {modeAllows(mode, "advanced") && (
          <Section title={t("document.masters")}>
            <p className="field-help">{t("document.mastersHelp")}</p>
            {content.masters.map((master) => (
              <fieldset key={master.id} className="studio-fieldset">
                <legend className="field-label">{master.name || t("document.masterName", { id: master.id })}</legend>
                {modeAllows(mode, "expert") && (
                  <>
                    <Field label={t("document.masterLabel")}>
                      <input value={master.name ?? ""} maxLength={120} onChange={(event) => setMaster(master.id, { name: event.target.value })} />
                    </Field>
                    <Field label={t("document.orientation")}>
                      <select value={master.orientation ?? ""} onChange={(event) => setMaster(master.id, { orientation: (event.target.value || null) as PageMaster["orientation"] })}>
                        <option value="">{t("document.asPage")}</option>
                        <option value="portrait">{t("document.portrait")}</option>
                        <option value="landscape">{t("document.landscape")}</option>
                      </select>
                    </Field>
                  </>
                )}
                <CheckField label={t("document.hasHeader")} checked={!!master.header} onChange={(checked) => setMaster(master.id, { header: checked ? { id: newNodeId(), type: "header", children: [] } : null })} />
                <CheckField label={t("document.hasFooter")} checked={!!master.footer} onChange={(checked) => setMaster(master.id, { footer: checked ? { id: newNodeId(), type: "footer", children: [] } : null })} />
              </fieldset>
            ))}
            {modeAllows(mode, "expert") && (
              <>
                <button type="button" className="button-secondary button-ghost" onClick={() => setContent({ ...content, masters: [...content.masters, { id: newNodeId(), name: t("document.newMaster"), header: null, footer: null, background: [] }] })}>
                  {t("document.addMaster")}
                </button>
                <Field label={t("document.firstPageMaster")} help={t("document.firstPageMasterHelp")}>
                  <select value={settings.first_page_master ?? ""} onChange={(event) => setSettings({ first_page_master: event.target.value || null }, "firstPage")}>
                    <option value="">{t("document.sameAsOthers")}</option>
                    {content.masters.map((master) => (
                      <option key={master.id} value={master.id}>
                        {master.name || master.id}
                      </option>
                    ))}
                  </select>
                </Field>
              </>
            )}
          </Section>
        )}

        <Section title={t("document.settings")}>
          <Field label={t("document.numbering")}>
            <select value={settings.heading_numbering === null || settings.heading_numbering === undefined ? "" : settings.heading_numbering ? "on" : "off"} onChange={(event) => setSettings({ heading_numbering: event.target.value === "" ? null : event.target.value === "on" }, "numbering")}>
              <option value="">{t("document.fromBrand")}</option>
              <option value="on">{t("document.on")}</option>
              <option value="off">{t("document.off")}</option>
            </select>
          </Field>
          <Field label={t("document.language")} help={t("document.languageHelp")}>
            <select value={settings.language ?? ""} onChange={(event) => setSettings({ language: event.target.value || null }, "language")}>
              <option value="">{t("document.languageExport")}</option>
              {locales.map((code) => (
                <option key={code} value={code}>
                  {t(`language.${code}`)}
                </option>
              ))}
            </select>
          </Field>
          <CheckField label={t("document.autoVerify")} help={t("document.autoVerifyHelp")} checked={settings.auto_verify_note} onChange={(auto_verify_note) => setSettings({ auto_verify_note }, "autoVerify")} />
          {modeAllows(mode, "advanced") && (
            <>
              <CheckField label={t("document.justify")} checked={settings.justify} onChange={(justify) => setSettings({ justify }, "justify")} />
              <CheckField label={t("document.hyphenate")} checked={settings.hyphenate} onChange={(hyphenate) => setSettings({ hyphenate }, "hyphenate")} />
            </>
          )}
        </Section>
      </fieldset>
    </div>
  );
}

function ColorOverride({ label, value, onChange }: { label: string; value: string | null | undefined; onChange: (value: string | null) => void }) {
  const t = useTranslations("documentStudio");
  return (
    <div className="field-stack">
      <span className="field-label">{label}</span>
      <div className="studio-color-custom">
        <input type="color" aria-label={label} value={value ?? "#000000"} /* design-ok: Dokumentfarbe (Daten) */ onChange={(event) => onChange(event.target.value.toUpperCase())} />
        <span className="field-help">{value ?? t("document.fromBrand")}</span>
        {value && (
          <button type="button" className="button-ghost" onClick={() => onChange(null)}>
            {t("document.reset")}
          </button>
        )}
      </div>
    </div>
  );
}
