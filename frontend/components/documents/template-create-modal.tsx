"use client";

// Neue Vorlage (Gestaltung auf Abruf): Dokumenttyp wählen, dann womit man startet - ein Design
// bzw. eine Vorlage aus dem Katalog (Vorschau mit dem eigenen Erscheinungsbild), eine Kopie
// einer eigenen Vorlage oder leer. Übernommen wird nur genau diese eine Vorlage; sie nutzt das
// gewählte Erscheinungsbild, es entsteht kein neues Brand-Profil.

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { adoptCatalogItem, CatalogItem, typesByCategory } from "@/components/documents/catalog";
import { templateDisplayName } from "@/components/documents/studio-labels";
import { Modal } from "@/components/ui/modal";
import { Select } from "@/components/ui/select";
import { useToast } from "@/contexts/toast-context";
import { apiErrorMessage, Brand, DocumentTemplateDetail, DocumentTemplateInfo, DocumentTypeInfo, studioApi } from "@/lib/documents/api";

type Start = "catalog" | "copy" | "blank";
// Auswahlwert «Erscheinungsbild des Designs (neu)»: das CD des Designs wird mitgenommen
const DESIGN_BRAND = "design";

type Props = {
  open: boolean;
  onClose: () => void;
  types: DocumentTypeInfo[];
  categories: string[];
  // Eigene Vorlagen (Ausgangspunkt «Kopie»)
  templates: DocumentTemplateInfo[];
  catalog: CatalogItem[];
  brands: Brand[];
  // Darf Erscheinungsbilder anlegen (Voraussetzung, um das CD eines Designs mitzunehmen)
  canBrand: boolean;
  initialType?: string | null;
  onCreated: (template: DocumentTemplateDetail) => void;
};

