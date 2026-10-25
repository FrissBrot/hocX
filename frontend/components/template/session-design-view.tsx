"use client";

// Ansicht «PDF» bzw. «Einladung» im Vorlagen-Editor: Seitengestaltung dieses Sitzungsdokuments.
// Gehört die Gestaltung allein dieser Vorlage, wird sie hier direkt im Designer bearbeitet
// (Vorschau mit den Traktanden der Vorlage und den Inhalten der letzten Sitzung). Sonst zeigt
// die Ansicht die geltende Standardgestaltung und bietet an, eine eigene Gestaltung anzulegen.

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { TemplateDesigner } from "@/components/documents/designer/designer";
import { templateDisplayName } from "@/components/documents/studio-labels";
import { StatusBanner } from "@/components/ui/status-banner";
import { useToast } from "@/contexts/toast-context";
import { apiErrorMessage, previewDocument, SessionDesign, studioApi } from "@/lib/documents/api";
import type { TemplateSummary } from "@/types/api";

type Props = { sessionTemplate: TemplateSummary; documentType: "protocol" | "invitation" };

export function SessionDesignView({ sessionTemplate, documentType }: Props) {
  const t = useTranslations("templates.studio");
  const tStudio = useTranslations("documentStudio");
  const toast = useToast();
  const [design, setDesign] = useState<SessionDesign | null | undefined>(undefined);
  const [pages, setPages] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    studioApi
      .sessionDesigns(sessionTemplate.id)
      .then((rows) => {
        if (!cancelled) setDesign((rows ?? []).find((item) => item.document_type === documentType) ?? null);
      })
      .catch((reason) => {
        if (!cancelled) {
          setDesign(null);
          setError(apiErrorMessage(reason, t("design.loadFailed")));
        }
      });
    return () => {
      cancelled = true;
    };
    // t ist während der Lebensdauer unveränderlich
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionTemplate.id, documentType]);

  // Vorschau der geltenden (geteilten) Gestaltung mit den Traktanden dieser Vorlage
  useEffect(() => {
    if (!design || design.owned) return;
    const controller = new AbortController();
    previewDocument({ document_type: documentType, template_id: design.template_id, protocol_template_id: sessionTemplate.id, data_mode: "data" }, 4, controller.signal)
      .then((result) => setPages(result.pages))
      .catch((reason) => {
        if (!controller.signal.aborted) setError(apiErrorMessage(reason, tStudio("preview.failed")));
      });
    return () => controller.abort();
    // tStudio ist während der Lebensdauer unveränderlich
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [design, documentType, sessionTemplate.id]);

  async function customize() {
    setBusy(true);
    try {
      const created = await studioApi.customizeSessionDesign(sessionTemplate.id, documentType, t("design.copyName", { name: sessionTemplate.name, type: tStudio(`docType.${documentType}`) }));
      setDesign({ document_type: documentType, template_id: created.id, template_name: created.name, template_origin: created.origin, template_system_key: created.system_key, source: "protocol_template", owned: true });
      toast(t("design.customized"), "success");
    } catch (reason) {
      toast(apiErrorMessage(reason, t("design.customizeFailed")), "error");
    } finally {
      setBusy(false);
    }
  }

  if (design === undefined) return <p className="muted">{tStudio("common.loading")}</p>;
  if (design?.owned) {
    return (
      <div className="session-design-designer">
        <TemplateDesigner key={design.template_id} templateId={design.template_id} sessionTemplateId={sessionTemplate.id} />
      </div>
    );
  }
  return (
    <div className="grid">
      {error ? <StatusBanner tone="error" message={error} /> : null}
      <div className="session-design-intro">
        <div>
          <h2 className="studio-section-title">{t(`design.title.${documentType}`)}</h2>
          <p className="muted">{design ? t("design.sharedInfo", { name: templateDisplayName(tStudio, { name: design.template_name, origin: design.template_origin, system_key: design.template_system_key }) }) : t("design.noneInfo")}</p>
        </div>
        <button type="button" className="button-primary" disabled={busy} onClick={() => void customize()}>
          {t("design.customize")}
        </button>
      </div>
      <div className="studio-preview-pages session-design-pages">
        {pages.map((page, index) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img key={index} className="studio-preview-page" src={page} alt={tStudio("preview.pageAlt", { page: index + 1 })} />
        ))}
      </div>
    </div>
  );
}
