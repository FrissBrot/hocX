"use client";

// Export Center: ein einheitlicher Exportablauf für alle Dokumente. Vorlage wählen (vorbelegt
// nach Prioritätsregel: Zuweisung > Mandanten-Standard > Plattform-Standard), Vorschau mit den
// echten Daten prüfen, Optionen setzen, PDF erzeugen oder ein Zusatzformat laden. Gestaltet wird
// ausschliesslich im Document Studio - hier gibt es bewusst keinen Designer.

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { templateDisplayName } from "@/components/documents/studio-labels";
import { Badge } from "@/components/ui/badge";
import { Modal } from "@/components/ui/modal";
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
  exportDocumentFile,
  ExportOptions,
  previewDocument,
  renderDocument,
  saveBlob,
  studioApi,
} from "@/lib/documents/api";
import { Select } from "@/components/ui/select";

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

const PREVIEW_DEBOUNCE_MS = 400;
const PROTOCOL_TYPES = ["protocol", "invitation", "agenda", "attendance"];

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
  const [pages, setPages] = useState<string[]>([]);
  const [previewState, setPreviewState] = useState<"idle" | "loading" | "error">("idle");
  const [previewError, setPreviewError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const cache = useRef(new Map<string, string[]>());

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
  const paramsKey = JSON.stringify(context.params ?? {});
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

  // Vorschau: entprellt, veraltete Anfragen werden abgebrochen, Ergebnisse gecacht
  const requestKey = JSON.stringify(request);
  useEffect(() => {
    if (!open || !templateId) return;
    const cached = cache.current.get(requestKey);
    if (cached) {
      setPages(cached);
      setPreviewState("idle");
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setPreviewState("loading");
      previewDocument(request, 4, controller.signal)
        .then((result) => {
          cache.current.set(requestKey, result.pages);
          setPages(result.pages);
          setPreviewState("idle");
        })
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
  }, [open, templateId, requestKey, request]);

  async function createPdf() {
    setBusy("pdf");
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
      toast(apiErrorMessage(error, t("export.failed")), "error");
    } finally {
      setBusy(null);
    }
  }

  async function downloadFormat(format: "csv" | "xlsx" | "ics" | "markdown") {
    setBusy(format);
    try {
      const { blob, filename } = await exportDocumentFile(request, format);
      saveBlob(blob, filename);
    } catch (error) {
      toast(apiErrorMessage(error, t("export.failed")), "error");
    } finally {
      setBusy(null);
    }
  }

  const selectableTypes = types.filter((item) => (context.protocolId ? PROTOCOL_TYPES.includes(item.key) || item.key === context.documentType : item.key === context.documentType));
  const selected = templates?.find((item) => item.id === templateId) ?? null;

  return (
    <Modal className="studio-modal" open={open} onClose={onClose} title={t("export.title")} description={t("export.description")} size="fullscreen">
      <div className="studio-export">
        <aside className="studio-export-panel">
          {selectableTypes.length > 1 && (
            <label className="field-stack">
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

          <section className="studio-export-section" aria-labelledby="studio-export-templates">
            <h3 id="studio-export-templates" className="studio-section-title">
              {t("export.template")}
            </h3>
            {templates === null ? (
              <p className="muted">{t("common.loading")}</p>
            ) : templates.length === 0 ? (
              <StatusBanner tone="neutral" message={t("export.noTemplates")} />
            ) : (
              <div className="studio-variant-list" role="radiogroup" aria-label={t("export.template")}>
                {templates.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    role="radio"
                    aria-checked={item.id === templateId}
                    className={item.id === templateId ? "studio-variant studio-variant-active" : "studio-variant"}
                    onClick={() => setTemplateId(item.id)}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img className="studio-variant-thumb" src={studioApi.thumbnailUrl(item.id, item.published_revision?.id ?? "")} alt="" loading="lazy" />
                    <span className="studio-variant-name">{templateDisplayName(t, item)}</span>
                    {item.is_default && (
                      <Badge variant="info" className="studio-variant-badge">
                        {t("library.default")}
                      </Badge>
                    )}
                  </button>
                ))}
              </div>
            )}
            {capabilities?.edit_templates && selected && (
              <a className="studio-link" href={selected.editable ? `/documents/templates/${selected.id}` : "/documents"}>
                {t("export.openInStudio")}
              </a>
            )}
          </section>

          <section className="studio-export-section" aria-labelledby="studio-export-options">
            <h3 id="studio-export-options" className="studio-section-title">
              {t("export.options")}
            </h3>
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
            <label className="field-stack">
              <span className="field-label">{t("export.documentTitle")}</span>
              <input value={options.title ?? ""} maxLength={300} placeholder={t("export.documentTitleAuto")} onChange={(event) => setOptions({ ...options, title: event.target.value || null })} />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("export.watermark")}</span>
              <Select value={options.watermark ?? "auto"} onChange={(event) => setOptions({ ...options, watermark: event.target.value as ExportOptions["watermark"] })}>
                <option value="auto">{t("export.watermarkAuto")}</option>
                <option value="on">{t("export.watermarkOn")}</option>
                {/* Entwürfe ohne Kennzeichnung nur mit Schreibrecht (STUDIO-007, serverseitig erzwungen) */}
                {capabilities?.unmark_drafts && <option value="off">{t("export.watermarkOff")}</option>}
              </Select>
            </label>
          </section>

          <div className="modal-actions studio-export-actions">
            {(typeInfo?.formats ?? []).map((format) => (
              <button key={format} type="button" className="button-secondary" disabled={!!busy || !templateId} onClick={() => void downloadFormat(format)}>
                {busy === format ? t("export.working") : t(`export.format.${format}`)}
              </button>
            ))}
            <button type="button" className="button-primary" disabled={!!busy || !templateId} onClick={() => void createPdf()}>
              {busy === "pdf" ? t("export.working") : t("export.createPdf")}
            </button>
          </div>
        </aside>

        <section className="studio-export-preview" aria-live="polite" aria-label={t("export.preview")}>
          <div className="studio-preview-bar">
            <span className="field-label">{t("export.preview")}</span>
            {previewState === "loading" && <span className="muted">{t("preview.loading")}</span>}
          </div>
          {previewState === "error" && <StatusBanner tone="error" message={previewError} />}
          {!templateId ? (
            <p className="muted">{t("export.chooseTemplate")}</p>
          ) : (
            <div className="studio-preview-pages">
              {pages.map((page, index) => (
                // eslint-disable-next-line @next/next/no-img-element
                <img key={index} className="studio-preview-page" src={page} alt={t("preview.pageAlt", { page: index + 1 })} />
              ))}
            </div>
          )}
          <p className="field-help">{t("export.previewHint")}</p>
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
