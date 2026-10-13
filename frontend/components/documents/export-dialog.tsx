"use client";

// Ein Export-Dialog für alle Dokumente: links Dokumenttyp bzw. Rezept, Blockliste
// (hinzufügen, entfernen, per Drag-and-drop sortieren, Parameter), Hausstil, Sprache und
// Optionen; rechts die entprellte Live-Vorschau. Öffnet sich überall mit Kontext vorbelegt
// (Protokoll, Todos mit aktiven Filtern, Termine, Statistik, Listen).

import { DragEvent, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { BlockParamForm } from "@/components/documents/block-param-form";
import { ActionMenu } from "@/components/ui/action-menu";
import { Modal } from "@/components/ui/modal";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import {
  BlockSpec,
  CatalogBlock,
  defaultParams,
  DocumentCatalog,
  DocumentRecipe,
  DocumentRequest,
  DocumentStyle,
  ExportOptions,
  exportDocumentFile,
  fetchCatalog,
  listRecipes,
  listStyles,
  previewDocument,
  renderDocument,
  saveBlob,
} from "@/lib/documents/api";

export type DocumentExportContext = {
  /** Vorbelegter Dokumenttyp (protocol, todos, events, statistics, list, …). */
  documentType: string;
  protocolId?: string | null;
  /** Parameter für die Standardblöcke, z. B. aktive Filter der Seite. */
  params?: Record<string, unknown>;
};

type Props = {
  open: boolean;
  onClose: () => void;
  context: DocumentExportContext;
  onExported?: () => void;
};

type EditableBlock = BlockSpec & { key: string };

const PREVIEW_DEBOUNCE_MS = 450;
const TITLE_PAGES = ["", "none", "minimal", "modern", "bold", "cover"];
const TOCS = ["", "off", "on", "compact"];
const ORIENTATIONS = ["", "portrait", "landscape"];

let blockCounter = 0;
function withKey(block: BlockSpec): EditableBlock {
  blockCounter += 1;
  return { ...block, params: { ...(block.params ?? {}) }, key: `b${blockCounter}` };
}

function applyContextParams(blocks: BlockSpec[], catalog: DocumentCatalog, params?: Record<string, unknown>): BlockSpec[] {
  if (!params) return blocks;
  return blocks.map((block) => {
    const schema = catalog.blocks.find((entry) => entry.type === block.type)?.params_schema;
    const allowed = Object.keys(schema?.properties ?? {});
    const extra = Object.fromEntries(Object.entries(params).filter(([key]) => allowed.includes(key)));
    return { ...block, params: { ...block.params, ...extra } };
  });
}

function stripKeys(blocks: EditableBlock[]): BlockSpec[] {
  return blocks.map(({ key: _key, ...block }) => block);
}

export function DocumentExportDialog({ open, onClose, context, onExported }: Props) {
  const t = useTranslations("documents");
  const tPdf = useTranslations("documentPdf");
  const tCommon = useTranslations("common");
  const toast = useToast();
  const confirm = useConfirm();

  const [catalog, setCatalog] = useState<DocumentCatalog | null>(null);
  const [styles, setStyles] = useState<DocumentStyle[]>([]);
  const [recipes, setRecipes] = useState<DocumentRecipe[]>([]);
  const [documentType, setDocumentType] = useState(context.documentType);
  const [recipeId, setRecipeId] = useState<string | null>(null);
  const [blocks, setBlocks] = useState<EditableBlock[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [styleId, setStyleId] = useState<string | null>(null);
  const [language, setLanguage] = useState<string>("");
  const [options, setOptions] = useState<ExportOptions>({});
  const [recipeName, setRecipeName] = useState("");
  const [pages, setPages] = useState<string[]>([]);
  const [previewState, setPreviewState] = useState<"idle" | "loading" | "error">("idle");
  const [previewError, setPreviewError] = useState("");
  const [busy, setBusy] = useState(false);
  const dragIndex = useRef<number | null>(null);

  // Katalog, Stile und Rezepte beim ersten Öffnen laden
  useEffect(() => {
    if (!open || catalog) return;
    void Promise.all([fetchCatalog(), listStyles(), listRecipes()])
      .then(([loadedCatalog, loadedStyles, loadedRecipes]) => {
        setCatalog(loadedCatalog);
        setStyles(loadedStyles ?? []);
        setRecipes(loadedRecipes ?? []);
      })
      .catch((error) => toast(error instanceof Error ? error.message : t("dialog.loadFailed"), "error"));
  }, [open, catalog, toast, t]);

  // Beim Öffnen und bei Wechsel des Dokumenttyps die Standardblöcke übernehmen. Die
  // Kontext-Parameter werden über ihren Inhalt verglichen (Aufrufer übergeben oft neue Objekte).
  const contextParamsKey = JSON.stringify(context.params ?? {});
  useEffect(() => {
    if (!catalog || recipeId) return;
    const type = catalog.document_types.find((entry) => entry.key === documentType) ?? catalog.document_types.find((entry) => entry.key === "custom");
    setBlocks(applyContextParams(type?.blocks ?? [], catalog, JSON.parse(contextParamsKey)).map(withKey));
  }, [catalog, documentType, recipeId, contextParamsKey]);

  useEffect(() => {
    if (open) {
      setDocumentType(context.documentType);
      setRecipeId(null);
    }
  }, [open, context.documentType]);

  const request = useMemo<DocumentRequest>(
    () => ({
      document_type: documentType,
      protocol_id: context.protocolId ?? null,
      blocks: stripKeys(blocks),
      style_id: styleId,
      options,
      language: language || null,
    }),
    [documentType, context.protocolId, blocks, styleId, options, language]
  );
  const requestKey = JSON.stringify(request);

  // Live-Vorschau, entprellt; ältere Anfragen werden abgebrochen
  useEffect(() => {
    if (!open || !catalog) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setPreviewState("loading");
      previewDocument(request, 3, controller.signal)
        .then((result) => {
          setPages(result?.pages ?? []);
          setPreviewState("idle");
        })
        .catch((error) => {
          if (controller.signal.aborted) return;
          setPreviewState("error");
          setPreviewError(error instanceof Error ? error.message : t("dialog.previewFailed"));
        });
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
    // requestKey bildet den Inhalt von request ab
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, catalog, requestKey]);

  const catalogByType = useMemo(() => new Map((catalog?.blocks ?? []).map((entry) => [entry.type, entry])), [catalog]);
  const documentTypes = (catalog?.document_types ?? []).filter((entry) => !entry.needs_protocol || context.protocolId);

  function blockName(type: string) {
    return tPdf(`blockType.${type}`);
  }

  function updateBlock(key: string, patch: Partial<EditableBlock>) {
    setBlocks((current) => current.map((block) => (block.key === key ? { ...block, ...patch } : block)));
  }

  function move(index: number, target: number) {
    setBlocks((current) => {
      if (target < 0 || target >= current.length) return current;
      const next = [...current];
      const [item] = next.splice(index, 1);
      next.splice(target, 0, item);
      return next;
    });
  }

  function addBlock(entry: CatalogBlock | null) {
    if (!entry) return;
    const block = withKey({ type: entry.type, params: defaultParams(entry.params_schema), hide_if_empty: true, level: 1 });
    setBlocks((current) => [...current, block]);
    setExpanded(block.key);
  }

  function onDrop(event: DragEvent, index: number) {
    event.preventDefault();
    if (dragIndex.current !== null) move(dragIndex.current, index);
    dragIndex.current = null;
  }

  function selectRecipe(recipe: DocumentRecipe | null) {
    if (!recipe) {
      setRecipeId(null);
      setRecipeName("");
      return;
    }
    setRecipeId(recipe.id);
    setRecipeName(recipe.name);
    setDocumentType(recipe.document_type);
    setBlocks(recipe.blocks.map(withKey));
    setOptions(recipe.options ?? {});
    setStyleId(recipe.style_id);
    setLanguage(recipe.language ?? "");
  }

  async function saveRecipe(asNew: boolean) {
    const body = { name: recipeName.trim(), document_type: documentType, blocks: stripKeys(blocks), options, style_id: styleId, language: language || null };
    try {
      const saved = asNew || !recipeId
        ? await browserApiFetch<DocumentRecipe>("/api/document-recipes", { method: "POST", body: JSON.stringify(body) })
        : await browserApiFetch<DocumentRecipe>(`/api/document-recipes/${recipeId}`, { method: "PATCH", body: JSON.stringify(body) });
      setRecipes((current) => [...current.filter((recipe) => recipe.id !== saved.id), saved].sort((a, b) => a.name.localeCompare(b.name)));
      setRecipeId(saved.id);
      toast(t("dialog.recipeSaved"), "success");
    } catch (error) {
      toast(error instanceof Error ? error.message : t("dialog.recipeSaveFailed"), "error");
    }
  }

  async function deleteRecipe() {
    if (!recipeId) return;
    const ok = await confirm({ tone: "danger", message: t("dialog.recipeDeleteConfirm", { name: recipeName }), confirmLabel: tCommon("delete") });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/document-recipes/${recipeId}`, { method: "DELETE" });
      setRecipes((current) => current.filter((recipe) => recipe.id !== recipeId));
      selectRecipe(null);
    } catch (error) {
      toast(error instanceof Error ? error.message : t("dialog.recipeSaveFailed"), "error");
    }
  }

  async function exportPdf() {
    if (busy) return;
    setBusy(true);
    // Noch innerhalb des Klicks öffnen, damit der Browser den Tab nicht blockiert.
    const pdfWindow = window.open("about:blank", "_blank");
    if (pdfWindow) pdfWindow.opener = null;
    try {
      const result = await renderDocument(request);
      if (!result?.content_url) throw new Error(t("dialog.exportFailed"));
      if (pdfWindow && !pdfWindow.closed) pdfWindow.location.replace(result.content_url);
      else window.open(result.content_url, "_blank", "noopener,noreferrer");
      toast(result.version_label ? t("dialog.exportedVersion", { version: result.version_label }) : t("dialog.exported"), "success");
      onExported?.();
    } catch (error) {
      pdfWindow?.close();
      toast(error instanceof Error && error.message ? error.message : t("dialog.exportFailed"), "error");
    } finally {
      setBusy(false);
    }
  }

  async function exportFormat(format: "csv" | "xlsx" | "ics" | "markdown") {
    try {
      const { blob, filename } = await exportDocumentFile(request, format);
      saveBlob(blob, filename);
    } catch (error) {
      toast(error instanceof Error && error.message ? error.message : t("dialog.exportFailed"), "error");
    }
  }

  const addOptions = (catalog?.blocks ?? []).slice().sort((a, b) => a.group.localeCompare(b.group));

  return (
    <Modal open={open} onClose={onClose} title={t("dialog.title")} size="fullscreen">
      <div className="docexport-layout">
        <aside className="docexport-panel">
          {!catalog ? (
            <p className="muted">{t("dialog.loading")}</p>
          ) : (
            <>
              <section className="docexport-section">
                <div className="two-col">
                  <label className="field-stack">
                    <span className="field-label">{t("dialog.documentType")}</span>
                    <select value={documentType} disabled={Boolean(recipeId)} onChange={(event) => setDocumentType(event.target.value)}>
                      {documentTypes.map((entry) => (
                        <option key={entry.key} value={entry.key}>{tPdf(`docType.${entry.key}`)}</option>
                      ))}
                    </select>
                  </label>
                  <div className="field-stack">
                    <span className="field-label">{t("dialog.recipe")}</span>
                    <SearchableSelect
                      options={recipes}
                      getId={(recipe) => recipe.id}
                      getLabel={(recipe) => recipe.name}
                      value={recipeId}
                      onChange={selectRecipe}
                      nullLabel={t("dialog.recipeNone")}
                    />
                  </div>
                </div>
              </section>

              <section className="docexport-section">
                <h3 className="docexport-heading">{t("dialog.blocks")}</h3>
                {blocks.length === 0 && <p className="muted">{t("dialog.noBlocks")}</p>}
                <ol className="docexport-blocks">
                  {blocks.map((block, index) => {
                    const entry = catalogByType.get(block.type);
                    const isOpen = expanded === block.key;
                    return (
                      <li
                        key={block.key}
                        className="docexport-block"
                        draggable
                        onDragStart={() => {
                          dragIndex.current = index;
                        }}
                        onDragOver={(event) => event.preventDefault()}
                        onDrop={(event) => onDrop(event, index)}
                      >
                        <div className="docexport-block-head">
                          <span className="docexport-drag" aria-hidden="true">⋮⋮</span>
                          <button type="button" className="docexport-block-name" aria-expanded={isOpen} onClick={() => setExpanded(isOpen ? null : block.key)}>
                            {block.title || blockName(block.type)}
                          </button>
                          <button type="button" className="button-icon-soft button-icon-soft-sm" aria-label={t("dialog.moveUp")} disabled={index === 0} onClick={() => move(index, index - 1)}>↑</button>
                          <button type="button" className="button-icon-soft button-icon-soft-sm" aria-label={t("dialog.moveDown")} disabled={index === blocks.length - 1} onClick={() => move(index, index + 1)}>↓</button>
                          <button type="button" className="button-icon-soft button-icon-soft-sm button-icon-soft-danger" aria-label={t("dialog.removeBlock")} onClick={() => setBlocks((current) => current.filter((item) => item.key !== block.key))}>✕</button>
                        </div>
                        {isOpen && entry && (
                          <div className="docexport-block-body">
                            <div className="two-col">
                              <label className="field-stack">
                                <span className="field-label">{t("dialog.blockTitle")}</span>
                                <input value={block.title ?? ""} placeholder={blockName(block.type)} onChange={(event) => updateBlock(block.key, { title: event.target.value || null })} />
                              </label>
                              <label className="field-stack">
                                <span className="field-label">{t("dialog.level")}</span>
                                <select value={block.level ?? 1} onChange={(event) => updateBlock(block.key, { level: Number(event.target.value) })}>
                                  {[1, 2, 3].map((level) => <option key={level} value={level}>{level}</option>)}
                                </select>
                              </label>
                            </div>
                            <label className="docexport-check">
                              <input type="checkbox" checked={block.hide_if_empty !== false} onChange={(event) => updateBlock(block.key, { hide_if_empty: event.target.checked })} />
                              <span>{t("dialog.hideIfEmpty")}</span>
                            </label>
                            <BlockParamForm schema={entry.params_schema} params={block.params} protocolId={context.protocolId} onChange={(params) => updateBlock(block.key, { params })} />
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ol>
                <div className="field-stack">
                  <span className="field-label">{t("dialog.addBlock")}</span>
                  <SearchableSelect
                    options={addOptions}
                    getId={(entry) => entry.type}
                    getLabel={(entry) => `${t(`groups.${entry.group}`)} · ${blockName(entry.type)}`}
                    value={null}
                    onChange={addBlock}
                    placeholder={t("dialog.addBlockPlaceholder")}
                  />
                </div>
              </section>

              <section className="docexport-section">
                <h3 className="docexport-heading">{t("dialog.layout")}</h3>
                <div className="two-col">
                  <label className="field-stack">
                    <span className="field-label">{t("dialog.style")}</span>
                    <select value={styleId ?? ""} onChange={(event) => setStyleId(event.target.value || null)}>
                      <option value="">{t("dialog.styleDefault")}</option>
                      {styles.map((style) => <option key={style.id} value={style.id}>{style.name}</option>)}
                    </select>
                  </label>
                  <label className="field-stack">
                    <span className="field-label">{t("dialog.language")}</span>
                    <select value={language} onChange={(event) => setLanguage(event.target.value)}>
                      <option value="">{t("dialog.languageDefault")}</option>
                      {catalog.languages.map((code) => <option key={code} value={code}>{t(`languages.${code}`)}</option>)}
                    </select>
                  </label>
                  <label className="field-stack">
                    <span className="field-label">{t("dialog.titlePage")}</span>
                    <select value={options.title_page ?? ""} onChange={(event) => setOptions((current) => ({ ...current, title_page: event.target.value || null }))}>
                      {TITLE_PAGES.map((value) => <option key={value} value={value}>{value ? t(`variants.titlePage.${value}`) : t("dialog.fromStyle")}</option>)}
                    </select>
                  </label>
                  <label className="field-stack">
                    <span className="field-label">{t("dialog.toc")}</span>
                    <select value={options.toc ?? ""} onChange={(event) => setOptions((current) => ({ ...current, toc: event.target.value || null }))}>
                      {TOCS.map((value) => <option key={value} value={value}>{value ? t(`variants.toc.${value}`) : t("dialog.fromStyle")}</option>)}
                    </select>
                  </label>
                  <label className="field-stack">
                    <span className="field-label">{t("dialog.orientation")}</span>
                    <select value={options.orientation ?? ""} onChange={(event) => setOptions((current) => ({ ...current, orientation: event.target.value || null }))}>
                      {ORIENTATIONS.map((value) => <option key={value} value={value}>{value ? t(`variants.orientation.${value}`) : t("dialog.fromStyle")}</option>)}
                    </select>
                  </label>
                  <label className="field-stack">
                    <span className="field-label">{t("dialog.watermark")}</span>
                    <select
                      value={options.watermark === undefined || options.watermark === null ? "" : String(options.watermark)}
                      onChange={(event) => setOptions((current) => ({ ...current, watermark: event.target.value === "" ? null : event.target.value === "true" }))}
                    >
                      <option value="">{t("dialog.watermarkAuto")}</option>
                      <option value="true">{t("dialog.watermarkOn")}</option>
                      <option value="false">{t("dialog.watermarkOff")}</option>
                    </select>
                  </label>
                </div>
                <label className="field-stack">
                  <span className="field-label">{t("dialog.documentTitle")}</span>
                  <input value={options.title ?? ""} onChange={(event) => setOptions((current) => ({ ...current, title: event.target.value || null }))} />
                </label>
              </section>

              <section className="docexport-section">
                <h3 className="docexport-heading">{t("dialog.recipeSection")}</h3>
                <label className="field-stack">
                  <span className="field-label">{t("dialog.recipeName")}</span>
                  <input value={recipeName} maxLength={160} onChange={(event) => setRecipeName(event.target.value)} />
                </label>
                <div className="docexport-actions-row">
                  {recipeId && <button type="button" className="button-danger" onClick={() => void deleteRecipe()}>{t("dialog.recipeDelete")}</button>}
                  <button type="button" className="button-secondary" disabled={!recipeName.trim()} onClick={() => void saveRecipe(true)}>{t("dialog.recipeSaveNew")}</button>
                  {recipeId && <button type="button" className="button-secondary" disabled={!recipeName.trim()} onClick={() => void saveRecipe(false)}>{t("dialog.recipeUpdate")}</button>}
                </div>
              </section>
            </>
          )}
        </aside>

        <section className="docexport-preview" aria-live="polite" aria-label={t("dialog.preview")}>
          <div className="docexport-preview-bar">
            <span className="field-label">{t("dialog.preview")}</span>
            {previewState === "loading" && <span className="muted">{t("dialog.previewLoading")}</span>}
          </div>
          {previewState === "error" ? (
            <StatusBanner tone="error" message={previewError} />
          ) : pages.length === 0 ? (
            <p className="muted">{t("dialog.previewEmpty")}</p>
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
      <div className="modal-actions">
        <button type="button" className="button-ghost" onClick={onClose}>{tCommon("cancel")}</button>
        <ActionMenu
          ariaLabel={t("dialog.moreFormats")}
          items={[
            { label: t("dialog.formatCsv"), onClick: () => void exportFormat("csv") },
            { label: t("dialog.formatXlsx"), onClick: () => void exportFormat("xlsx") },
            { label: t("dialog.formatIcs"), onClick: () => void exportFormat("ics") },
            { label: t("dialog.formatMarkdown"), onClick: () => void exportFormat("markdown") },
          ]}
        />
        <button type="button" className="button-primary" disabled={busy || !catalog} onClick={() => void exportPdf()}>
          {busy ? t("dialog.exporting") : t("dialog.exportPdf")}
        </button>
      </div>
    </Modal>
  );
}

/** Schaltfläche, die den Export-Dialog mit Kontext öffnet. */
export function DocumentExportButton({ context, className = "button-secondary", label }: { context: DocumentExportContext; className?: string; label?: string }) {
  const t = useTranslations("documents");
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className={className} onClick={() => setOpen(true)}>
        {label ?? t("dialog.open")}
      </button>
      {open && <DocumentExportDialog open={open} onClose={() => setOpen(false)} context={context} />}
    </>
  );
}
