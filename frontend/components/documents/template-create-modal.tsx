"use client";

// Neue Vorlage: Name, Dokumenttyp und Ausgangspunkt (leer oder Kopie einer bestehenden
// Vorlage, z. B. einer Systemvorlage).

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { templateDisplayName } from "@/components/documents/studio-labels";
import { Modal } from "@/components/ui/modal";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { useToast } from "@/contexts/toast-context";
import { apiErrorMessage, DocumentTemplateDetail, DocumentTemplateInfo, DocumentTypeInfo, studioApi } from "@/lib/documents/api";

type Props = {
  open: boolean;
  onClose: () => void;
  types: DocumentTypeInfo[];
  templates: DocumentTemplateInfo[];
  onCreated: (template: DocumentTemplateDetail) => void;
};

export function TemplateCreateModal({ open, onClose, types, templates, onCreated }: Props) {
  const t = useTranslations("documentStudio");
  const toast = useToast();
  const [name, setName] = useState("");
  const [documentType, setDocumentType] = useState(types[0]?.key ?? "protocol");
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const sources = useMemo(() => templates.filter((item) => item.document_type === documentType && item.status === "active"), [templates, documentType]);

  async function create() {
    setBusy(true);
    try {
      const created = await studioApi.createTemplate({ name: name.trim(), document_type: documentType, from_template_id: sourceId });
      onCreated(created);
    } catch (error) {
      toast(apiErrorMessage(error, t("common.actionFailed")), "error");
      setBusy(false);
    }
  }

  return (
    <Modal className="studio-modal" open={open} onClose={onClose} title={t("create.title")} description={t("create.description")}>
      <div className="grid">
        <label className="field-stack">
          <span className="field-label">{t("library.name")}</span>
          <input value={name} maxLength={160} onChange={(event) => setName(event.target.value)} autoFocus />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("create.documentType")}</span>
          <select
            value={documentType}
            onChange={(event) => {
              setDocumentType(event.target.value);
              setSourceId(null);
            }}
          >
            {types.map((type) => (
              <option key={type.key} value={type.key}>
                {t(`docType.${type.key}`)}
              </option>
            ))}
          </select>
          <span className="field-help">{t(`docTypeHelp.${documentType}`)}</span>
        </label>
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
