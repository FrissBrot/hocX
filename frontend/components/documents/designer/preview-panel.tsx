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
import { apiErrorMessage, Diagnostic, NodeBox, previewDocument, SourceOption } from "@/lib/documents/api";
import { Select } from "@/components/ui/select";

const DEBOUNCE_MS = 700;
// Modus «Einfach»: die Vorschau ist die Arbeitsfläche, Änderungen sollen schneller sichtbar sein
const SIMPLE_DEBOUNCE_MS = 350;

/** Modus «Einfach»: ein Klick in die Vorschau wählt den Knoten bzw. Baustein («source:…»). */
export type PreviewPicking = { selected: string | null; onPick: (nodeId: string) => void; labelFor: (nodeId: string) => string | null };

type Props = { brandId: string | null; onDiagnostics: (items: Diagnostic[]) => void; picking?: PreviewPicking };

type PreviewState = { pages: string[]; count: number; diagnostics: Diagnostic[]; boxes: NodeBox[]; pageSize: [number, number] | null };

export function PreviewPanel({ brandId, onDiagnostics, picking }: Props) {
  const t = useTranslations("documentStudio");
  const { content, documentType, catalog, select, dataMode, setDataMode, protocolId, setProtocolId, sessionTemplateId } = useDesigner();
  const [protocols, setProtocols] = useState<SourceOption[]>([]);
  const [pages, setPages] = useState<string[]>([]);
  const [pageCount, setPageCount] = useState(0);
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState<{ message: string; nodeId?: string | null } | null>(null);
  const [zoom, setZoom] = useState(1);
  const [diagnostics, setDiagnostics] = useState<Diagnostic[]>([]);
  const [boxes, setBoxes] = useState<NodeBox[]>([]);
  const [pageSize, setPageSize] = useState<[number, number] | null>(null);
  const cache = useRef(new Map<string, PreviewState>());
  const withBoxes = picking !== undefined;
  const hiddenPages = Math.max(0, pageCount - pages.length);
  // Im Vorlagen-Editor wählt das Backend ohne Auswahl die letzte Sitzung der Vorlage
  const needsProtocol = !sessionTemplateId && (catalog.document_types.find((item) => item.key === documentType)?.needs_protocol ?? false);

  useEffect(() => {
    if (dataMode === "data" && protocols.length === 0) void loadSource("protocols").then(setProtocols);
  }, [dataMode, protocols.length]);

  const key = JSON.stringify([content, dataMode, protocolId, brandId, documentType, sessionTemplateId, withBoxes]);
  const show = (result: PreviewState) => {
    setPages(result.pages);
    setPageCount(result.count);
    setDiagnostics(result.diagnostics);
    setBoxes(result.boxes);
    setPageSize(result.pageSize);
    onDiagnostics(result.diagnostics);
  };
  useEffect(() => {
    if (dataMode === "data" && needsProtocol && !protocolId) {
      setPages([]);
      return;
    }
    const cached = cache.current.get(key);
    if (cached) {
      show(cached);
      setState("idle");
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setState("loading");
      previewDocument({ document_type: documentType, content, data_mode: dataMode, protocol_id: dataMode === "data" ? protocolId : null, brand_id: brandId, protocol_template_id: sessionTemplateId }, 12, controller.signal, { nodeBoxes: withBoxes })
        .then((result) => {
          const loaded: PreviewState = { pages: result.pages, count: result.page_count, diagnostics: result.diagnostics, boxes: result.node_boxes ?? [], pageSize: result.page_size ?? null };
          cache.current.set(key, loaded);
          if (cache.current.size > 30) cache.current.delete(cache.current.keys().next().value as string);
          show(loaded);
          setError(null);
          setState("idle");
        })
        .catch((reason) => {
          if (controller.signal.aborted) return;
          const detail = reason instanceof ApiError && reason.detail && typeof reason.detail === "object" ? (reason.detail as { node_id?: string | null }) : null;
          setError({ message: apiErrorMessage(reason, t("preview.failed")), nodeId: detail?.node_id ?? null });
          setState("error");
        });
    }, withBoxes ? SIMPLE_DEBOUNCE_MS : DEBOUNCE_MS);
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
          <Select value={dataMode} onChange={(event) => setDataMode(event.target.value as "sample" | "data")} aria-label={t("preview.dataMode")}>
            <option value="sample">{t("preview.sample")}</option>
            <option value="data">{t("preview.realData")}</option>
          </Select>
          {dataMode === "data" && (
            <SearchableSelect options={protocols} getId={(item) => item.id} getLabel={(item) => (item.detail ? `${item.label} · ${item.detail}` : item.label)} value={protocolId} onChange={(item) => setProtocolId(item?.id ?? null)} placeholder={t("preview.chooseProtocol")} nullLabel={sessionTemplateId ? t("preview.latestSession") : t("preview.noProtocol")} />
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
      <div className={picking ? "studio-preview-pages studio-preview-pages-spread" : "studio-preview-pages"} style={{ zoom }}>
        {pages.map((page, index) =>
          picking ? (
            <PickablePage key={index} src={page} alt={t("preview.pageAlt", { page: index + 1 })} boxes={boxes.filter((box) => box.page === index + 1)} pageSize={pageSize} picking={picking} />
          ) : (
            // eslint-disable-next-line @next/next/no-img-element
            <img key={index} className="studio-preview-page" src={page} alt={t("preview.pageAlt", { page: index + 1 })} />
          )
        )}
      </div>
      {hiddenPages ? <p className="field-help">{t("preview.morePages", { count: hiddenPages })}</p> : null}
    </section>
  );
}

/** Seite mit Klickflächen: je Knoten bzw. Baustein ein Rechteck (Prozent der Seite), grössere
 * zuerst, damit Bausteine innerhalb des Protokollinhalts obenauf liegen. */
function PickablePage({ src, alt, boxes, pageSize, picking }: { src: string; alt: string; boxes: NodeBox[]; pageSize: [number, number] | null; picking: PreviewPicking }) {
  const ordered = [...boxes].sort((left, right) => right.width * right.height - left.width * left.height);
  return (
    <div className="studio-preview-page-wrap">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img className="studio-preview-page" src={src} alt={alt} />
      {pageSize &&
        ordered.map((box, index) => {
          const label = picking.labelFor(box.node_id);
          if (!label) return null;
          const selected = picking.selected === box.node_id;
          return (
            <button
              key={`${box.node_id}-${index}`}
              type="button"
              className={selected ? "studio-preview-hit studio-preview-hit-selected" : "studio-preview-hit"}
              // Laufzeitposition aus der Vorschau
              style={{ left: `${(box.x / pageSize[0]) * 100}%`, top: `${(box.y / pageSize[1]) * 100}%`, width: `${(box.width / pageSize[0]) * 100}%`, height: `${(box.height / pageSize[1]) * 100}%` }}
              aria-label={label}
              aria-pressed={selected}
              title={label}
              onClick={() => picking.onPick(box.node_id)}
            >
              {selected ? <span className="studio-preview-hit-label">{label}</span> : null}
            </button>
          );
        })}
    </div>
  );
}
