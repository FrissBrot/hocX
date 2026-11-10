"use client";

// Katalog (Gestaltung auf Abruf): alle mitgelieferten Designs und Vorlagen nach Dokumenttyp.
// Designs zeigen ihr eigenes CD und bringen es beim «Hinzufügen» als verknüpftes Erscheinungsbild
// mit (sofern man Erscheinungsbilder verwalten darf), Systemvorlagen erscheinen mit dem des
// Vereins. Was niemand übernimmt, bleibt im Katalog und taucht im Verein nicht auf.

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { adoptCatalogItem, CatalogItem, typesByCategory } from "@/components/documents/catalog";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { useToast } from "@/contexts/toast-context";
import { apiErrorMessage, DocumentTypeInfo, previewDocument } from "@/lib/documents/api";

type Props = {
  open: boolean;
  onClose: () => void;
  items: CatalogItem[];
  types: DocumentTypeInfo[];
  categories: string[];
  initialType?: string | null;
  canAdopt: boolean;
  // Darf Erscheinungsbilder anlegen: ein Design bringt dann sein CD mit
  canBrand: boolean;
  onAdopted: () => void;
};

export function CatalogModal({ open, onClose, items, types, categories, initialType, canAdopt, canBrand, onAdopted }: Props) {
  const t = useTranslations("documentStudio");
  const toast = useToast();
  const withItems = useMemo(() => types.filter((type) => items.some((item) => item.documentType === type.key)), [types, items]);
  const [documentType, setDocumentType] = useState(() => (initialType && withItems.some((type) => type.key === initialType) ? initialType : withItems[0]?.key ?? "protocol"));
  const [busy, setBusy] = useState<string | null>(null);
  const [preview, setPreview] = useState<CatalogItem | null>(null);
  const visible = items.filter((item) => item.documentType === documentType);

  async function adopt(item: CatalogItem) {
    setBusy(item.key);
    try {
      const withBrand = canBrand && item.kind === "design";
      await adoptCatalogItem(item, item.name, withBrand);
      toast(t(withBrand ? "catalog.adoptedWithBrand" : "catalog.adopted", { name: item.name }), "success");
      onAdopted();
    } catch (reason) {
      toast(apiErrorMessage(reason, t("common.actionFailed")), "error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Modal className="studio-modal studio-catalog-modal" size="wide" open={open} onClose={onClose} title={t("catalog.title")} description={t("catalog.description")}>
      <div className="studio-catalog">
        <nav className="studio-catalog-types" aria-label={t("create.documentType")}>
          {typesByCategory(withItems, categories).map((group) => (
            <div key={group.category} className="studio-catalog-type-group">
              <span className="studio-catalog-type-head">{t(`category.${group.category}`)}</span>
              {group.types.map((type) => (
                <button
                  key={type.key}
                  type="button"
                  aria-current={documentType === type.key ? "true" : undefined}
                  className={documentType === type.key ? "studio-catalog-type studio-catalog-type-active" : "studio-catalog-type"}
                  onClick={() => setDocumentType(type.key)}
                >
                  <span>{t(`docType.${type.key}`)}</span>
                  <span className="studio-catalog-type-count">{items.filter((item) => item.documentType === type.key).length}</span>
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div className="studio-catalog-main">
          {preview ? (
            <CatalogPreview item={preview} onBack={() => setPreview(null)} />
          ) : (
            <>
              <div className="studio-catalog-heading">
                <h3 className="studio-section-title">{t(`docType.${documentType}`)}</h3>
                <span className="field-help">{t(`docTypeHelp.${documentType}`)}</span>
              </div>
              <div className="studio-catalog-grid">
                {visible.map((item) => (
                  <article key={item.key} className="studio-catalog-card">
                    <div className="studio-catalog-thumb">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={item.thumbnail} alt="" loading="lazy" />
                    </div>
                    <div className="studio-catalog-body">
                      <h4 className="studio-card-title">{item.name}</h4>
                      <p className="studio-card-description">{item.description}</p>
                      <div className="studio-catalog-actions">
                        {item.template ? (
                          <button type="button" className="button-secondary" onClick={() => setPreview(item)}>
                            {t("library.preview")}
                          </button>
                        ) : null}
                        {canAdopt ? (
                          <button
                            type="button"
                            className={item.adopted ? "button-secondary" : "button-primary"}
                            disabled={busy !== null}
                            aria-label={t("catalog.addNamed", { name: item.name })}
                            onClick={() => void adopt(item)}
                          >
                            {item.adopted ? t("catalog.addAgain") : t("catalog.add")}
                          </button>
                        ) : null}
                      </div>
                      {item.adopted ? <span className="studio-catalog-adopted">{t("catalog.alreadyAdopted")}</span> : null}
                    </div>
                  </article>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </Modal>
  );
}

// Vorschau einer Katalog-Vorlage im Katalog selbst (kein zweites Modal): mit Beispielinhalten
// und dem Erscheinungsbild des Vereins.
function CatalogPreview({ item, onBack }: { item: CatalogItem; onBack: () => void }) {
  const t = useTranslations("documentStudio");
  const [pages, setPages] = useState<string[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!item.template) return;
    const controller = new AbortController();
    previewDocument({ document_type: item.documentType, template_id: item.template.id, data_mode: "sample" }, 4, controller.signal)
      .then((result) => setPages(result.pages))
      .catch((reason) => {
        if (!controller.signal.aborted) setError(apiErrorMessage(reason, t("preview.failed")));
      });
    return () => controller.abort();
    // t ist während der Lebensdauer der Komponente unveränderlich
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item]);

  return (
    <div className="studio-catalog-preview">
      <div className="studio-catalog-heading">
        <button type="button" className="button-ghost" onClick={onBack}>
          {t("catalog.back")}
        </button>
        <h3 className="studio-section-title">{item.name}</h3>
      </div>
      <p className="field-help">{t("preview.sampleHint")}</p>
      {error && <StatusBanner tone="error" message={error} />}
      {!pages && !error && <p className="muted">{t("preview.loading")}</p>}
      <div className="studio-preview-pages">
        {(pages ?? []).map((page, index) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img key={index} className="studio-preview-page" src={page} alt={t("preview.pageAlt", { page: index + 1 })} />
        ))}
      </div>
    </div>
  );
}
