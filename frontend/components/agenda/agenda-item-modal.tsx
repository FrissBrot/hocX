"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { AgendaScheduleField } from "@/components/agenda/agenda-schedule-field";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { RichTextEditor } from "@/components/ui/rich-text-editor";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { StatusBanner } from "@/components/ui/status-banner";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate } from "@/lib/utils/format";
import { AgendaItem, AgendaSchedule, AgendaTemplateOption } from "@/types/api";

const NO_POINT = "__none__";

type Props = {
  /** Ohne `item`: neues Anliegen erfassen. */
  item?: AgendaItem | null;
  templates: AgendaTemplateOption[];
  /** Zuletzt im Popup gewählte Vorlage (wird beim Erfassen vorgewählt und danach gespeichert). */
  preferredTemplateId?: string | null;
  canEdit: boolean;
  onClose: () => void;
  onSaved: (item: AgendaItem) => void;
  onTemplateRemembered?: (templateId: string) => void;
};

export function AgendaItemModal({ item, templates, preferredTemplateId, canEdit, onClose, onSaved, onTemplateRemembered }: Props) {
  const t = useTranslations("agenda");
  const showToast = useToast();
  const isCreate = !item;
  const initialTemplateId =
    item?.template_id ?? (templates.some((template) => template.id === preferredTemplateId) ? preferredTemplateId! : templates[0]?.id ?? null);
  const [title, setTitle] = useState(item?.title ?? "");
  const [body, setBody] = useState(item?.body ?? "");
  const [templateId, setTemplateId] = useState<string | null>(initialTemplateId);
  const [pointId, setPointId] = useState<string>(item ? item.template_element_id ?? NO_POINT : "");
  const [schedule, setSchedule] = useState<AgendaSchedule>(
    item?.schedule_kind === "month" ? { kind: "month", month: item.scheduled_month ?? null } : { kind: "next_meeting" }
  );
  const [saving, setSaving] = useState(false);

  const editable = canEdit && (item?.can_edit ?? true);
  // Gebundene Anliegen stehen schon in einem Protokoll: dort nur Titel/Text, sonst vertagen.
  const structureEditable = editable && !item?.is_bound;
  const template = templates.find((option) => option.id === templateId) ?? null;
  const pointOptions = useMemo(
    () => [...(template?.points ?? []), { id: NO_POINT, name: t("pointNone") }],
    [template, t]
  );
  const effectivePointId = pointId || (template?.points[0]?.id ?? NO_POINT);

  async function save() {
    if (!title.trim() || !templateId) return;
    setSaving(true);
    try {
      const point = effectivePointId === NO_POINT ? null : effectivePointId;
      let saved: AgendaItem;
      if (isCreate) {
        saved = await browserApiFetch<AgendaItem>("/api/agenda-items", {
          method: "POST",
          body: JSON.stringify({ template_id: templateId, template_element_id: point, title: title.trim(), body, schedule }),
        });
        void browserApiFetch("/api/agenda-items/template-preference", {
          method: "PUT",
          body: JSON.stringify({ template_id: templateId }),
        }).then(() => onTemplateRemembered?.(templateId)).catch(() => undefined);
        showToast(t("created"), "success");
      } else {
        const patch: Record<string, unknown> = { title: title.trim(), body };
        if (structureEditable) {
          if (templateId !== item.template_id) patch.template_id = templateId;
          if (point !== (item.template_element_id ?? null) || templateId !== item.template_id) patch.template_element_id = point;
          patch.schedule = schedule;
        }
        saved = await browserApiFetch<AgendaItem>(`/api/agenda-items/${item.id}`, { method: "PATCH", body: JSON.stringify(patch) });
        showToast(t("saved"), "success");
      }
      onSaved(saved);
      onClose();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("errorSave"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open
      size="wide"
      title={isCreate ? t("createTitle") : t("editTitle")}
      description={isCreate ? t("createDescription") : undefined}
      onClose={onClose}
    >
      <ModalSaveForm
        className="grid agenda-item-form"
        onSubmit={(event) => {
          event.preventDefault();
          return save();
        }}
      >
        {item && !item.can_edit && <StatusBanner tone="neutral" message={t("frozenHint")} />}
        {item && item.can_edit && item.is_bound && item.protocol && (
          <StatusBanner tone="neutral" message={t("boundHint", { number: item.protocol.protocol_number })} />
        )}
        <label className="field-stack">
          <span className="field-label">{t("fieldTitle")}</span>
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder={t("titlePlaceholder")}
            maxLength={500}
            autoFocus={isCreate}
            required
            disabled={!editable}
          />
        </label>
        {/* Plain div, kein <label>: der RichTextEditor hat Toolbar-Buttons vor dem Eingabefeld */}
        <div className="field-stack">
          <span className="field-label">{t("fieldBody")}</span>
          <RichTextEditor value={body} onChange={setBody} readOnly={!editable} placeholder={t("bodyPlaceholder")} />
        </div>
        {templates.length === 0 && isCreate ? (
          <StatusBanner tone="neutral" message={t("noTemplates")} />
        ) : (
          <div className="two-col">
            <div className="field-stack">
              <span className="field-label">{t("fieldTemplate")}</span>
              <SearchableSelect
                options={templates}
                getId={(option) => option.id}
                getLabel={(option) => option.name}
                value={templateId}
                placeholder={t("templatePlaceholder")}
                disabled={!structureEditable}
                onChange={(option) => {
                  setTemplateId(option?.id ?? null);
                  setPointId("");
                }}
              />
            </div>
            <div className="field-stack">
              <span className="field-label">{t("fieldPoint")}</span>
              <SearchableSelect
                options={pointOptions}
                getId={(option) => option.id}
                getLabel={(option) => option.name}
                value={effectivePointId}
                placeholder={t("pointPlaceholder")}
                disabled={!structureEditable || !template}
                onChange={(option) => setPointId(option?.id ?? NO_POINT)}
              />
            </div>
          </div>
        )}
        {structureEditable && <AgendaScheduleField value={schedule} onChange={setSchedule} />}
        {item && (
          <p className="field-help">
            {item.created_by_name
              ? t("createdBy", { name: item.created_by_name, date: formatDate(item.created_at) })
              : t("createdAt", { date: formatDate(item.created_at) })}
          </p>
        )}
        {editable && (
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={onClose}>
              {t("cancel")}
            </button>
            <button data-modal-save type="submit" className="button-primary" disabled={saving || !title.trim() || !templateId}>
              {saving
                ? isCreate ? t("creatingEllipsis") : t("savingEllipsis")
                : isCreate ? t("createButton") : t("saveButton")}
            </button>
          </div>
        )}
      </ModalSaveForm>
    </Modal>
  );
}

export function AgendaPostponeModal({
  item,
  onClose,
  onPostponed,
}: {
  item: { id: string; title: string };
  onClose: () => void;
  onPostponed: (item: AgendaItem) => void;
}) {
  const t = useTranslations("agenda");
  const showToast = useToast();
  const [schedule, setSchedule] = useState<AgendaSchedule>({ kind: "next_meeting" });
  const [saving, setSaving] = useState(false);

  async function postpone() {
    setSaving(true);
    try {
      const saved = await browserApiFetch<AgendaItem>(`/api/agenda-items/${item.id}/postpone`, {
        method: "POST",
        body: JSON.stringify({ schedule }),
      });
      showToast(t("postponed"), "success");
      onPostponed(saved);
      onClose();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("errorPostpone"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open title={t("postponeTitle")} description={t("postponeDescription", { title: item.title })} onClose={onClose}>
      <ModalSaveForm
        className="grid agenda-item-form"
        onSubmit={(event) => {
          event.preventDefault();
          return postpone();
        }}
      >
        <AgendaScheduleField value={schedule} onChange={setSchedule} />
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>
            {t("cancel")}
          </button>
          <button data-modal-save type="submit" className="button-primary" disabled={saving}>
            {t("postponeButton")}
          </button>
        </div>
      </ModalSaveForm>
    </Modal>
  );
}
