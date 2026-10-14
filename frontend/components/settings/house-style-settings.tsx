"use client";

// Hausstil-Einstellungen: Stil wählen, Tokens setzen, Schriften und Bilder hochladen,
// Live-Vorschau mit einem festen Musterdokument. Ein Hausstil wird nur über Daten angepasst
// (Tokens, siehe backend/app/documents/style_tokens.py); Template-Code gibt es nicht mehr.

import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { BlockSpec, DocumentStyle, DocumentStyleAsset, previewDocument, StyleTokens } from "@/lib/documents/api";

type Props = {
  initialStyles: DocumentStyle[];
  initialAssets: DocumentStyleAsset[];
  initialLanguage: string;
  languages: string[];
  canEdit: boolean;
};

const STYLE_KEYS = ["modern", "classic", "compact"];
const FONTS = ["style", "inter", "liberation_sans", "liberation_serif", "noto_sans", "custom"];
const HEADERS = ["none", "minimal", "standard", "bar", "logo", "logo_bar"];
const FOOTERS = ["none", "minimal", "standard", "with_version", "date_page"];
const TITLE_PAGES = ["none", "minimal", "modern", "bold", "cover"];
const TOCS = ["off", "on", "compact", "very_compact"];
// Startwert, wenn der Absenderblock eine eigene Farbe bekommt (wie die frühere Fussfarbe)
const SENDER_COLOR_DEFAULT = "#444444"; // design-ok: PDF-Farbwert (Daten), keine UI-Farbe
const SPACINGS = ["tight", "normal", "relaxed"];
const MARGINS = ["narrow", "normal", "wide"];
const ORIENTATIONS = ["portrait", "landscape"];
const FONT_CUTS = ["regular", "bold", "italic", "bold_italic"] as const;
const PREVIEW_DEBOUNCE_MS = 450;