export function TemplateCreateModal({ open, onClose, types, categories, templates, catalog, brands, canBrand, initialType, onCreated }: Props) {
  const t = useTranslations("documentStudio");
  const toast = useToast();
  const activeBrands = useMemo(() => brands.filter((brand) => !brand.archived), [brands]);
  const defaultBrand = activeBrands.find((brand) => brand.is_default) ?? activeBrands[0] ?? null;
  const [documentType, setDocumentType] = useState(initialType ?? types[0]?.key ?? "protocol");
  const typeCatalog = useMemo(() => catalog.filter((item) => item.documentType === documentType), [catalog, documentType]);
  const typeCopies = useMemo(() => templates.filter((item) => item.document_type === documentType && item.status === "active"), [templates, documentType]);
  // Ohne eigene Wahl gelten Voreinstellungen aus den geladenen Daten: der Katalog kann nach dem
  // Öffnen des Dialogs eintreffen (null = noch nichts gewählt bzw. eingegeben)
  const [chosenStart, setStart] = useState<Start | null>(null);
  const [chosenKey, setCatalogKey] = useState<string | null>(null);
  const [copyId, setCopyId] = useState<string | null>(null);
  const [chosenName, setName] = useState<string | null>(null);
  const [nameTouched, setNameTouched] = useState(false);
  const start: Start = chosenStart ?? (typeCatalog.length > 0 ? "catalog" : "blank");
  const catalogKey = chosenKey ?? typeCatalog[0]?.key ?? null;
  const [chosenBrand, setBrandId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const chosen = typeCatalog.find((item) => item.key === catalogKey) ?? null;
  // Ein Design bringt standardmässig sein eigenes CD mit; sonst gilt das Standard-Erscheinungsbild
  const designBrandAvailable = canBrand && start === "catalog" && chosen?.kind === "design";
  const fallbackBrand = designBrandAvailable ? DESIGN_BRAND : defaultBrand?.id ?? null;
  const brandId = chosenBrand && (chosenBrand !== DESIGN_BRAND || designBrandAvailable) ? chosenBrand : fallbackBrand;
  const withDesignBrand = designBrandAvailable && brandId === DESIGN_BRAND;
  const copySource = typeCopies.find((item) => item.id === copyId) ?? null;
  const name = chosenName ?? (start === "catalog" && chosen ? chosen.name : t(`docType.${documentType}`));

  function suggest(value: string) {
    if (!nameTouched) setName(value);
  }

  function chooseType(key: string) {
    setDocumentType(key);
    setStart(null);
    setCatalogKey(null);
    setCopyId(null);
    if (!nameTouched) setName(null);
  }

  function chooseStart(value: Start) {
    setStart(value);
    if (value === "copy" && typeCopies[0]) {
      setCopyId(copyId ?? typeCopies[0].id);
      suggest(t("library.copyName", { name: templateDisplayName(t, copySource ?? typeCopies[0]) }));
    } else if (!nameTouched) setName(null);
  }

  const ready = !!name.trim() && !busy && (start === "blank" || (start === "catalog" && !!chosen) || (start === "copy" && !!copySource));
  const footnote =
    start === "catalog" && chosen ? t("create.footCatalog", { name: chosen.name }) : start === "copy" ? t("create.footCopy") : t("create.footBlank");

  async function create() {
    setBusy(true);
    try {
      let created: DocumentTemplateDetail;
      if (start === "catalog" && chosen) created = await adoptCatalogItem(chosen, name.trim(), withDesignBrand);
      else created = await studioApi.createTemplate({ name: name.trim(), document_type: documentType, from_template_id: start === "copy" ? copySource?.id ?? null : null });
      // Ohne Auswahl folgt die Vorlage dem Standard-Erscheinungsbild des Vereins
      if (!withDesignBrand && brandId && defaultBrand && brandId !== defaultBrand.id) await studioApi.updateTemplate(created.id, { brand_id: brandId });
      onCreated(created);
    } catch (error) {
      toast(apiErrorMessage(error, t("common.actionFailed")), "error");
      setBusy(false);
    }
  }

  return (
    <Modal
      className="studio-modal studio-catalog-modal"
      size="wide"
      open={open}
      onClose={onClose}
      title={t("create.title")}
      description={t("create.description")}
      footer={
        <>
          <span className="field-help">{footnote}</span>
          <div className="modal-footer-actions">
            <button type="button" className="button-ghost" onClick={onClose}>
              {t("common.cancel")}
            </button>
            <button type="button" className="button-primary" disabled={!ready} onClick={() => void create()}>
              {t("create.submit")}
            </button>
          </div>
        </>
      }
    >
      <div className="studio-catalog">
        <nav className="studio-catalog-types" aria-label={t("create.documentType")}>
          {typesByCategory(types, categories).map((group) => (
            <div key={group.category} className="studio-catalog-type-group">
              <span className="studio-catalog-type-head">{t(`category.${group.category}`)}</span>
              {group.types.map((type) => (
                <button
                  key={type.key}
                  type="button"
                  aria-current={documentType === type.key ? "true" : undefined}
                  className={documentType === type.key ? "studio-catalog-type studio-catalog-type-active" : "studio-catalog-type"}
                  onClick={() => chooseType(type.key)}
                >
                  <span>{t(`docType.${type.key}`)}</span>
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div className="studio-catalog-main">
          <p className="muted">{t(`docTypeHelp.${documentType}`)}</p>
          <div className="studio-start-list" role="radiogroup" aria-label={t("create.startFrom")}>
            {(["catalog", "copy", "blank"] as const).map((value) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={start === value}
                disabled={(value === "catalog" && typeCatalog.length === 0) || (value === "copy" && typeCopies.length === 0)}
                className={start === value ? "studio-start studio-start-active" : "studio-start"}
                onClick={() => chooseStart(value)}
              >
                <span className="studio-start-name">{t(`create.start.${value}`)}</span>
                <span className="field-help">
                  {value === "catalog"
                    ? t("create.startCatalogHelp", { count: typeCatalog.length })
                    : value === "copy"
                      ? t("create.startCopyHelp", { count: typeCopies.length })
                      : t("create.startBlankHelp")}
                </span>
              </button>
            ))}
          </div>

          {start === "catalog" && (
            <div className="studio-variant-list studio-design-list" role="radiogroup" aria-label={t("create.design")}>
              {typeCatalog.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  role="radio"
                  aria-checked={catalogKey === item.key}
                  className={catalogKey === item.key ? "studio-variant studio-variant-active" : "studio-variant"}
                  onClick={() => {
                    setCatalogKey(item.key);
                    suggest(item.name);
                  }}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img className="studio-variant-thumb" src={item.thumbnail} alt="" loading="lazy" />
                  <span className="studio-variant-name">{item.name}</span>
                  <span className="field-help">{item.description}</span>
                </button>
              ))}
            </div>
          )}
          {start === "copy" && (
            <div className="studio-copy-list" role="radiogroup" aria-label={t("create.start.copy")}>
              {typeCopies.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  role="radio"
                  aria-checked={copyId === item.id}
                  className={copyId === item.id ? "studio-copy studio-copy-active" : "studio-copy"}
                  onClick={() => {
                    setCopyId(item.id);
                    suggest(t("library.copyName", { name: templateDisplayName(t, item) }));
                  }}
                >
                  <span className="studio-copy-name">{templateDisplayName(t, item)}</span>
                </button>
              ))}
            </div>
          )}

          <div className="studio-create-fields">
            <label className="field-stack">
              <span className="field-label">{t("library.name")}</span>
              <input
                value={name}
                maxLength={start === "catalog" ? 120 : 160}
                onChange={(event) => {
                  setName(event.target.value);
                  setNameTouched(true);
                }}
              />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("create.brand")}</span>
              <Select value={brandId ?? ""} onChange={(event) => setBrandId(event.target.value || null)}>
                {designBrandAvailable ? <option value={DESIGN_BRAND}>{t("create.brandDesign")}</option> : null}
                {activeBrands.map((brand) => (
                  <option key={brand.id} value={brand.id}>
                    {brand.is_default ? t("create.brandDefault", { name: brand.name }) : brand.name}
                  </option>
                ))}
              </Select>
            </label>
            <span className="field-help studio-create-fields-help">{t(withDesignBrand ? "create.brandDesignHelp" : "create.brandHelp")}</span>
          </div>
        </div>
      </div>
    </Modal>
  );
}
