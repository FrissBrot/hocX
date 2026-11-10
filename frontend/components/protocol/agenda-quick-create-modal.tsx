"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { RichTextEditor } from "@/components/ui/rich-text-editor";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { ProtocolAgendaItem } from "@/types/api";

const NO_SECTION = "__none__";

/** Anliegen direkt im Protokoll erfassen (Mini-Menü des Editors): sofort an dieses Protokoll
 *  gebunden, standardmässig unter dem gerade gewählten Traktandum. */
export function AgendaQuickCreateModal({
  protocolId,
  sections,
  defaultSectionId,
  onClose,
  onCreated,
}: {
  protocolId: string;
  sections: { id: string; name: string }[];
  defaultSectionId: string | null;
  onClose: () => void;
  onCreated: (item: ProtocolAgendaItem) => void;
}) {
  const t = useTranslations("agenda");
  const showToast = useToast();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [sectionId, setSectionId] = useState<string>(
    defaultSectionId && sections.some((section) => section.id === defaultSectionId) ? defaultSectionId : NO_SECTION
  );
  const [saving, setSaving] = useState(false);
  const options = [...sections, { id: NO_SECTION, name: t("editor.sectionNone") }];

  async function create() {
    if (!title.trim()) return;
    setSaving(true);
    try {
      const created = await browserApiFetch<ProtocolAgendaItem>(`/api/protocols/${protocolId}/agenda-items`, {
        method: "POST",
        body: JSON.stringify({ title: title.trim(), body, protocol_element_id: sectionId === NO_SECTION ? null : sectionId }),
      });
      showToast(t("created"), "success");
      onCreated(created);
      onClose();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("errorSave"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open title={t("editor.quickCreateTitle")} description={t("editor.quickCreateDescription")} onClose={onClose}>
      <ModalSaveForm
        className="grid agenda-item-form"
        onSubmit={(event) => {
          event.preventDefault();
          return create();
        }}
      >
        <label className="field-stack">
          <span className="field-label">{t("fieldTitle")}</span>
          <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder={t("titlePlaceholder")} maxLength={500} autoFocus required />
        </label>
        <div className="field-stack">
          <span className="field-label">{t("fieldBody")}</span>
          <RichTextEditor value={body} onChange={setBody} placeholder={t("bodyPlaceholder")} />
        </div>
        <div className="field-stack">
          <span className="field-label">{t("editor.sectionLabel")}</span>
          <SearchableSelect
            options={options}
            getId={(option) => option.id}
            getLabel={(option) => option.name}
            value={sectionId}
            onChange={(option) => setSectionId(option?.id ?? NO_SECTION)}
          />
        </div>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>
            {t("cancel")}
          </button>
          <button data-modal-save type="submit" className="button-primary" disabled={saving || !title.trim()}>
            {saving ? t("creatingEllipsis") : t("createButton")}
          </button>
        </div>
      </ModalSaveForm>
    </Modal>
  );
}
