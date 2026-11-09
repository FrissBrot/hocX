"use client";

// Export Center: ein einheitlicher Exportablauf für alle Dokumente (Design «Todo Export Popup»).
// Links: Auswahl (bei Pendenzen), Aussehen (Vorlage, vorbelegt nach Prioritätsregel: Zuweisung >
// Mandanten-Standard > Plattform-Standard) und weitere Optionen. Rechts: Vorschau im gewählten
// Format (PDF-Seiten, Tabelle für CSV/Excel, WhatsApp-Text). Unten: Spalten, Format, Ausführen.
// Gestaltet wird ausschliesslich im Document Studio - hier gibt es bewusst keinen Designer.

import { Fragment, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { templateDisplayName } from "@/components/documents/studio-labels";
import { TodoExportFilters, useExportTodos } from "@/components/documents/todo-export-filters";
import { Badge } from "@/components/ui/badge";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal } from "@/components/ui/modal";
import { Select } from "@/components/ui/select";
import { StatusBanner } from "@/components/ui/status-banner";
import { useToast } from "@/contexts/toast-context";
import { locales } from "@/i18n/locale-config.generated";
import { browserApiBaseUrl } from "@/lib/api/client";
import {
  apiErrorMessage,
  Brand,
  Capabilities,
  DocumentRequest,
  DocumentTemplateInfo,
  DocumentTypeInfo,
  exportColumns,
  exportDocumentFile,
  ExportOptions,
  ExportPreview,
  exportPreview,
  previewDocument,
  renderDocument,
  saveBlob,
  studioApi,
} from "@/lib/documents/api";
import {
  initialTodoExportFilter,
  localIsoDate,
  matchesTodoFilter,
  nextSessionDate,
  TodoExportFilter,
  todoExportParams,
} from "@/lib/documents/todo-export-filter";

export type DocumentExportContext = {
  /** Dokumenttyp (protocol, invitation, todos, events, statistics, list, …). */
  documentType: string;
  protocolId?: string | null;
  /** Seitenkontext, z. B. aktive Filter der Seite (gilt für passende Komponenten). */
  params?: Record<string, unknown>;
};

type Props = {
  open: boolean;
  onClose: () => void;
  context: DocumentExportContext;
  onExported?: () => void;
};


type ExportFormat = "pdf" | "csv" | "xlsx" | "ics" | "markdown";

const PREVIEW_DEBOUNCE_MS = 400;
const PROTOCOL_TYPES = ["protocol", "invitation", "agenda", "attendance"];

const WHATSAPP_MARKS: Partial<Record<string, (text: string, key: number) => ReactNode>> = {
  "*": (text, key) => <strong key={key}>{text}</strong>,
  _: (text, key) => <em key={key}>{text}</em>,
  "~": (text, key) => <s key={key}>{text}</s>,
};

/** WhatsApp-Formatierung (*fett*, _kursiv_, ~durchgestrichen~) als Elemente, ohne HTML. */
function whatsappText(text: string): ReactNode[] {
  return text.split(/(\*[^*\n]+\*|_[^_\n]+_|~[^~\n]+~)/g).map((part, index) => {
    const mark = WHATSAPP_MARKS[part[0]];
    if (mark && part.length >= 3 && part.endsWith(part[0])) return mark(part.slice(1, -1), index);
    return <Fragment key={index}>{part}</Fragment>;
  });
}

