"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { LazyRichTextEditor } from "@/components/ui/rich-text-editor-lazy";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { ProtocolAgendaItem } from "@/types/api";

const NO_SECTION = "__none__";

/** Anliegen direkt im Protokoll erfassen (Schublade «Anliegen» des Editors): sofort an dieses
 *  Protokoll gebunden, standardmässig unter dem gerade aktiven Traktandum. Danach bleibt die
 *  Schublade offen für das nächste Anliegen. */
export function AgendaQuickCreateForm({
  protocolId,
  sections,
  defaultSectionId,
  onCreated,
}: {
  protocolId: string;
  sections: { id: string; name: string }[];
  defaultSectionId: string | null;
  onCreated: (item: ProtocolAgendaItem) => void;
}) {
  const t = useTranslations("agenda");
  const showToast = useToast();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  // null = automatisch der aktive Punkt; sonst die Wahl im Feld
  const [chosenSectionId, setChosenSectionId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [bodyKey, setBodyKey] = useState(0);
  const autoSectionId = defaultSectionId && sections.some((section) => section.id === defaultSectionId) ? defaultSectionId : NO_SECTION;
  const sectionId = chosenSectionId ?? autoSectionId;
  const options = [...sections, { id: NO_SECTION, name: t("editor.sectionNone") }];

  async function create() {
    if (!title.trim() || saving) return;
    setSaving(true);
    try {
      const created = await browserApiFetch<ProtocolAgendaItem>(`/api/protocols/${protocolId}/agenda-items`, {
        method: "POST",
        body: JSON.stringify({ title: title.trim(), body, protocol_element_id: sectionId === NO_SECTION ? null : sectionId }),
      });
      showToast(t("created"), "success");
      onCreated(created);
      setTitle("");
      setBody("");
      setBodyKey((key) => key + 1);
      setChosenSectionId(null);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("errorSave"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      className="grid agenda-item-form"
      onSubmit={(event) => {
        event.preventDefault();
        void create();
      }}
    >
      <p className="muted protocol-drawer-note">{t("editor.quickCreateDescription")}</p>
      <div className="field-stack">
        <span className="field-label">{t("editor.sectionLabel")}</span>
        <SearchableSelect
          options={options}
          getId={(option) => option.id}
          getLabel={(option) => option.name}
          value={sectionId}
          onChange={(option) => setChosenSectionId(option?.id ?? NO_SECTION)}
        />
      </div>
      <label className="field-stack">
        <span className="field-label">{t("fieldTitle")}</span>
        <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder={t("titlePlaceholder")} maxLength={500} required data-drawer-autofocus />
      </label>
      <div className="field-stack">
        <span className="field-label">{t("fieldBody")}</span>
        <LazyRichTextEditor key={bodyKey} value={body} onChange={setBody} placeholder={t("bodyPlaceholder")} />
      </div>
      <button type="submit" className="button-primary" disabled={saving || !title.trim()}>
        {saving ? t("creatingEllipsis") : t("createButton")}
      </button>
    </form>
  );
}
