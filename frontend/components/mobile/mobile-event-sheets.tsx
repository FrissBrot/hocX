"use client";

import { useRouter } from "next/navigation";
import type { Route } from "next";
import { useMemo } from "react";
import { useLocale, useTranslations } from "next-intl";

import { MobileIcon } from "@/components/mobile/mobile-icons";
import { MobileAvatar, MobileListRow, MobileTagPill } from "@/components/mobile/mobile-ui";
import { dateParts, relativeDay, tagColor } from "@/components/mobile/mobile-utils";
import { ActionMenu } from "@/components/ui/action-menu";
import { Modal } from "@/components/ui/modal";
import { LazyRichTextEditor as RichTextEditor } from "@/components/ui/rich-text-editor-lazy";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirmEventDelete } from "@/components/events/use-confirm-event-delete";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import type { CycleOption } from "@/lib/hooks/use-cycle-options";
import type { TagConfig } from "@/lib/hooks/use-tag-config";
import type { EventSummary, ParticipantSummary, ProtocolSummary } from "@/types/api";

export function eventDateLabel(event: EventSummary, locale: string): string {
  if (event.event_end_date && event.event_end_date > event.event_date) {
    return `${dateParts.long(event.event_date, locale)} – ${dateParts.long(event.event_end_date, locale)}`;
  }
  return dateParts.long(event.event_date, locale);
}

