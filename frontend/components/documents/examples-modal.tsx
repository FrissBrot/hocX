"use client";

// Gestaltungsbeispiele: fertig gestaltete Vorlagen samt eigenem CD. «Hinzufügen» legt im Verein
// eine Vorlage und ein damit verknüpftes Brand-Profil an (backend/app/documents/examples.py);
// im Designer lässt sich die Vorlage danach auf das eigene CD umstellen.

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { useToast } from "@/contexts/toast-context";
import { apiErrorMessage, DesignExample, DocumentTemplateDetail, studioApi } from "@/lib/documents/api";

type Props = {
  onClose: () => void;
  onImported: (template: DocumentTemplateDetail) => void;
};

export function ExamplesModal({ onClose, onImported }: Props) {
  const t = useTranslations("documentStudio");
  const toast = useToast();
  const [examples, setExamples] = useState<DesignExample[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    studioApi
      .listExamples()
      .then((loaded) => setExamples(loaded ?? []))
      .catch((reason) => setError(apiErrorMessage(reason, t("examples.loadFailed"))));
    // t ist während der Lebensdauer der Komponente unveränderlich
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function add(example: DesignExample) {
    setBusy(example.key);
    try {
      const template = await studioApi.importExample(example.key, t(`examples.items.${example.key}.name`));
      toast(t("examples.imported"), "success");
      onImported(template);
    } catch (reason) {
      toast(apiErrorMessage(reason, t("common.actionFailed")), "error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Modal className="studio-modal" size="wide" open onClose={onClose} title={t("examples.title")} description={t("examples.description")}>
      {error && <StatusBanner tone="error" message={error} />}
      {examples === null && !error && <p className="muted">{t("common.loading")}</p>}
      <div className="studio-gallery">
        {(examples ?? []).map((example) => (
          <article key={example.key} className="studio-card">
            <div className="studio-card-preview">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={studioApi.exampleThumbnailUrl(example.key)} alt="" loading="lazy" />
            </div>
            <div className="studio-card-body">
              <h3 className="studio-card-title">{t(`examples.items.${example.key}.name`)}</h3>
              <p className="studio-card-description">{t(`examples.items.${example.key}.description`)}</p>
              <button type="button" className="button-secondary" disabled={busy !== null} onClick={() => void add(example)}>
                {busy === example.key ? t("examples.adding") : t("examples.add")}
              </button>
            </div>
          </article>
        ))}
      </div>
    </Modal>
  );
}