export function DocumentExportDialog({ open, onClose, context, onExported }: Props) {
  const t = useTranslations("documentStudio");
  const toast = useToast();
  const [documentType, setDocumentType] = useState(context.documentType);
  const [types, setTypes] = useState<DocumentTypeInfo[]>([]);
  const [templates, setTemplates] = useState<DocumentTemplateInfo[] | null>(null);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [brandId, setBrandId] = useState<string>("");
  const [language, setLanguage] = useState<string>("");
  const [options, setOptions] = useState<ExportOptions>({ watermark: "auto" });
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [format, setFormat] = useState<ExportFormat>("pdf");
  const [pages, setPages] = useState<string[]>([]);
  const [pageCount, setPageCount] = useState(0);
  const [dataPreview, setDataPreview] = useState<ExportPreview | null>(null);
  const [previewState, setPreviewState] = useState<"idle" | "loading" | "error">("idle");
  const [previewError, setPreviewError] = useState("");
  const [busy, setBusy] = useState(false);
  // Spalten für CSV, Excel und Text: alle angeboten, abgewählte gelten nur für diesen Export
  const [columns, setColumns] = useState<string[]>([]);
  const [excludedColumns, setExcludedColumns] = useState<string[]>([]);
  // Pendenzen: Status, Fälligkeit, Tag, Person, Protokoll und Auswahl von Hand
  const [todoFilter, setTodoFilter] = useState<TodoExportFilter>(() => initialTodoExportFilter(context.params));
  const isTodos = documentType === "todos";
  const todos = useExportTodos(open && isTodos);
  const cache = useRef(new Map<string, { pages: string[]; count: number }>());

  useEffect(() => {
    if (open) setDocumentType(context.documentType);
  }, [open, context.documentType]);

  // Katalog (Dokumenttypen, Formate), Rechte und Brand-Profile einmal laden
  useEffect(() => {
    if (!open || capabilities) return;
    void Promise.all([studioApi.capabilities(), studioApi.catalog(), studioApi.brands()])
      .then(([loadedCapabilities, catalog, loadedBrands]) => {
        setCapabilities(loadedCapabilities);
        setTypes(catalog.document_types);
        setBrands(loadedBrands ?? []);
      })
      .catch((error) => toast(apiErrorMessage(error, t("export.loadFailed")), "error"));
    // t/toast sind während der Lebensdauer der Komponente unveränderlich
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, capabilities]);

  // Veröffentlichte Vorlagen des Dokumenttyps; vorgewählt ist die geltende Standardvorlage
  useEffect(() => {
    if (!open) return;
    setTemplates(null);
    void studioApi
      .listTemplates({ documentType })
      .then((loaded) => {
        const usable = (loaded ?? []).filter((item) => item.published_revision && item.status === "active");
        setTemplates(usable);
        setTemplateId(usable.find((item) => item.is_default)?.id ?? usable[0]?.id ?? null);
      })
      .catch((error) => {
        setTemplates([]);
        toast(apiErrorMessage(error, t("export.loadFailed")), "error");
      });
    // t/toast sind während der Lebensdauer der Komponente unveränderlich
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, documentType]);

  const typeInfo = types.find((item) => item.key === documentType);
  const formats: ExportFormat[] = ["pdf", ...((typeInfo?.formats ?? []) as ExportFormat[])];
  useEffect(() => {
    if (typeInfo && !["pdf", ...typeInfo.formats].includes(format)) setFormat("pdf");
  }, [typeInfo, format]);

  const today = localIsoDate();
  const loadedTodos = Array.isArray(todos) ? todos : null;
  const nextSession = useMemo(() => (loadedTodos ? nextSessionDate(loadedTodos, today) : null), [loadedTodos, today]);
  const todoDates = useMemo(() => ({ today, nextSession }), [today, nextSession]);
  const selectedTodos = useMemo(() => {
    if (!isTodos || !loadedTodos) return null;
    const excluded = new Set(todoFilter.exclude_ids);
    return loadedTodos.filter((todo) => matchesTodoFilter(todo, todoFilter, todoDates) && !excluded.has(todo.id)).length;
  }, [isTodos, loadedTodos, todoFilter, todoDates]);

  const paramsKey = JSON.stringify({ ...(context.params ?? {}), ...(isTodos ? todoExportParams(todoFilter, todoDates) : {}) });
  const request = useMemo<DocumentRequest>(
    () => ({
      document_type: documentType,
      protocol_id: context.protocolId ?? null,
      template_id: templateId,
      brand_id: brandId || null,
      params: JSON.parse(paramsKey),
      options,
      language: language || null,
    }),
    [documentType, context.protocolId, templateId, brandId, paramsKey, options, language]
  );

  // Vorschau im gewählten Format: entprellt, veraltete Anfragen werden abgebrochen. PDF-Seiten
  // werden gecacht; CSV/Excel/Text kommen gekürzt von /documents/export/preview.
  const requestKey = JSON.stringify(request);
  const dataFormat = format === "csv" || format === "xlsx" || format === "markdown" ? format : null;
  const excludedKey = JSON.stringify(excludedColumns);
  useEffect(() => {
    if (!open || !templateId || format === "ics") return;
    const cached = format === "pdf" ? cache.current.get(requestKey) : undefined;
    if (cached) {
      setPages(cached.pages);
      setPageCount(cached.count);
      setPreviewState("idle");
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setPreviewState("loading");
      const done = dataFormat
        ? exportPreview(request, dataFormat, JSON.parse(excludedKey), controller.signal).then((result) => setDataPreview(result))
        : previewDocument(request, 4, controller.signal).then((result) => {
            const count = result.page_count || result.pages.length;
            cache.current.set(requestKey, { pages: result.pages, count });
            setPages(result.pages);
            setPageCount(count);
          });
      done
        .then(() => setPreviewState("idle"))
        .catch((error) => {
          if (controller.signal.aborted) return;
          setPreviewState("error");
          setPreviewError(apiErrorMessage(error, t("export.previewFailed")));
        });
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
    // t/toast sind während der Lebensdauer der Komponente unveränderlich
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, templateId, requestKey, request, format, dataFormat, excludedKey]);

  // Spaltenliste zur aktuellen Vorlage/Sprache/Filter; Optionen (Titel, Wasserzeichen) ändern sie nicht
  // options weglassen (nicht null: der Server erwartet ein Objekt und lehnte die Anfrage sonst ab)
  const { options: _options, ...columnsRequest } = request;
  const columnsKey = JSON.stringify(columnsRequest);
  const hasTableFormats = (typeInfo?.formats ?? []).some((item) => item !== "ics");
  useEffect(() => {
    if (!open || !templateId || !hasTableFormats) {
      setColumns([]);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      exportColumns(JSON.parse(columnsKey) as DocumentRequest, controller.signal)
        .then((loaded) => {
          setColumns(loaded);
          setExcludedColumns((current) => current.filter((label) => loaded.includes(label)));
        })
        .catch(() => {
          if (!controller.signal.aborted) setColumns([]);
        });
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [open, templateId, columnsKey, hasTableFormats]);

  function toggleColumn(label: string) {
    setExcludedColumns((current) =>
      current.includes(label) ? current.filter((item) => item !== label) : current.length + 1 < columns.length ? [...current, label] : current
    );
  }

  async function createPdf() {
    // Noch im Klick öffnen, damit der Browser das neue Fenster nicht blockiert
    const pdfWindow = window.open("about:blank", "_blank");
    if (pdfWindow) pdfWindow.opener = null;
    try {
      const result = await renderDocument(request);
      const url = `${browserApiBaseUrl}${result.content_url}`;
      if (pdfWindow && !pdfWindow.closed) pdfWindow.location.replace(url);
      else window.open(url, "_blank", "noopener,noreferrer");
      toast(result.version_label ? t("export.createdVersion", { version: result.version_label }) : t("export.created"), "success", {
        onMessageClick: () => window.open(url, "_blank", "noopener,noreferrer"),
      });
      onExported?.();
    } catch (error) {
      pdfWindow?.close();
      throw error;
    }
  }

  // Text (Markdown) landet für WhatsApp direkt in der Zwischenablage. ClipboardItem mit Promise
  // hält die Nutzergeste über den Serveraufruf hinweg (Safari lehnt writeText danach sonst ab).
  async function copyMarkdown() {
    const text = exportDocumentFile(request, "markdown", excludedColumns).then(({ blob }) => blob.text());
    if (typeof ClipboardItem !== "undefined" && navigator.clipboard?.write) {
      await navigator.clipboard.write([new ClipboardItem({ "text/plain": text.then((value) => new Blob([value], { type: "text/plain" })) })]);
    } else {
      await navigator.clipboard.writeText(await text);
    }
    toast(t("export.markdownCopied"), "success");
  }

  async function run() {
    setBusy(true);
    try {
      if (format === "pdf") await createPdf();
      else if (format === "markdown") await copyMarkdown();
      else {
        const { blob, filename } = await exportDocumentFile(request, format, format === "ics" ? [] : excludedColumns);
        saveBlob(blob, filename);
      }
    } catch (error) {
      toast(apiErrorMessage(error, t("export.failed")), "error");
    } finally {
      setBusy(false);
    }
  }

  const selectableTypes = types.filter((item) => (context.protocolId ? PROTOCOL_TYPES.includes(item.key) || item.key === context.documentType : item.key === context.documentType));
  const selected = templates?.find((item) => item.id === templateId) ?? null;
  const showColumns = format !== "pdf" && format !== "ics" && columns.length > 0;
  const runLabel = selectedTodos === null ? t(`export.run.${format}`) : t("export.runCount", { label: t(`export.run.${format}`), count: selectedTodos });
  const runDisabled = busy || !templateId || selectedTodos === 0;
  const optionBits = [
    language ? t(`language.${language}`) : null,
    options.title ? t("export.summaryTitle") : null,
    options.watermark === "on" ? t("export.summaryWatermarkOn") : options.watermark === "off" ? t("export.summaryWatermarkOff") : null,
    brandId ? brands.find((brand) => brand.id === brandId)?.name ?? null : null,
  ].filter(Boolean);
  const watermarkOptions = [
    { value: "auto", label: t("export.watermarkAutoShort") },
    { value: "on", label: t("export.watermarkOn") },
    // Entwürfe ohne Kennzeichnung nur mit Schreibrecht (STUDIO-007, serverseitig erzwungen)
    ...(capabilities?.unmark_drafts ? [{ value: "off", label: t("export.watermarkOff") }] : []),
  ];
  const morePages = Math.max(pageCount - pages.length, 0);
  const sheetRows = (dataPreview?.tables ?? []).reduce((sum, table) => sum + table.total_rows, 0);
  const sheetColumns = dataPreview?.tables[0]?.rows[0]?.length ?? 0;
  const previewMeta =
    format === "pdf"
      ? pageCount
        ? [t("export.previewPages", { count: pageCount }), selected ? templateDisplayName(t, selected) : null].filter(Boolean).join(" · ")
        : ""
      : format === "markdown"
        ? dataPreview?.text != null
          ? t("export.previewChars", { count: dataPreview.text.length })
          : ""
        : format === "ics"
          ? ""
          : dataPreview
            ? t("export.previewRows", { rows: sheetRows, columns: sheetColumns })
            : "";

  const footer = (
    <div className="export-footer">
      {showColumns && (
        <div className="export-columns" role="group" aria-label={t("export.columns")}>
          <span className="field-label">{t("export.columns")}</span>
          {columns.map((label) => {
            const on = !excludedColumns.includes(label);
            return (
              <button key={label} type="button" aria-pressed={on} className={on ? "button-pill button-pill-active" : "button-pill"} onClick={() => toggleColumn(label)}>
                {label}
              </button>
            );
          })}
          <span className="field-help">{t("export.columnsHelp")}</span>
        </div>
      )}
      <div className="export-footer-row">
        <div className="export-formats" role="radiogroup" aria-label={t("export.formatLabel")}>
          {formats.map((item) => (
            <button
              key={item}
              type="button"
              role="radio"
              aria-checked={format === item}
              className={format === item ? "export-format export-format-active" : "export-format"}
              onClick={() => setFormat(item)}
            >
              <span className="export-format-name">{t(`export.format.${item}`)}</span>
              <span className="export-format-sub">{t(`export.formatSub.${item}`)}</span>
            </button>
          ))}
        </div>
        <div className="export-footer-actions">
          <button type="button" className="button-ghost" onClick={onClose}>
            {t("export.cancel")}
          </button>
          <button type="button" className="button-primary" disabled={runDisabled} onClick={() => void run()}>
            {busy ? t("export.working") : runLabel}
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <Modal className="studio-modal export-modal" open={open} onClose={onClose} title={t("export.title")} description={t("export.description")} size="fullscreen" footer={footer}>
      <div className="export-dialog">
        <div className="export-dialog-panel">
          {selectableTypes.length > 1 && (
            <label className="field-stack export-step">
              <span className="field-label">{t("export.documentType")}</span>
              <Select value={documentType} onChange={(event) => setDocumentType(event.target.value)}>
                {selectableTypes.map((item) => (
                  <option key={item.key} value={item.key}>
                    {t(`docType.${item.key}`)}
                  </option>
                ))}
              </Select>
            </label>
          )}

          {isTodos && <TodoExportFilters todos={todos} dates={todoDates} value={todoFilter} onChange={setTodoFilter} />}

          <section className="export-step" aria-labelledby="export-step-appearance">
            <div className="export-step-head">
              <span className="export-step-number" aria-hidden="true">
                {isTodos ? 2 : 1}
              </span>
              <h3 id="export-step-appearance" className="export-step-title">
                {t("export.appearance")}
              </h3>
              {capabilities?.edit_templates && selected && (
                <a className="studio-link export-step-meta" href={selected.editable ? `/documents/templates/${selected.id}` : "/documents"}>
                  {t("export.openInStudio")}
                </a>
              )}
            </div>
            {templates === null ? (
              <p className="muted">{t("common.loading")}</p>
            ) : templates.length === 0 ? (
              <StatusBanner tone="neutral" message={t("export.noTemplates")} />
            ) : (
              <div className="export-templates" role="radiogroup" aria-label={t("export.template")}>
                {templates.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    role="radio"
                    aria-checked={item.id === templateId}
                    className={item.id === templateId ? "export-template export-template-active" : "export-template"}
                    onClick={() => setTemplateId(item.id)}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img className="export-template-thumb" src={studioApi.thumbnailUrl(item.id, item.published_revision?.id ?? "")} alt="" loading="lazy" />
                    <span className="export-template-name">
                      {templateDisplayName(t, item)}
                      {item.is_default && <Badge variant="info">{t("library.default")}</Badge>}
                    </span>
                  </button>
                ))}
              </div>
            )}

            <button type="button" className="export-options-toggle" aria-expanded={optionsOpen} onClick={() => setOptionsOpen(!optionsOpen)}>
              <span className="export-options-chevron" aria-hidden="true">
                ›
              </span>
              {t("export.options")}
              <span className="muted">· {optionBits.length ? optionBits.join(", ") : t("export.optionsHint")}</span>
            </button>
            {optionsOpen && (
              <div className="export-options">
                <label className="field-stack">
                  <span className="field-label">{t("export.documentTitle")}</span>
                  <input value={options.title ?? ""} maxLength={300} placeholder={t("export.documentTitleAuto")} onChange={(event) => setOptions({ ...options, title: event.target.value || null })} />
                </label>
                <div className="two-col">
                  <label className="field-stack">
                    <span className="field-label">{t("export.language")}</span>
                    <Select value={language} onChange={(event) => setLanguage(event.target.value)}>
                      <option value="">{t("export.languageDefault")}</option>
                      {locales.map((code) => (
                        <option key={code} value={code}>
                          {t(`language.${code}`)}
                        </option>
                      ))}
                    </Select>
                  </label>
                  <div className="field-stack">
                    <span className="field-label" id="export-watermark-label">
                      {t("export.watermark")}
                    </span>
                    <FilterTabs
                      options={watermarkOptions}
                      value={options.watermark ?? "auto"}
                      onChange={(watermark) => setOptions({ ...options, watermark: watermark as ExportOptions["watermark"] })}
                    />
                  </div>
                </div>
                {brands.length > 1 && (
                  <label className="field-stack">
                    <span className="field-label">{t("export.brand")}</span>
                    <Select value={brandId} onChange={(event) => setBrandId(event.target.value)}>
                      <option value="">{t("export.brandDefault")}</option>
                      {brands.map((brand) => (
                        <option key={brand.id} value={brand.id}>
                          {brand.name}
                        </option>
                      ))}
                    </Select>
                  </label>
                )}
              </div>
            )}
          </section>
        </div>

        <section className="export-dialog-preview" aria-live="polite" aria-label={t("export.preview")}>
          <div className="export-preview-bar">
            <span className="export-preview-title">{t("export.preview")}</span>
            <span className="export-preview-meta">{previewMeta}</span>
            {previewState === "loading" && <span className="export-preview-loading">{t("export.previewUpdating")}</span>}
          </div>
          <div className={previewState === "loading" ? "export-preview-body export-preview-body-loading" : "export-preview-body"}>
            {previewState === "error" && <StatusBanner tone="error" message={previewError} />}
            {!templateId ? (
              <p className="muted">{t("export.chooseTemplate")}</p>
            ) : format === "ics" ? (
              <p className="muted">{t("export.previewNone")}</p>
            ) : format === "pdf" ? (
              <div className="studio-preview-pages">
                {pages.map((page, index) => (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img key={index} className="studio-preview-page" src={page} alt={t("preview.pageAlt", { page: index + 1 })} />
                ))}
                {morePages ? <p className="field-help">{t("export.previewHint")}</p> : null}
              </div>
            ) : format === "markdown" ? (
              dataPreview?.text != null && (
                <div className="export-whatsapp">
                  <div className="export-whatsapp-bubble">{whatsappText(dataPreview.text)}</div>
                  <p className="export-whatsapp-hint">{t("export.previewWhatsapp")}</p>
                </div>
              )
            ) : dataPreview && sheetRows === 0 ? (
              <p className="muted">{t("export.previewEmpty")}</p>
            ) : (
              dataPreview?.tables.map((table, index) => {
                const [header = [], ...rows] = table.rows;
                const hiddenRows = table.total_rows - rows.length;
                return (
                  <div key={index} className="export-sheet">
                    {dataPreview.tables.length > 1 && <p className="field-label">{table.title}</p>}
                    <div className="export-sheet-scroll">
                      <table className="export-sheet-table">
                        <thead>
                          <tr>
                            <th scope="col" aria-hidden="true" />
                            {header.map((cell, cellIndex) => (
                              <th key={cellIndex} scope="col">
                                {cell}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {rows.map((row, rowIndex) => (
                            <tr key={rowIndex}>
                              <th scope="row">{rowIndex + 2}</th>
                              {row.map((cell, cellIndex) => (
                                <td key={cellIndex} title={cell}>
                                  {cell}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {hiddenRows ? <p className="field-help">{t("export.previewMoreRows", { count: hiddenRows })}</p> : null}
                  </div>
                );
              })
            )}
          </div>
        </section>
      </div>
    </Modal>
  );
}

export function DocumentExportButton({ context, className = "button-secondary", label }: { context: DocumentExportContext; className?: string; label?: string }) {
  const t = useTranslations("documentStudio");
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className={className} onClick={() => setOpen(true)}>
        {label ?? t("export.button")}
      </button>
      {open && <DocumentExportDialog open={open} onClose={() => setOpen(false)} context={context} />}
    </>
  );
}
