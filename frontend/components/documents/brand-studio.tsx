"use client";

// Brand Studio: Corporate Design des Mandanten. Mehrere Brand-Profile, eines ist Standard.
// Farben, Typografie (inkl. eigener Schriften), Assets (Logo, Briefkopf, Hintergrund,
// Wasserzeichen, eigene Bilder), Layoutvorgaben, Kopf/Fuss, Organisation und Prüfvermerk.
// Jede gespeicherte Änderung ist eine neue, unveränderliche Revision; Exporte merken sich die
// verwendete Revision. Die Vorschau rendert ein Beispieldokument mit den ungespeicherten Werten.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { AppearanceEditor } from "@/components/documents/appearance-editor";
import { AssetPicker } from "@/components/documents/asset-picker";
import { ActionMenu } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { locales } from "@/i18n/locale-config.generated";
import { ApiError } from "@/lib/api/client";
import { apiErrorMessage, AppearanceCatalog, Brand, BrandRevision, Capabilities, DocumentAsset, previewDocument, studioApi } from "@/lib/documents/api";
import { baseVariant, DEFAULT_APPEARANCE_BASE } from "@/lib/documents/appearance";
import { DERIVED_COLOR_KEYS, deriveBrandColors } from "@/lib/documents/brand-colors";
import { BrandTokens } from "@/lib/documents/layout";
import { formatDateTime } from "@/lib/utils/format";
import { Select } from "@/components/ui/select";
import { ColorInput, normalizeHex } from "@/components/ui/color-input";

const PREVIEW_DEBOUNCE_MS = 500;
// Dokumente der Vorschau: jeweils die Vorlage, die der Verein für diesen Typ verwendet
const PREVIEW_TYPES = ["protocol", "invitation", "attendance"] as const;
type PreviewType = (typeof PREVIEW_TYPES)[number];
// Einfache Ansicht: nur Haupt- und Zweitfarbe, alles andere unter «Erweiterte Optionen»
const BASE_COLOR_KEYS = ["primary", "secondary"] as const;
const COLOR_KEYS = ["accent", "accent_2", "heading", "text", "muted", "background", "surface", "border", "success", "warning", "danger", "info", "watermark", "table_header_background", "table_header_text", "table_zebra"];
const FONT_KEYS = ["inter", "liberation_sans", "liberation_serif", "noto_sans"];
const ASSET_ROLES = ["logo", "logo_alt", "letterhead", "background", "watermark", "footer_image"] as const;
const ADVANCED_ASSET_ROLES = ASSET_ROLES.filter((role) => role !== "logo");
const SIZE_KEYS = ["base_size", "size_title", "size_subtitle", "size_h1", "size_h2", "size_h3", "size_small"] as const;
const HEADER_FOOTER_FLAGS = ["header_show_logo", "header_show_title", "header_show_date", "header_line", "footer_show_number", "footer_show_pages", "footer_line"];
const DOCUMENT_DEFAULTS = ["title_page", "toc", "heading_numbering", "show_metadata", "watermark_draft"] as const;
// Auswahl-Optionen der Darstellung im Dokument (brand.BrandLayout)
const LAYOUT_CHOICES = {
  heading_number_style: ["plain", "accent", "badge", "paragraph"],
  responsible_display: ["title", "right", "below"],
  empty_blocks: ["note", "hide"],
} as const;
type LayoutChoice = keyof typeof LAYOUT_CHOICES;

type Props = { capabilities: Capabilities };

function Section({ title, children, open = false, className = "studio-brand-section" }: { title: string; children: React.ReactNode; open?: boolean; className?: string }) {
  return (
    <details className={`studio-prop-group ${className}`} open={open}>
      <summary className="studio-prop-summary">{title}</summary>
      <div className="studio-prop-body">{children}</div>
    </details>
  );
}