export function EventDetailSheet({
  event,
  canEdit,
  protocol,
  participants,
  cycleOptions,
  tagConfig,
  onClose,
  onEdit,
  onChange,
  onDeleted,
}: {
  event: EventSummary;
  canEdit: boolean;
  protocol: ProtocolSummary | null;
  participants: ParticipantSummary[];
  cycleOptions: CycleOption[];
  tagConfig: TagConfig;
  onClose: () => void;
  onEdit: () => void;
  onChange: (event: EventSummary) => void;
  onDeleted: (id: string) => void;
}) {
  const t = useTranslations("mobile");
  const tEvents = useTranslations("events");
  const locale = useLocale();
  const router = useRouter();
  const confirmEventDelete = useConfirmEventDelete();
  const showToast = useToast();

  const nameById = useMemo(() => new Map(participants.map((participant) => [participant.id, participant.display_name])), [participants]);
  const people = [
    { role: t("events.organizers"), ids: event.organizer_ids ?? [] },
    { role: t("events.leadership"), ids: event.leadership_ids ?? [] },
  ]
    .map((group) => ({ ...group, names: group.ids.map((id) => nameById.get(id)).filter((name): name is string => !!name) }))
    .filter((group) => group.names.length > 0);
  const cycles = (event.cycle_assignments ?? [])
    .map((assignment) => cycleOptions.find((option) => option.cycle_config_id === assignment.cycle_config_id && option.cycle_year === assignment.cycle_year)?.name)
    .filter((name): name is string => !!name);

  async function toggleCancelled() {
    const next = !event.is_cancelled;
    onChange({ ...event, is_cancelled: next });
    try {
      await browserApiFetch(`/api/events/${event.id}`, { method: "PATCH", body: JSON.stringify({ is_cancelled: next }) });
      showToast(next ? t("events.markedCancelled") : t("events.cancelReverted"), "success");
    } catch (error) {
      onChange(event);
      showToast(error instanceof Error ? error.message : tEvents("toasts.eventUpdateFailed"), "error");
    }
  }

  async function remove() {
    const ok = await confirmEventDelete(event.id, event.title);
    if (!ok) return;
    try {
      await browserApiFetch(`/api/events/${event.id}`, { method: "DELETE" });
      onDeleted(event.id);
      showToast(tEvents("toasts.deleted"), "success");
      onClose();
    } catch (error) {
      showToast(error instanceof Error ? error.message : tEvents("toasts.deleteFailed"), "error");
    }
  }

  return (
    <Modal
      open
      size="sheet"
      title={event.title}
      onClose={onClose}
      className="mobile-sheet"
      header={
        event.is_cancelled ? (
          <MobileTagPill label={t("events.cancelled")} color="" cancelled />
        ) : event.tag ? (
          <MobileTagPill label={event.tag} color={tagColor(event.tag, tagConfig)} />
        ) : (
          <span />
        )
      }
      headerActions={
        canEdit ? (
          <ActionMenu
            ariaLabel={t("events.actions")}
            items={[
              { label: t("common.edit"), onClick: onEdit },
              { label: event.is_cancelled ? t("events.revertCancel") : t("events.markCancelled"), onClick: () => void toggleCancelled() },
              { label: t("events.delete"), onClick: () => void remove(), danger: true },
            ]}
          />
        ) : null
      }
      footer={
        canEdit || protocol ? (
          <div className="mobile-sheet-footer">
            {canEdit ? (
              <button type="button" className="button-secondary mobile-sheet-footer-grow" onClick={onEdit}>
                {t("common.edit")}
              </button>
            ) : null}
            {protocol ? (
              <button type="button" className="button-primary mobile-sheet-footer-grow" onClick={() => router.push(`/protocols/${protocol.id}` as Route)}>
                {t("dashboard.openProtocol")}
              </button>
            ) : null}
          </div>
        ) : undefined
      }
    >
      <div className="grid mobile-sheet-body">
        <div>
          <h2 className={`mobile-sheet-title${event.is_cancelled ? " mobile-text-struck" : ""}`}>{event.title}</h2>
          <div className="mobile-sheet-date">{eventDateLabel(event, locale)}</div>
          <div className="mobile-muted-sm">{relativeDay(event.event_date, t)}</div>
        </div>
        {event.is_cancelled ? <StatusBanner tone="error" message={t("events.cancelledHint")} /> : null}
        <div className="mobile-card mobile-group-card">
          <MobileListRow
            leading={<MobileIcon name="location" size={18} className="mobile-list-row-icon" />}
            label={<span className="mobile-stacked"><small>{t("events.location")}</small>{event.location || "—"}</span>}
          />
          <MobileListRow
            leading={<MobileIcon name="people" size={18} className="mobile-list-row-icon" />}
            label={
              <span className="mobile-stacked">
                <small>{t("events.participantCount")}</small>
                {event.participant_count ? t("events.persons", { count: event.participant_count }) : "—"}
              </span>
            }
          />
          {protocol ? (
            <MobileListRow
              leading={<MobileIcon name="document" size={18} className="mobile-list-row-icon" />}
              label={<span className="mobile-stacked"><small>{t("events.protocol")}</small><span className="mobile-link-text">{protocol.protocol_number}</span></span>}
              onClick={() => router.push(`/protocols/${protocol.id}` as Route)}
            />
          ) : null}
        </div>
        {event.description ? (
          <div className="mobile-field-block">
            <div className="mobile-eyebrow">{t("events.description")}</div>
            {/* Markdown, gerendert wie im Terminformular */}
            <div className="mobile-body-text"><RichTextEditor value={event.description} readOnly onChange={() => undefined} /></div>
          </div>
        ) : null}
        {event.program ? (
          <div className="mobile-field-block">
            <div className="mobile-eyebrow">{t("events.program")}</div>
            <div className="mobile-body-text"><RichTextEditor value={event.program} readOnly onChange={() => undefined} /></div>
          </div>
        ) : null}
        {people.map((group) => (
          <div key={group.role} className="mobile-field-block">
            <div className="mobile-eyebrow">{group.role}</div>
            <div className="mobile-tag-wrap">
              {group.names.map((name) => (
                <span key={name} className="mobile-person-chip">
                  <MobileAvatar name={name} size="xs" />
                  {name}
                </span>
              ))}
            </div>
          </div>
        ))}
        {cycles.length > 0 ? (
          <div className="mobile-field-block">
            <div className="mobile-eyebrow">{t("events.cycle")}</div>
            <div className="mobile-tag-wrap">
              {cycles.map((name) => (
                <span key={name} className="mobile-cycle-pill">{name}</span>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </Modal>
  );
}
