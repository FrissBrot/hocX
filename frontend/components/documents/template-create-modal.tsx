"use client";

// Neue Vorlage: Name, Dokumenttyp und Ausgangspunkt. Für Dokumenttypen mit Designs (Alpin,
// Kreide …, backend/app/documents/examples.py) zuerst die Design-Galerie: ein Design legt
// Titelseite, Seitenvorlagen und ein eigenes Brand-Profil an, dessen Grundstil allen Elementen
// die Darstellung vorgibt. Ohne Design: leer oder Kopie einer bestehenden Vorlage.

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { templateDisplayName } from "@/components/documents/studio-labels";
import { Modal } from "@/components/ui/modal";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { useToast } from "@/contexts/toast-context";
import { apiErrorMessage, DesignExample, DocumentTemplateDetail, DocumentTemplateInfo, DocumentTypeInfo, studioApi } from "@/lib/documents/api";
import { Select } from "@/components/ui/select";

type Props = {
  open: boolean;
  onClose: () => void;
  types: DocumentTypeInfo[];
  templates: DocumentTemplateInfo[];
  /** Designs legen ein Brand-Profil an: nur mit Brand-Recht anbieten */
  canUseDesigns?: boolean;
  onCreated: (template: DocumentTemplateDetail) => void;
};

export function TemplateCreateModal({ open, onClose, types, templates, canUseDesigns = false, onCreated }: Props) {
  const t = useTranslations("documentStudio");
  const toast = useToast();
  const [name, setName] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const [documentType, setDocumentType] = useState(types[0]?.key ?? "protocol");
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [designs, setDesigns] = useState<DesignExample[]>([]);
  const [design, setDesign] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const sources = useMemo(() => templates.filter((item) => item.document_type === documentType && item.status === "active"), [templates, documentType]);
  const typeDesigns = useMemo(() => designs.filter((item) => item.document_type === documentType), [designs, documentType]);

  useEffect(() => {
    if (!canUseDesigns) return;
    studioApi
      .listExamples()
      .then((loaded) => setDesigns(loaded ?? []))
      // Ohne Designs bleibt der Dialog wie bisher (leer oder Kopie)
      .catch(() => setDesigns([]));
  }, [canUseDesigns]);

  function chooseDesign(key: string | null) {
    setDesign(key);
    if (key) setSourceId(null);
    // Vorschlag für den Namen, solange noch nichts Eigenes eingegeben ist
    if (!nameTouched) setName(key ? t(`examples.items.${key}.name`) : "");
  }

  async function create() {
    setBusy(true);
    try {
      const created = design
        ? await studioApi.importExample(design, name.trim())
        : await studioApi.createTemplate({ name: name.trim(), document_type: documentType, from_template_id: sourceId });
      onCreated(created);
    } catch (error) {
      toast(apiErrorMessage(error, t("common.actionFailed")), "error");
      setBusy(false);
    }
  }

  return (
    <Modal className="studio-modal" size={typeDesigns.length > 0 ? "wide" : "default"} open={open} onClose={onClose} title={t("create.title")} description={t("create.description")}>
      <div className="grid">
        <label className="field-stack">
          <span className="field-label">{t("create.documentType")}</span>
          <Select
            value={documentType}
            onChange={(event) => {
              setDocumentType(event.target.value);
              setSourceId(null);
              chooseDesign(null);
            }}
          >
            {types.map((type) => (
              <option key={type.key} value={type.key}>
                {t(`docType.${type.key}`)}
              </option>
            ))}
          </Select>
          <span className="field-help">{t(`docTypeHelp.${documentType}`)}</span>
        </label>
        {typeDesigns.length > 0 && (
          <div className="field-stack">
            <span className="field-label">{t("create.design")}</span>
            <div className="studio-variant-list studio-design-list" role="radiogroup" aria-label={t("create.design")}>
              <button type="button" role="radio" aria-checked={design === null} className={design === null ? "studio-variant studio-variant-active" : "studio-variant"} onClick={() => chooseDesign(null)}>
                <span className="studio-variant-name">{t("create.noDesign")}</span>
                <span className="field-help">{t("create.noDesignHelp")}</span>
              </button>
              {typeDesigns.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  role="radio"
                  aria-checked={design === item.key}
                  className={design === item.key ? "studio-variant studio-variant-active" : "studio-variant"}
                  onClick={() => chooseDesign(item.key)}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img className="studio-variant-thumb" src={studioApi.exampleThumbnailUrl(item.key)} alt="" loading="lazy" />
                  <span className="studio-variant-name">{t(`examples.items.${item.key}.name`)}</span>
                  <span className="field-help">{t(`examples.items.${item.key}.description`)}</span>
                </button>
              ))}
            </div>
            <span className="field-help">{t("create.designHelp")}</span>
          </div>
        )}
        <label className="field-stack">
          <span className="field-label">{t("library.name")}</span>
          <input
            value={name}
            maxLength={design ? 120 : 160}
            onChange={(event) => {
              setName(event.target.value);
              setNameTouched(true);
            }}
            autoFocus
          />
        </label>
        {!design && (
          <div className="field-stack">
            <span className="field-label">{t("create.startFrom")}</span>
            <SearchableSelect
              options={sources}
              getId={(item) => item.id}
              getLabel={(item) => `${templateDisplayName(t, item)} · ${t(`origin.${item.origin}`)}`}
              value={sourceId}
              onChange={(item) => setSourceId(item ? item.id : null)}
              nullLabel={t("create.blank")}
            />
            <span className="field-help">{t("create.startFromHelp")}</span>
          </div>
        )}
      </div>
      <div className="modal-actions">
        <button type="button" className="button-ghost" onClick={onClose}>
          {t("common.cancel")}
        </button>
        <button type="button" className="button-primary" disabled={!name.trim() || busy} onClick={() => void create()}>
          {t("create.submit")}
        </button>
      </div>
    </Modal>
  );
}