export function BrandStudio({ capabilities }: Props) {
  const t = useTranslations("documentStudio");
  const locale = useLocale();
  const toast = useToast();
  const confirm = useConfirm();
  const [brands, setBrands] = useState<Brand[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<BrandTokens | null>(null);
  // Farben des Profils als Vorschläge im Farbwähler
  const brandSwatches = draft
    ? [...BASE_COLOR_KEYS, ...COLOR_KEYS, ...draft.colors.custom.map((item) => item.key)]
        .map((key) => {
          const custom = draft.colors.custom.find((item) => item.key === key);
          return custom ? { value: custom.value, label: custom.label || custom.key } : { value: draft.colors[key], label: t(`colorRef.${key}`) };
        })
        .filter((item, index, all) => normalizeHex(item.value) && all.findIndex((other) => normalizeHex(other.value) === normalizeHex(item.value)) === index)
    : [];
  const [name, setName] = useState("");
  const [assets, setAssets] = useState<DocumentAsset[]>([]);
  // Vorschau mit der Vorlage, die der Verein für diesen Dokumenttyp verwendet
  const [previewType, setPreviewType] = useState<PreviewType>("protocol");
  const [pages, setPages] = useState<string[]>([]);
  const [previewError, setPreviewError] = useState("");
  const [saving, setSaving] = useState(false);
  const [picker, setPicker] = useState<{ role: string; kind: "image" | "font" } | null>(null);
  const [revisions, setRevisions] = useState<BrandRevision[] | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createPreset, setCreatePreset] = useState("classic_blue");
  const [presets, setPresets] = useState<string[]>([]);
  const [appearanceCatalog, setAppearanceCatalog] = useState<AppearanceCatalog | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [documentLanguage, setDocumentLanguage] = useState<string | null>(null);
  const canEdit = capabilities.manage_brand;
  const selected = brands?.find((item) => item.id === selectedId) ?? null;

  const load = useCallback(
    (keepSelection = true) => {
      void studioApi.brands(showArchived).then((loaded) => {
        setBrands(loaded);
        const nextSelected = (keepSelection && loaded.find((item) => item.id === selectedId)) || loaded.find((item) => item.is_default) || loaded[0] || null;
        setSelectedId(nextSelected?.id ?? null);
        setDraft(nextSelected ? structuredClone(nextSelected.tokens) : null);
        setName(nextSelected?.name ?? "");
      });
    },
    [selectedId, showArchived]
  );

  useEffect(() => load(false), [showArchived]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    void studioApi.assets().then(setAssets);
    void studioApi.documentSettings().then((settings) => setDocumentLanguage(settings?.language ?? null));
    void studioApi.catalog().then((catalog) => {
      setPresets(catalog.brand_presets);
      setAppearanceCatalog(catalog.appearance ?? null);
    });
  }, []);

  const dirty = useMemo(() => !!selected && !!draft && (JSON.stringify(selected.tokens) !== JSON.stringify(draft) || name !== selected.name), [selected, draft, name]);

  // Live-Vorschau mit den ungespeicherten Werten
  const previewKey = JSON.stringify([draft, previewType]);
  useEffect(() => {
    if (!draft) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      previewDocument({ document_type: previewType, brand_tokens: canEdit ? draft : null, brand_id: canEdit ? null : selectedId, data_mode: "sample" }, 2, controller.signal)
        .then((result) => {
          setPages(result.pages);
          setPreviewError("");
        })
        .catch((reason) => {
          if (!controller.signal.aborted) setPreviewError(apiErrorMessage(reason, t("preview.failed")));
        });
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewKey]);

  if (!brands) return <p className="muted">{t("common.loading")}</p>;

  function update(mutator: (tokens: BrandTokens) => void) {
    setDraft((current) => {
      if (!current) return current;
      const next = structuredClone(current);
      mutator(next);
      return next;
    });
  }

  function setBaseColor(key: (typeof BASE_COLOR_KEYS)[number], value: string) {
    update((tokens) => {
      tokens.colors[key] = value.toUpperCase();
      if (tokens.derive_colors !== false) Object.assign(tokens.colors, deriveBrandColors(tokens.colors.primary, tokens.colors.secondary));
    });
  }

  function setDeriveColors(enabled: boolean) {
    update((tokens) => {
      tokens.derive_colors = enabled;
      if (enabled) Object.assign(tokens.colors, deriveBrandColors(tokens.colors.primary, tokens.colors.secondary));
    });
  }

  // Grundstil/Design: übernimmt Überschriften, Tabellen und Ecken in den Seitenaufbau; Übersteuerungen
  // einzelner Elementarten bleiben bestehen.
  function setAppearanceBase(base: string) {
    const definition = appearanceCatalog?.bases[base];
    if (!definition) return;
    update((tokens) => {
      tokens.appearance = { base, elements: tokens.appearance?.elements ?? {} };
      // Designs geben zusätzlich Abschnittsnummer und Verantwortliche vor (appearance.py)
      Object.assign(tokens.layout, definition.layout as Partial<BrandTokens["layout"]>);
    });
  }

  async function save() {
    if (!selected || !draft) return;
    setSaving(true);
    try {
      const updated = await studioApi.updateBrand(selected.id, { lock_version: selected.lock_version, name, tokens: draft });
      setBrands((current) => current?.map((item) => (item.id === updated.id ? updated : item)) ?? null);
      setDraft(structuredClone(updated.tokens));
      toast(t("brand.saved", { revision: updated.revision }), "success");
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) toast(t("brand.conflict"), "error");
      else toast(apiErrorMessage(reason, t("brand.saveFailed")), "error");
    } finally {
      setSaving(false);
    }
  }

  async function act(action: () => Promise<unknown>, message: string, reselect = true) {
    try {
      await action();
      toast(message, "success");
      load(reselect);
    } catch (reason) {
      toast(apiErrorMessage(reason, t("common.actionFailed")), "error");
    }
  }

  async function saveDocumentLanguage(language: string) {
    const previous = documentLanguage;
    setDocumentLanguage(language);
    try {
      await studioApi.updateDocumentSettings(language);
      toast(t("brand.documentLanguageSaved"), "success");
    } catch (reason) {
      setDocumentLanguage(previous);
      toast(apiErrorMessage(reason, t("brand.saveFailed")), "error");
    }
  }

  async function create() {
    try {
      const created = await studioApi.createBrand({ name: createName.trim(), preset: createPreset });
      setCreateOpen(false);
      setCreateName("");
      setBrands((current) => [...(current ?? []), created]);
      setSelectedId(created.id);
      setDraft(structuredClone(created.tokens));
      setName(created.name);
      toast(t("brand.created"), "success");
    } catch (reason) {
      toast(apiErrorMessage(reason, t("common.actionFailed")), "error");
    }
  }

  const assetName = (id: string | null | undefined) => (id ? assets.find((asset) => asset.id === id)?.name ?? t("props.imageMissing") : t("brand.noImage"));
  const fontName = (ids: string[]) => ids.map((id) => assets.find((asset) => asset.id === id)?.font_family ?? "?").join(", ");

  // Schriftauswahl; «both» setzt Fliesstext und Überschriften gemeinsam (einfache Ansicht)
  const fontSelect = (role: "body" | "heading" | "both", label: string) => {
    const source = draft!.typography[role === "both" ? "body" : role];
    const roles = role === "both" ? (["body", "heading"] as const) : [role];
    return (
      <label className="field-stack">
        <span className="field-label">{label}</span>
        <Select
          value={source.asset_ids.length ? "custom" : source.builtin ?? "inter"}
          onChange={(event) =>
            event.target.value === "custom"
              ? setPicker({ role: `font:${role}`, kind: "font" })
              : update((tokens) => { roles.forEach((item) => { tokens.typography[item] = { builtin: event.target.value, asset_ids: [] }; }); })
          }
        >
          {FONT_KEYS.map((key) => (
            <option key={key} value={key}>
              {t(`font.${key}`)}
            </option>
          ))}
          <option value="custom">{source.asset_ids.length ? fontName(source.asset_ids) : t("brand.customFont")}</option>
        </Select>
      </label>
    );
  };

  const assetRole = (role: (typeof ASSET_ROLES)[number], showLabel = true) => (
    <div key={role} className="studio-asset-role">
      {showLabel && <span className="field-label">{t(`brand.asset.${role}`)}</span>}
      <div className="studio-inline-actions">
        <button type="button" className="button-secondary" onClick={() => setPicker({ role, kind: "image" })}>
          {assetName(draft!.assets[role])}
        </button>
        {draft!.assets[role] && (
          <button type="button" className="button-ghost" onClick={() => update((tokens) => { tokens.assets[role] = null; })}>
            {t("brand.remove")}
          </button>
        )}
      </div>
    </div>
  );

  // Nicht verwendet: kein Standard, keine Vorlage, keine Zuweisung (Gestaltung auf Abruf)
  const isUnused = (brand: Brand) => !brand.is_default && !brand.archived && !brand.assigned && (brand.template_count ?? 0) === 0;
  const usedBrands = brands.filter((brand) => !isUnused(brand));
  const unusedBrands = brands.filter(isUnused);

  async function archiveUnused() {
    try {
      for (const brand of unusedBrands) await studioApi.archiveBrand(brand.id, true);
      toast(t("brand.unusedArchived", { count: unusedBrands.length }), "success");
      load(false);
    } catch (reason) {
      toast(apiErrorMessage(reason, t("common.actionFailed")), "error");
      load(false);
    }
  }

  function renderBrand(brand: Brand) {
    return (
      <div key={brand.id} className={brand.id === selectedId ? "studio-brand-item studio-brand-item-active" : "studio-brand-item"}>
        <button
          type="button"
          className="studio-brand-select"
          onClick={async () => {
            if (dirty && !(await confirm({ message: t("brand.discardChanges"), confirmLabel: t("brand.switch") }))) return;
            setSelectedId(brand.id);
            setDraft(structuredClone(brand.tokens));
            setName(brand.name);
            setRevisions(null);
          }}
        >
          <span className="studio-brand-swatches" aria-hidden="true">
            {["primary", "secondary", "accent"].map((key) => (
              <span key={key} className="studio-brand-dot" style={{ background: brand.tokens.colors[key] }} />
            ))}
          </span>
          <span className="studio-brand-name">{brand.name}</span>
          {brand.is_default && <Badge variant="success">{t("brand.default")}</Badge>}
          {brand.archived && <Badge variant="neutral">{t("brand.archived")}</Badge>}
        </button>
        {canEdit && (
          <ActionMenu
            ariaLabel={t("brand.actionsFor", { name: brand.name })}
            items={[
              ...(!brand.is_default && !brand.archived ? [{ label: t("brand.makeDefault"), onClick: () => void act(() => studioApi.updateBrand(brand.id, { lock_version: brand.lock_version, is_default: true }), t("brand.defaultSet")) }] : []),
              { label: t("brand.duplicate"), onClick: () => void act(() => studioApi.createBrand({ name: t("brand.copyName", { name: brand.name }), from_brand_id: brand.id }), t("brand.created")) },
              { label: t("brand.revisions"), onClick: () => { setSelectedId(brand.id); void studioApi.brandRevisions(brand.id).then(setRevisions); } },
              ...(!brand.is_default ? [{ label: brand.archived ? t("brand.unarchive") : t("brand.archive"), onClick: () => void act(() => studioApi.archiveBrand(brand.id, !brand.archived), brand.archived ? t("brand.unarchived") : t("brand.archivedDone"), false) }] : []),
              ...(!brand.is_default
                ? [{
                    label: t("brand.delete"),
                    danger: true,
                    onClick: async () => {
                      if (await confirm({ message: t("brand.deleteConfirm", { name: brand.name }), tone: "danger", confirmLabel: t("brand.delete") })) await act(() => studioApi.deleteBrand(brand.id), t("brand.deleted"), false);
                    },
                  }]
                : []),
            ]}
          />
        )}
      </div>
    );
  }

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("brand.title")}</h1>
          <p className="muted">{t("brand.description")}</p>
        </div>
      </div>
      {!canEdit && <StatusBanner tone="neutral" message={t("brand.readOnly")} />}

      <div className="studio-brand-layout">
        <aside className="studio-brand-list" aria-label={t("brand.profiles")}>
          {usedBrands.map((brand) => renderBrand(brand))}
          {unusedBrands.length > 0 && (
            <div className="studio-brand-unused">
              <div className="studio-brand-unused-head">
                <span className="field-label">{t("brand.unused")}</span>
                {canEdit && (
                  <button type="button" className="button-secondary button-ghost" onClick={() => void archiveUnused()}>
                    {t("brand.archiveUnused")}
                  </button>
                )}
              </div>
              {unusedBrands.map((brand) => renderBrand(brand))}
            </div>
          )}
          <p className="field-help">{t("brand.oneProfileHint")}</p>
          {canEdit && (
            <button type="button" className="button-secondary" onClick={() => setCreateOpen(true)}>
              {t("brand.create")}
            </button>
          )}
          <label className="studio-inline-check">
            <input type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} />
            <span>{t("brand.showArchived")}</span>
          </label>
          <label className="field-stack studio-brand-language">
            <span className="field-label">{t("brand.documentLanguage")}</span>
            <Select value={documentLanguage ?? ""} disabled={!canEdit || documentLanguage === null} onChange={(event) => void saveDocumentLanguage(event.target.value)}>
              {locales.map((code) => (
                <option key={code} value={code}>
                  {t(`language.${code}`)}
                </option>
              ))}
            </Select>
            <span className="field-help">{t("brand.documentLanguageHelp")}</span>
          </label>
        </aside>

        {selected && draft && (
          <section className="studio-brand-editor" aria-label={t("brand.editor")}>
            <fieldset disabled={!canEdit} className="studio-prop-fieldset">
              <label className="field-stack">
                <span className="field-label">{t("brand.name")}</span>
                <input value={name} maxLength={120} onChange={(event) => setName(event.target.value)} />
              </label>

              <Section title={t("brand.colors")} open>
                <div className="studio-color-grid">
                  {BASE_COLOR_KEYS.map((key) => (
                    <label key={key} className="studio-color-cell">
                      <ColorInput value={draft.colors[key]} swatches={brandSwatches} aria-label={t(`colorRef.${key}`)} onChange={(value) => setBaseColor(key, value)} />
                      <span>{t(`colorRef.${key}`)}</span>
                    </label>
                  ))}
                </div>
                <label className="studio-inline-check">
                  <input type="checkbox" checked={draft.derive_colors !== false} onChange={(event) => setDeriveColors(event.target.checked)} />
                  <span>{t("brand.deriveColors")}</span>
                </label>
                <p className="field-help">{t("brand.deriveColorsHelp")}</p>
              </Section>

              {appearanceCatalog && (
                <Section title={t("appearance.baseTitle")} open>
                  <p className="field-help">{t("appearance.baseHelp")}</p>
                  <div className="studio-variant-list studio-appearance-bases" role="radiogroup" aria-label={t("appearance.baseTitle")}>
                    {Object.keys(appearanceCatalog.bases).map((base) => {
                      const active = (draft.appearance?.base ?? DEFAULT_APPEARANCE_BASE) === base;
                      // Frühere Grundstile nur für Profile, die sie noch nutzen
                      if (appearanceCatalog.bases[base].legacy && !active) return null;
                      return (
                        <button key={base} type="button" role="radio" aria-checked={active} className={active ? "studio-variant studio-variant-active" : "studio-variant"} onClick={() => setAppearanceBase(base)}>
                          <span className="studio-variant-name">{t(`appearance.base.${base}.name`)}</span>
                          <span className="field-help">{t(`appearance.base.${base}.help`)}</span>
                          {appearanceCatalog.bases[base].legacy && (
                            <Badge variant="neutral" className="studio-variant-badge">
                              {t("appearance.legacyBase")}
                            </Badge>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </Section>
              )}

              <Section title={t("brand.typography")} open>
                {fontSelect("both", t("brand.font.both"))}
              </Section>

              <Section title={t("brand.asset.logo")} open>
                {assetRole("logo", false)}
              </Section>

              <Section title={t("brand.organization")}>
                {(["name", "address", "contact", "website", "place"] as const).map((key) => (
                  <label key={key} className="field-stack">
                    <span className="field-label">{t(`brand.org.${key}`)}</span>
                    {key === "address" ? (
                      <textarea rows={3} value={draft.organization[key]} maxLength={600} onChange={(event) => update((tokens) => { tokens.organization[key] = event.target.value; })} />
                    ) : (
                      <input value={draft.organization[key]} maxLength={key === "place" ? 120 : 300} onChange={(event) => update((tokens) => { tokens.organization[key] = event.target.value; })} />
                    )}
                    {key === "name" && <span className="field-help">{t("brand.orgNameHelp")}</span>}
                  </label>
                ))}
              </Section>

              <Section title={t("brand.advanced")} className="studio-brand-section studio-brand-advanced">
                <Section title={t("brand.allColors")}>
                  <p className="field-help">{t("brand.allColorsHelp")}</p>
                  <div className="studio-color-grid">
                    {COLOR_KEYS.map((key) => (
                      <label key={key} className="studio-color-cell">
                        <ColorInput
                          value={draft.colors[key]}
                          swatches={brandSwatches}
                          aria-label={t(`colorRef.${key}`)}
                          onChange={(value) =>
                            update((tokens) => {
                              tokens.colors[key] = value;
                              if (DERIVED_COLOR_KEYS.includes(key)) tokens.derive_colors = false;
                            })
                          }
                        />
                        <span>{t(`colorRef.${key}`)}</span>
                      </label>
                    ))}
                  </div>
                  <h4 className="studio-subtitle">{t("brand.customColors")}</h4>
                  {draft.colors.custom.map((item, index) => (
                    <div key={index} className="studio-custom-color">
                      <ColorInput value={item.value} swatches={brandSwatches} aria-label={t("brand.customColorValue")} onChange={(value) => update((tokens) => { tokens.colors.custom[index].value = value; })} />
                      <input value={item.label} placeholder={t("brand.customColorLabel")} aria-label={t("brand.customColorLabel")} onChange={(event) => update((tokens) => { tokens.colors.custom[index].label = event.target.value; })} />
                      <input value={item.key} placeholder={t("brand.customColorKey")} aria-label={t("brand.customColorKey")} pattern="[a-z0-9_]+" onChange={(event) => update((tokens) => { tokens.colors.custom[index].key = event.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"); })} />
                      <button type="button" className="button-icon-soft button-icon-soft-danger" aria-label={t("brand.removeColor")} onClick={() => update((tokens) => { tokens.colors.custom.splice(index, 1); })}>
                        ✕
                      </button>
                    </div>
                  ))}
                  <button type="button" className="button-secondary button-ghost" onClick={() => update((tokens) => { tokens.colors.custom.push({ key: `farbe_${tokens.colors.custom.length + 1}`, label: "", value: tokens.colors.primary }); })}>
                    {t("brand.addColor")}
                  </button>
                </Section>
                {appearanceCatalog && (
                  <Section title={t("appearance.elementsTitle")}>
                    <p className="field-help">{t("appearance.elementsHelp")}</p>
                    <AppearanceEditor
                      catalog={appearanceCatalog}
                      kinds={Object.keys(appearanceCatalog.variants)}
                      value={draft.appearance?.elements}
                      inherited={(kind) => baseVariant(draft, appearanceCatalog, kind)}
                      inheritLabel={(value) => t("appearance.inheritBase", { value })}
                      onChange={(elements) => update((tokens) => { tokens.appearance = { base: tokens.appearance?.base ?? DEFAULT_APPEARANCE_BASE, elements }; })}
                    />
                  </Section>
                )}
                <Section title={t("brand.typographyAdvanced")}>
                  <div className="studio-field-grid">
                    {fontSelect("body", t("brand.font.body"))}
                    {fontSelect("heading", t("brand.font.heading"))}
                  </div>
                  <div className="studio-field-grid">
                    {SIZE_KEYS.map((key) => (
                      <label key={key} className="field-stack">
                        <span className="field-label">{t(`brand.size.${key}`)}</span>
                        <span className="studio-number">
                          <input type="number" min={5} max={72} step={0.5} value={draft.typography[key]} onChange={(event) => update((tokens) => { tokens.typography[key] = Number(event.target.value || 0); })} />
                          <span className="studio-number-suffix">{t("brand.unitPt")}</span>
                        </span>
                      </label>
                    ))}
                    <label className="field-stack">
                      <span className="field-label">{t("brand.lineHeight")}</span>
                      <input type="number" min={1} max={2.5} step={0.05} value={draft.typography.line_height} onChange={(event) => update((tokens) => { tokens.typography.line_height = Number(event.target.value || 1.35); })} />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">{t("brand.headingWeight")}</span>
                      <Select value={draft.typography.weight_heading} onChange={(event) => update((tokens) => { tokens.typography.weight_heading = event.target.value as "bold"; })}>
                        <option value="medium">{t("fields.weightValue.medium")}</option>
                        <option value="bold">{t("fields.weightValue.bold")}</option>
                      </Select>
                    </label>
                    <label className="field-stack">
                      <span className="field-label">{t("brand.letterSpacing")}</span>
                      <input type="number" min={-1} max={4} step={0.1} value={draft.typography.letter_spacing_heading} onChange={(event) => update((tokens) => { tokens.typography.letter_spacing_heading = Number(event.target.value || 0); })} />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">{t("brand.headingTransform")}</span>
                      <Select value={draft.typography.heading_transform} onChange={(event) => update((tokens) => { tokens.typography.heading_transform = event.target.value as "none"; })}>
                        <option value="none">{t("fields.transformValue.none")}</option>
                        <option value="upper">{t("fields.transformValue.upper")}</option>
                      </Select>
                    </label>
                  </div>
                  <fieldset className="studio-fieldset">
                    <legend className="field-label">{t("brand.fallbacks")}</legend>
                    <div className="studio-param-checks">
                      {FONT_KEYS.map((key) => (
                        <label key={key} className="studio-inline-check">
                          <input type="checkbox" checked={draft.typography.fallbacks.includes(key)} onChange={(event) => update((tokens) => { tokens.typography.fallbacks = event.target.checked ? [...tokens.typography.fallbacks, key].slice(0, 3) : tokens.typography.fallbacks.filter((item) => item !== key); })} />
                          <span>{t(`font.${key}`)}</span>
                        </label>
                      ))}
                    </div>
                  </fieldset>
                </Section>

                <Section title={t("brand.advancedAssets")}>
                  {ADVANCED_ASSET_ROLES.map((role) => assetRole(role))}
                  <h4 className="studio-subtitle">{t("brand.ownImages")}</h4>
                  {draft.assets.images.map((image, index) => (
                    <div key={index} className="studio-custom-color">
                      <span>{assetName(image.asset_id)}</span>
                      <input value={image.label} placeholder={t("brand.imageLabel")} aria-label={t("brand.imageLabel")} onChange={(event) => update((tokens) => { tokens.assets.images[index].label = event.target.value; })} />
                      <input value={image.key} aria-label={t("brand.imageKey")} onChange={(event) => update((tokens) => { tokens.assets.images[index].key = event.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"); })} />
                      <button type="button" className="button-icon-soft button-icon-soft-danger" aria-label={t("brand.remove")} onClick={() => update((tokens) => { tokens.assets.images.splice(index, 1); })}>
                        ✕
                      </button>
                    </div>
                  ))}
                  <button type="button" className="button-secondary button-ghost" onClick={() => setPicker({ role: "images", kind: "image" })}>
                    {t("brand.addImage")}
                  </button>
                </Section>

                <Section title={t("brand.layout")}>
                  <div className="studio-field-grid">
                    <label className="field-stack">
                      <span className="field-label">{t("brand.pageSize")}</span>
                      <Select value={draft.layout.page_size} onChange={(event) => update((tokens) => { tokens.layout.page_size = event.target.value as "A4"; })}>
                        {["A4", "A5", "Letter"].map((size) => (
                          <option key={size} value={size}>
                            {t(`document.sizeValue.${size}`)}
                          </option>
                        ))}
                      </Select>
                    </label>
                    <label className="field-stack">
                      <span className="field-label">{t("document.orientation")}</span>
                      <Select value={draft.layout.orientation} onChange={(event) => update((tokens) => { tokens.layout.orientation = event.target.value as "portrait"; })}>
                        <option value="portrait">{t("document.portrait")}</option>
                        <option value="landscape">{t("document.landscape")}</option>
                      </Select>
                    </label>
                    {(["top", "right", "bottom", "left"] as const).map((side) => (
                      <label key={side} className="field-stack">
                        <span className="field-label">{t(`brand.margin.${side}`)}</span>
                        <span className="studio-number">
                          <input type="number" min={0} max={80} step={0.5} value={draft.layout.margins[side]} onChange={(event) => update((tokens) => { tokens.layout.margins[side] = Number(event.target.value || 0); })} />
                          <span className="studio-number-suffix">{t("brand.unitMm")}</span>
                        </span>
                      </label>
                    ))}
                    <label className="field-stack">
                      <span className="field-label">{t("brand.paragraphGap")}</span>
                      <input type="number" min={0} max={20} step={0.5} value={draft.layout.paragraph_gap} onChange={(event) => update((tokens) => { tokens.layout.paragraph_gap = Number(event.target.value || 0); })} />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">{t("brand.sectionGap")}</span>
                      <input type="number" min={0} max={40} step={0.5} value={draft.layout.section_gap} onChange={(event) => update((tokens) => { tokens.layout.section_gap = Number(event.target.value || 0); })} />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">{t("brand.borderWidth")}</span>
                      <input type="number" min={0.1} max={4} step={0.1} value={draft.layout.border_width} onChange={(event) => update((tokens) => { tokens.layout.border_width = Number(event.target.value || 0.5); })} />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">{t("brand.radius")}</span>
                      <input type="number" min={0} max={10} step={0.5} value={draft.layout.radius} onChange={(event) => update((tokens) => { tokens.layout.radius = Number(event.target.value || 0); })} />
                    </label>
                  </div>
                  <fieldset className="studio-fieldset">
                    <legend className="field-label">{t("brand.documentDefaults")}</legend>
                    <p className="field-help">{t("brand.documentDefaultsHelp")}</p>
                    {DOCUMENT_DEFAULTS.map((key) => (
                      <label key={key} className="studio-inline-check">
                        <input type="checkbox" checked={draft.layout[key]} onChange={(event) => update((tokens) => { tokens.layout[key] = event.target.checked; })} />
                        <span>{t(`brand.defaultFlag.${key}`)}</span>
                      </label>
                    ))}
                  </fieldset>
                  {(Object.keys(LAYOUT_CHOICES) as LayoutChoice[]).map((key) => (
                    <label key={key} className="field-stack">
                      <span className="field-label">{t(`brand.choice.${key}.label`)}</span>
                      <Select value={draft.layout[key]} onChange={(event) => update((tokens) => { (tokens.layout as Record<LayoutChoice, string>)[key] = event.target.value; })}>
                        {LAYOUT_CHOICES[key].map((value) => (
                          <option key={value} value={value}>{t(`brand.choice.${key}.${value}`)}</option>
                        ))}
                      </Select>
                      <span className="field-help">{t(`brand.choice.${key}.help`)}</span>
                    </label>
                  ))}
                </Section>

                <Section title={t("brand.headerFooter")}>
                  <p className="field-help">{t("brand.headerFooterHelp")}</p>
                  {HEADER_FOOTER_FLAGS.map((key) => (
                    <label key={key} className="studio-inline-check">
                      <input type="checkbox" checked={draft.layout.header_footer[key] === true} onChange={(event) => update((tokens) => { tokens.layout.header_footer[key] = event.target.checked; })} />
                      <span>{t(`brand.hf.${key}`)}</span>
                    </label>
                  ))}
                  <label className="field-stack">
                    <span className="field-label">{t("brand.footerText")}</span>
                    <input value={String(draft.layout.header_footer.footer_text ?? "")} maxLength={300} onChange={(event) => update((tokens) => { tokens.layout.header_footer.footer_text = event.target.value; })} />
                  </label>
                </Section>

                <Section title={t("brand.verify")}>
                  <p className="field-help">{t("brand.verifyHelp")}</p>
                  {(["show_url", "show_id", "show_qr"] as const).map((key) => (
                    <label key={key} className="studio-inline-check">
                      <input type="checkbox" checked={draft.verify[key]} onChange={(event) => update((tokens) => { tokens.verify[key] = event.target.checked; })} />
                      <span>{t(`brand.verifyFlag.${key}`)}</span>
                    </label>
                  ))}
                </Section>
              </Section>
            </fieldset>
            {canEdit && (
              <div className="modal-actions studio-brand-actions">
                <span className="muted">{t("brand.affects", { count: selected.template_count ?? 0, revision: selected.revision })}</span>
                <button type="button" className="button-ghost" disabled={!dirty} onClick={() => { setDraft(structuredClone(selected.tokens)); setName(selected.name); }}>
                  {t("brand.reset")}
                </button>
                <button type="button" className="button-primary" disabled={!dirty || saving} onClick={() => void save()}>
                  {t("brand.save")}
                </button>
              </div>
            )}
          </section>
        )}

        <section className="studio-brand-preview" aria-label={t("preview.title")}>
          <div className="studio-preview-bar">
            <span className="field-label">{t("preview.title")}</span>
            <FilterTabs options={PREVIEW_TYPES.map((value) => ({ value, label: t(`docType.${value}`) }))} value={previewType} onChange={setPreviewType} />
          </div>
          {previewError && <StatusBanner tone="error" message={previewError} />}
          <div className="studio-preview-pages">
            {pages.map((page, index) => (
              // eslint-disable-next-line @next/next/no-img-element
              <img key={index} className="studio-preview-page" src={page} alt={t("preview.pageAlt", { page: index + 1 })} />
            ))}
          </div>
        </section>
      </div>

      {picker && (
        <AssetPicker
          open
          onClose={() => setPicker(null)}
          assets={assets}
          onAssetsChange={setAssets}
          canUpload={canEdit}
          kind={picker.kind}
          defaultCategory={picker.role === "logo" || picker.role === "logo_alt" ? "logo" : picker.role === "letterhead" ? "letterhead" : picker.role === "background" ? "background" : picker.role === "watermark" ? "watermark" : "image"}
          onPick={(asset) =>
            update((tokens) => {
              if (picker.role.startsWith("font:")) {
                const role = picker.role.slice(5) as "body" | "heading" | "both";
                const source = tokens.typography[role === "both" ? "body" : role].asset_ids;
                const choice = { builtin: null, asset_ids: [...source.filter((id) => id !== asset.id), asset.id].slice(-4) };
                (role === "both" ? (["body", "heading"] as const) : [role]).forEach((item) => { tokens.typography[item] = structuredClone(choice); });
              } else if (picker.role === "images") {
                tokens.assets.images.push({ key: `bild_${tokens.assets.images.length + 1}`, label: asset.name, asset_id: asset.id });
              } else {
                tokens.assets[picker.role as (typeof ASSET_ROLES)[number]] = asset.id;
              }
            })
          }
        />
      )}

      <Modal className="studio-modal" open={createOpen} onClose={() => setCreateOpen(false)} title={t("brand.createTitle")}>
        <label className="field-stack">
          <span className="field-label">{t("brand.name")}</span>
          <input value={createName} maxLength={120} onChange={(event) => setCreateName(event.target.value)} autoFocus />
        </label>
        <div className="field-stack">
          <span className="field-label">{t("brand.preset")}</span>
          <div className="studio-variant-list" role="radiogroup" aria-label={t("brand.preset")}>
            {presets.map((preset) => (
              <button key={preset} type="button" role="radio" aria-checked={createPreset === preset} className={createPreset === preset ? "studio-variant studio-variant-active" : "studio-variant"} onClick={() => setCreatePreset(preset)}>
                <span className="studio-variant-name">{t(`brand.presetName.${preset}`)}</span>
                <span className="field-help">{t(`brand.presetHelp.${preset}`)}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={() => setCreateOpen(false)}>
            {t("common.cancel")}
          </button>
          <button type="button" className="button-primary" disabled={!createName.trim()} onClick={() => void create()}>
            {t("common.create")}
          </button>
        </div>
      </Modal>

      <Modal className="studio-modal" open={revisions !== null} onClose={() => setRevisions(null)} title={t("brand.revisionsTitle", { name: selected?.name ?? "" })}>
        <ul className="studio-revision-list">
          {(revisions ?? []).map((revision) => (
            <li key={revision.id} className="studio-revision-item">
              <span>
                {t("revisions.number", { revision: revision.revision })} · {formatDateTime(revision.created_at, locale)}
                {revision.created_by_name ? ` · ${revision.created_by_name}` : ""}
              </span>
              {canEdit && selected && revision.revision !== selected.revision && (
                <button type="button" className="button-secondary" onClick={() => { setRevisions(null); void act(() => studioApi.restoreBrandRevision(selected.id, revision.id), t("brand.restored")); }}>
                  {t("revisions.restore")}
                </button>
              )}
            </li>
          ))}
        </ul>
      </Modal>
    </div>
  );
}
