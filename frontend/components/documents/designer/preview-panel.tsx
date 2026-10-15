"use client";

// Verbindliche Vorschau: rendert den aktuellen (ungespeicherten) Stand mit der echten
// Typst-Engine. Entprellt, veraltete Anfragen werden abgebrochen, Ergebnisse gecacht.
// Umschaltbar zwischen Beispielinhalten und echten Daten (mit gewähltem Protokoll, soweit der
// Benutzer Zugriff hat). Hinweise am Element: ein Klick wählt das betroffene Element aus.

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { loadSource } from "@/components/documents/designer/component-params";
import { useDesigner } from "@/components/documents/designer/designer-context";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { StatusBanner } from "@/components/ui/status-banner";
import { ApiError } from "@/lib/api/client";
import { apiErrorMessage, Diagnostic, previewDocument, SourceOption } from "@/lib/documents/api";

const DEBOUNCE_MS = 700;

type Props = { brandId: string | null; onDiagnostics: (items: Diagnostic[]) => void };

export function PreviewPanel({ brandId, onDiagnostics }: Props) {
  const t = useTranslations("documentStudio");
  const { content, documentType, catalog, select } = useDesigner();
  const [dataMode, setDataMode] = useState<"sample" | "data">("sample");
  const [protocolId, setProtocolId] = useState<string | null>(null);
  const [protocols, setProtocols] = useState<SourceOption[]>([]);
  const [pages, setPages] = useState<string[]>([]);
  const [pageCount, setPageCount] = useState(0);
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState<{ message: string; nodeId?: string | null } | null>(null);
  const [zoom, setZoom] = useState(1);
  const [diagnostics, setDiagnostics] = useState<Diagnostic[]>([]);
  const cache = useRef(new Map<string, { pages: string[]; count: number; diagnostics: Diagnostic[] }>());
  const hiddenPages = Math.max(0, pageCount - pages.length);
  const needsProtocol = catalog.document_types.find((item) => item.key === documentType)?.needs_protocol ?? false;

  useEffect(() => {
    if (dataMode === "data" && protocols.length === 0) void loadSource("protocols").then(setProtocols);
  }, [dataMode, protocols.length]);

  const key = JSON.stringify([content, dataMode, protocolId, brandId, documentType]);
  useEffect(() => {
    if (dataMode === "data" && needsProtocol && !protocolId) {
      setPages([]);
      return;
    }
    const cached = cache.current.get(key);
    if (cached) {
      setPages(cached.pages);
      setPageCount(cached.count);
      setDiagnostics(cached.diagnostics);
      onDiagnostics(cached.diagnostics);
      setState("idle");
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setState("loading");
      previewDocument({ document_type: documentType, content, data_mode: dataMode, protocol_id: dataMode === "data" ? protocolId : null, brand_id: brandId }, 12, controller.signal)
        .then((result) => {
          cache.current.set(key, { pages: result.pages, count: result.page_count, diagnostics: result.diagnostics });
          if (cache.current.size > 30) cache.current.delete(cache.current.keys().next().value as string);
          setPages(result.pages);
          setPageCount(result.page_count);
          setDiagnostics(result.diagnostics);
          onDiagnostics(result.diagnostics);
          setError(null);
          setState("idle");
        })
        .catch((reason) => {
          if (controller.signal.aborted) return;
          const detail = reason instanceof ApiError && reason.detail && typeof reason.detail === "object" ? (reason.detail as { node_id?: string | null }) : null;
          setError({ message: apiErrorMessage(reason, t("preview.failed")), nodeId: detail?.node_id ?? null });
          setState("error");
        });
    }, DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
    // onDiagnostics ist stabil genug; die Vorschau hängt nur am Inhalt
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return (
    <section className="studio-preview" aria-label={t("preview.title")}>
      <div className="studio-preview-bar">
        <div className="studio-preview-controls">
          <select value={dataMode} onChange={(event) => setDataMode(event.target.value as "sample" | "data")} aria-label={t("preview.dataMode")}>
            <option value="sample">{t("preview.sample")}</option>
            <option value="data">{t("preview.realData")}</option>
          </select>
          {dataMode === "data" && (
            <SearchableSelect options={protocols} getId={(item) => item.id} getLabel={(item) => (item.detail ? `${item.label} · ${item.detail}` : item.label)} value={protocolId} onChange={(item) => setProtocolId(item?.id ?? null)} placeholder={t("preview.chooseProtocol")} nullLabel={t("preview.noProtocol")} />
          )}
          <span className="studio-zoom">
            <button type="button" className="button-icon-soft button-icon-soft-sm" aria-label={t("toolbar.zoomOut")} onClick={() => setZoom((value) => Math.max(0.5, value - 0.25))}>
              −
            </button>
            <span>{Math.round(zoom * 100)}%</span>
            <button type="button" className="button-icon-soft button-icon-soft-sm" aria-label={t("toolbar.zoomIn")} onClick={() => setZoom((value) => Math.min(2, value + 0.25))}>
              +
            </button>
          </span>
        </div>
        <span className="muted" aria-live="polite">
          {state === "loading" ? t("preview.loading") : pageCount ? t("preview.pages", { count: pageCount }) : ""}
        </span>
      </div>
      {error && (
        <div className="studio-preview-error">
          <StatusBanner tone="error" message={error.message} />
          {error.nodeId && (
            <button type="button" className="button-secondary" onClick={() => select(error.nodeId ?? null)}>
              {t("preview.showElement")}
            </button>
          )}
        </div>
      )}
      {diagnostics.length > 0 && (
        <ul className="studio-diagnostics" aria-label={t("preview.issues")}>
          {diagnostics.map((item, index) => (
            <li key={index}>
              <button type="button" className={item.severity === "error" ? "studio-diagnostic studio-diagnostic-error" : "studio-diagnostic"} onClick={() => item.node_id && select(item.node_id)}>
                {t(`diagnosticCode.${item.code}`)}
                {item.detail ? ` · ${item.detail}` : ""}
              </button>
            </li>
          ))}
        </ul>
      )}
      {dataMode === "data" && needsProtocol && !protocolId && <p className="field-help">{t("preview.protocolRequired")}</p>}
      <div className="studio-preview-pages" style={{ zoom }}>
        {pages.map((page, index) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img key={index} className="studio-preview-page" src={page} alt={t("preview.pageAlt", { page: index + 1 })} />
        ))}
      </div>
      {hiddenPages ? <p className="field-help">{t("preview.morePages", { count: hiddenPages })}</p> : null}
    </section>
  );
}
