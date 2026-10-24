"use client";

// Vorschau einer Vorlage aus der Bibliothek: gerendert von Typst mit Beispielinhalten.

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { templateDescription, templateDisplayName } from "@/components/documents/studio-labels";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { apiErrorMessage, DocumentTemplateInfo, previewDocument } from "@/lib/documents/api";

export function TemplatePreviewModal({ template, onClose }: { template: DocumentTemplateInfo; onClose: () => void }) {
  const t = useTranslations("documentStudio");
  const [pages, setPages] = useState<string[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    const revision = template.draft_revision && template.editable ? template.draft_revision : template.published_revision;
    previewDocument({ document_type: template.document_type, template_id: template.id, revision_id: template.editable ? revision?.id ?? null : null, data_mode: "sample" }, 6, controller.signal)
      .then((result) => setPages(result.pages))
      .catch((reason) => {
        if (!controller.signal.aborted) setError(apiErrorMessage(reason, t("preview.failed")));
      });
    return () => controller.abort();
    // t/toast sind während der Lebensdauer der Komponente unveränderlich
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [template]);

  return (
    <Modal className="studio-modal" open onClose={onClose} title={templateDisplayName(t, template)} description={templateDescription(t, template) || undefined} size="wide">
      <p className="field-help">{t("preview.sampleHint")}</p>
      {error && <StatusBanner tone="error" message={error} />}
      {!pages && !error && <p className="muted">{t("preview.loading")}</p>}
      <div className="studio-preview-pages">
        {(pages ?? []).map((page, index) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img key={index} className="studio-preview-page" src={page} alt={t("preview.pageAlt", { page: index + 1 })} />
        ))}
      </div>
    </Modal>
  );
}