export function HouseStyleSettings({ initialStyles, initialAssets, initialLanguage, languages, canEdit }: Props) {
  const t = useTranslations("documents");
  const tCommon = useTranslations("common");
  const toast = useToast();
  const confirm = useConfirm();
  const [styles, setStyles] = useState(initialStyles);
  const [assets, setAssets] = useState(initialAssets);
  const [selectedId, setSelectedId] = useState<string | null>(initialStyles.find((style) => style.is_default)?.id ?? initialStyles[0]?.id ?? null);
  const selected = styles.find((style) => style.id === selectedId) ?? null;
  const [draft, setDraft] = useState<DocumentStyle | null>(selected);
  const [language, setLanguage] = useState(initialLanguage);
  const [pages, setPages] = useState<string[]>([]);
  const [previewError, setPreviewError] = useState("");
  const [saving, setSaving] = useState(false);
  const imageInput = useRef<HTMLInputElement>(null);
  const fontInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setDraft(selected);
    // nur beim Wechsel des Stils übernehmen, nicht bei jedem Speichern
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  const sampleBlocks = useMemo<BlockSpec[]>(
    () => [
      { type: "heading", params: { text: t("styles.sample.heading") } },
      { type: "richtext", params: { markdown: t("styles.sample.text") } },
      { type: "bullet_list", title: t("styles.sample.listTitle"), params: { items: [t("styles.sample.item1"), t("styles.sample.item2")] } },
      {
        type: "generic_table",
        title: t("styles.sample.tableTitle"),
        params: { headers: [t("styles.sample.colTask"), t("styles.sample.colPerson"), t("styles.sample.colDue")], rows: [[t("styles.sample.item1"), "Anna", "01.03.2026"], [t("styles.sample.item2"), "Ben", "15.03.2026"]] },
      },
      { type: "signature_fields", params: {} },
    ],
    [t]
  );

  const previewKey = JSON.stringify([draft?.style_key, draft?.tokens, sampleBlocks, language]);
  useEffect(() => {
    if (!draft) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      previewDocument(
        {
          document_type: "custom",
          blocks: sampleBlocks,
          style_override: { style_key: draft.style_key, tokens: draft.tokens },
          options: { title: t("styles.sample.title"), watermark: false },
          language,
        },
        2,
        controller.signal
      )
        .then((result) => {
          setPages(result?.pages ?? []);
          setPreviewError("");
        })
        .catch((error) => {
          if (!controller.signal.aborted) setPreviewError(error instanceof Error ? error.message : t("styles.previewFailed"));
        });
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
    // previewKey bildet alle Eingaben ab
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewKey]);

  function setToken<K extends keyof StyleTokens>(key: K, value: StyleTokens[K]) {
    setDraft((current) => (current ? { ...current, tokens: { ...current.tokens, [key]: value } } : current));
  }

  async function createStyle() {
    try {
      const created = await browserApiFetch<DocumentStyle>("/api/document-styles", { method: "POST", body: JSON.stringify({ name: t("styles.newName"), style_key: "modern" }) });
      setStyles((current) => [...current, created]);
      setSelectedId(created.id);
      setDraft(created);
    } catch (error) {
      toast(error instanceof Error ? error.message : t("styles.saveFailed"), "error");
    }
  }

  async function save() {
    if (!draft) return;
    setSaving(true);
    try {
      const updated = await browserApiFetch<DocumentStyle>(`/api/document-styles/${draft.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name: draft.name, style_key: draft.style_key, tokens: draft.tokens, is_default: draft.is_default || undefined }),
      });
      setStyles((current) => current.map((style) => (style.id === updated.id ? updated : updated.is_default ? { ...style, is_default: false } : style)));
      setDraft(updated);
      toast(t("styles.saved"), "success");
    } catch (error) {
      toast(error instanceof Error ? error.message : t("styles.saveFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  async function removeStyle() {
    if (!draft) return;
    const ok = await confirm({ tone: "danger", message: t("styles.deleteConfirm", { name: draft.name }), confirmLabel: tCommon("delete") });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/document-styles/${draft.id}`, { method: "DELETE" });
      const remaining = await browserApiFetch<DocumentStyle[]>("/api/document-styles");
      setStyles(remaining ?? []);
      setSelectedId(remaining?.[0]?.id ?? null);
      setDraft(remaining?.[0] ?? null);
    } catch (error) {
      toast(error instanceof Error ? error.message : t("styles.saveFailed"), "error");
    }
  }

  async function upload(kind: "image" | "font", event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const body = new FormData();
    body.append("kind", kind);
    body.append("file", file);
    try {
      const asset = await browserApiFetch<DocumentStyleAsset>("/api/document-style-assets", { method: "POST", body });
      setAssets((current) => [asset, ...current]);
      toast(t("styles.uploaded"), "success");
    } catch (error) {
      toast(error instanceof Error ? error.message : t("styles.uploadFailed"), "error");
    }
  }

  async function removeAsset(asset: DocumentStyleAsset) {
    const ok = await confirm({ tone: "danger", message: t("styles.assetDeleteConfirm", { name: asset.name }), confirmLabel: tCommon("delete") });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/document-style-assets/${asset.id}`, { method: "DELETE" });
      setAssets((current) => current.filter((item) => item.id !== asset.id));
    } catch (error) {
      toast(error instanceof Error ? error.message : t("styles.saveFailed"), "error");
    }
  }

  async function saveLanguage(value: string) {
    setLanguage(value);
    try {
      await browserApiFetch("/api/document-settings", { method: "PATCH", body: JSON.stringify({ language: value }) });
      toast(t("styles.languageSaved"), "success");
    } catch (error) {
      toast(error instanceof Error ? error.message : t("styles.saveFailed"), "error");
    }
  }

  const images = assets.filter((asset) => asset.kind === "image");
  const fonts = assets.filter((asset) => asset.kind === "font");
  const tokens = draft?.tokens;

  function select<K extends keyof StyleTokens>(key: K, values: readonly string[], labelPrefix: string) {
    return (
      <label className="field-stack">
        <span className="field-label">{t(`styles.fields.${String(key)}`)}</span>
        <select disabled={!canEdit} value={String(tokens?.[key] ?? "")} onChange={(event) => setToken(key, (key === "base_size" ? Number(event.target.value) : event.target.value) as StyleTokens[K])}>
          {values.map((value) => <option key={value} value={value}>{t(`${labelPrefix}.${value}`)}</option>)}
        </select>
      </label>
    );
  }

  function assetSelect(key: "logo_asset_id" | "footer_image_asset_id") {
    return (
      <label className="field-stack">
        <span className="field-label">{t(`styles.fields.${key}`)}</span>
        <select disabled={!canEdit} value={tokens?.[key] ?? ""} onChange={(event) => setToken(key, event.target.value || null)}>
          <option value="">{t("styles.noAsset")}</option>
          {images.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}
        </select>
      </label>
    );
  }

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h2 className="section-title">{t("styles.title")}</h2>
          <p className="muted">{t("styles.intro")}</p>
        </div>
        {canEdit && <button type="button" className="button-primary" onClick={() => void createStyle()}>{t("styles.newStyle")}</button>}
      </div>

      <section className="panel">
        <label className="field-stack">
          <span className="field-label">{t("styles.documentLanguage")}</span>
          <select disabled={!canEdit} value={language} onChange={(event) => void saveLanguage(event.target.value)}>
            {languages.map((code) => <option key={code} value={code}>{t(`languages.${code}`)}</option>)}
          </select>
          <span className="field-help">{t("styles.documentLanguageHelp")}</span>
        </label>
      </section>

      <div className="housestyle-layout">
        <div className="housestyle-form">
          <div className="housestyle-list" role="list">
            {styles.map((style) => (
              <button
                key={style.id}
                type="button"
                role="listitem"
                className={style.id === selectedId ? "housestyle-item housestyle-item-active" : "housestyle-item"}
                onClick={() => setSelectedId(style.id)}
              >
                <span>{style.name}</span>
                <span className="housestyle-item-meta">
                  {t(`styles.baseStyles.${style.style_key}`)}
                  {style.is_default && <Badge variant="info">{t("styles.default")}</Badge>}
                </span>
              </button>
            ))}
          </div>

          {draft && tokens ? (
            <section className="panel housestyle-fields">
              <div className="two-col">
                <label className="field-stack">
                  <span className="field-label">{t("styles.fields.name")}</span>
                  <input disabled={!canEdit} value={draft.name} maxLength={120} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
                </label>
                <label className="field-stack">
                  <span className="field-label">{t("styles.fields.style_key")}</span>
                  <select disabled={!canEdit} value={draft.style_key} onChange={(event) => setDraft({ ...draft, style_key: event.target.value })}>
                    {STYLE_KEYS.map((key) => <option key={key} value={key}>{t(`styles.baseStyles.${key}`)}</option>)}
                  </select>
                </label>
                <label className="field-stack">
                  <span className="field-label">{t("styles.fields.primary_color")}</span>
                  <input disabled={!canEdit} type="color" className="housestyle-color" value={tokens.primary_color} onChange={(event) => setToken("primary_color", event.target.value)} />
                </label>
                <label className="field-stack">
                  <span className="field-label">{t("styles.fields.secondary_color")}</span>
                  <input disabled={!canEdit} type="color" className="housestyle-color" value={tokens.secondary_color} onChange={(event) => setToken("secondary_color", event.target.value)} />
                </label>
                {select("font", FONTS, "styles.fonts")}
                {select("base_size", ["10", "11", "12"], "styles.sizes")}
                {select("line_spacing", SPACINGS, "styles.spacings")}
                {select("margins", MARGINS, "styles.margins")}
                {select("orientation", ORIENTATIONS, "variants.orientation")}
                {select("header", HEADERS, "variants.header")}
                {select("footer", FOOTERS, "variants.footer")}
                {select("title_page", TITLE_PAGES, "variants.titlePage")}
                {select("toc", TOCS, "variants.toc")}
                {assetSelect("logo_asset_id")}
                {assetSelect("footer_image_asset_id")}
              </div>
              {tokens.font === "custom" && (
                <div className="two-col">
                  {FONT_CUTS.map((cut) => (
                    <label key={cut} className="field-stack">
                      <span className="field-label">{t(`styles.fontCuts.${cut}`)}</span>
                      <select disabled={!canEdit} value={tokens.custom_fonts[cut] ?? ""} onChange={(event) => setToken("custom_fonts", { ...tokens.custom_fonts, [cut]: event.target.value || null })}>
                        <option value="">{t("styles.noAsset")}</option>
                        {fonts.map((asset) => <option key={asset.id} value={asset.id}>{asset.font_family ? `${asset.font_family} (${asset.name})` : asset.name}</option>)}
                      </select>
                    </label>
                  ))}
                </div>
              )}
              <label className="field-stack">
                <span className="field-label">{t("styles.fields.sender")}</span>
                <textarea disabled={!canEdit} rows={3} maxLength={600} value={tokens.sender} onChange={(event) => setToken("sender", event.target.value)} />
              </label>
              <label className="docexport-check">
                <input disabled={!canEdit} type="checkbox" checked={tokens.sender_color !== null} onChange={(event) => setToken("sender_color", event.target.checked ? SENDER_COLOR_DEFAULT : null)} />
                <span>{t("styles.fields.sender_color_custom")}</span>
              </label>
              {tokens.sender_color !== null && (
                <label className="field-stack">
                  <span className="field-label">{t("styles.fields.sender_color")}</span>
                  <input disabled={!canEdit} type="color" className="housestyle-color" value={tokens.sender_color} onChange={(event) => setToken("sender_color", event.target.value)} />
                </label>
              )}
              <label className="field-stack">
                <span className="field-label">{t("styles.fields.place")}</span>
                <input disabled={!canEdit} maxLength={120} value={tokens.place} onChange={(event) => setToken("place", event.target.value)} />
              </label>
              {(["numbering", "toc_block_titles", "show_metadata", "watermark_draft"] as const).map((key) => (
                <label key={key} className="docexport-check">
                  <input disabled={!canEdit} type="checkbox" checked={tokens[key]} onChange={(event) => setToken(key, event.target.checked)} />
                  <span>{t(`styles.fields.${key}`)}</span>
                </label>
              ))}
              <fieldset className="housestyle-group">
                <legend className="docexport-heading">{t("styles.verifyHeading")}</legend>
                <p className="muted housestyle-group-hint">{t("styles.verifyHint")}</p>
                {(["verify_show_url", "verify_show_id", "verify_show_qr"] as const).map((key) => (
                  <label key={key} className="docexport-check">
                    <input disabled={!canEdit} type="checkbox" checked={tokens[key]} onChange={(event) => setToken(key, event.target.checked)} />
                    <span>{t(`styles.fields.${key}`)}</span>
                  </label>
                ))}
              </fieldset>
              <label className="docexport-check">
                <input disabled={!canEdit || selected?.is_default} type="checkbox" checked={draft.is_default} onChange={(event) => setDraft({ ...draft, is_default: event.target.checked })} />
                <span>{t("styles.makeDefault")}</span>
              </label>
              {canEdit && (
                <div className="docexport-actions-row">
                  <button type="button" className="button-danger" disabled={styles.length <= 1} onClick={() => void removeStyle()}>{tCommon("delete")}</button>
                  <button type="button" className="button-primary" disabled={saving || !draft.name.trim()} onClick={() => void save()}>{saving ? t("styles.saving") : tCommon("save")}</button>
                </div>
              )}
            </section>
          ) : (
            <p className="muted">{t("styles.empty")}</p>
          )}

          <section className="panel housestyle-assets">
            <h3 className="docexport-heading">{t("styles.assets")}</h3>
            <p className="field-help">{t("styles.assetsHelp")}</p>
            {assets.length === 0 ? (
              <p className="muted">{t("styles.noAssets")}</p>
            ) : (
              <ul className="housestyle-asset-list">
                {assets.map((asset) => (
                  <li key={asset.id} className="housestyle-asset">
                    <span>{asset.name}</span>
                    <span className="muted">{asset.kind === "font" ? asset.font_family : t("styles.image")}</span>
                    {canEdit && (
                      <button type="button" className="button-icon-soft button-icon-soft-sm button-icon-soft-danger" aria-label={t("styles.assetDelete", { name: asset.name })} onClick={() => void removeAsset(asset)}>✕</button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {canEdit && (
              <div className="docexport-actions-row">
                <input ref={imageInput} type="file" hidden accept="image/png,image/jpeg,image/webp" onChange={(event) => void upload("image", event)} />
                <input ref={fontInput} type="file" hidden accept=".ttf,.otf" onChange={(event) => void upload("font", event)} />
                <button type="button" className="button-secondary" onClick={() => imageInput.current?.click()}>{t("styles.uploadImage")}</button>
                <button type="button" className="button-secondary" onClick={() => fontInput.current?.click()}>{t("styles.uploadFont")}</button>
              </div>
            )}
          </section>
        </div>

        <section className="docexport-preview" aria-live="polite" aria-label={t("styles.preview")}>
          <div className="docexport-preview-bar">
            <span className="field-label">{t("styles.preview")}</span>
          </div>
          {previewError ? (
            <StatusBanner tone="error" message={previewError} />
          ) : (
            <div className="docexport-pages">
              {pages.map((page, index) => (
                // eslint-disable-next-line @next/next/no-img-element
                <img key={index} className="docexport-page" src={page} alt={t("dialog.pageAlt", { page: index + 1 })} />
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
