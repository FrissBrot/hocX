"use client";

import { useRouter } from "next/navigation";
import type { Route } from "next";
import { useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { MobileIcon } from "@/components/mobile/mobile-icons";
import { MobileAvatar, MobileChip, MobileListRow, MobileSwitch, MobileTagPill } from "@/components/mobile/mobile-ui";
import { dateParts, relativeDay, tagColor, todayIso } from "@/components/mobile/mobile-utils";
import { ActionMenu } from "@/components/ui/action-menu";
import { DateInput } from "@/components/ui/date-input";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
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
  const confirm = useConfirm();
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
    const ok = await confirm({ message: tEvents("toasts.deleteConfirmMessage"), tone: "danger", confirmLabel: tEvents("toasts.deleteConfirmLabel") });
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
            <p className="mobile-body-text">{event.description}</p>
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

type Draft = {
  title: string;
  event_date: string;
  event_end_date: string;
  tag: string | null;
  participant_count: number;
  location: string;
  description: string;
  is_cancelled: boolean;
};

function draftFrom(event: EventSummary | null): Draft {
  return {
    title: event?.title ?? "",
    event_date: event?.event_date?.slice(0, 10) ?? todayIso(),
    event_end_date: event?.event_end_date?.slice(0, 10) ?? "",
    tag: event?.tag ?? null,
    participant_count: event?.participant_count ?? 0,
    location: event?.location ?? "",
    description: event?.description ?? "",
    is_cancelled: event?.is_cancelled ?? false,
  };
}

export function EventFormSheet({
  event,
  tags,
  tagConfig,
  onClose,
  onSaved,
}: {
  event: EventSummary | null;
  tags: string[];
  tagConfig: TagConfig;
  onClose: () => void;
  onSaved: (event: EventSummary, created: boolean) => void;
}) {
  const t = useTranslations("mobile");
  const tEvents = useTranslations("events");
  const showToast = useToast();
  const [draft, setDraft] = useState<Draft>(() => draftFrom(event));
  const [saving, setSaving] = useState(false);
  const valid = draft.title.trim().length > 0 && draft.event_date.length > 0;
  const update = (patch: Partial<Draft>) => setDraft((current) => ({ ...current, ...patch }));

  async function save() {
    if (!valid || saving) return;
    setSaving(true);
    const body = {
      title: draft.title.trim(),
      event_date: draft.event_date,
      event_end_date: draft.event_end_date && draft.event_end_date > draft.event_date ? draft.event_end_date : null,
      tag: draft.tag || null,
      participant_count: Math.max(0, draft.participant_count),
      location: draft.location.trim() || null,
      description: draft.description.trim() || null,
      is_cancelled: draft.is_cancelled,
    };
    try {
      const saved = event
        ? await browserApiFetch<EventSummary>(`/api/events/${event.id}`, { method: "PATCH", body: JSON.stringify(body) })
        : await browserApiFetch<EventSummary>("/api/events", { method: "POST", body: JSON.stringify(body) });
      onSaved(saved, !event);
      showToast(event ? t("events.saved") : tEvents("toasts.eventCreated"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : tEvents("toasts.saveFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open
      size="sheet"
      title={event ? t("events.editTitle") : t("events.newTitle")}
      onClose={onClose}
      className="mobile-sheet"
      footer={
        <div className="modal-actions mobile-sheet-footer">
          <button type="button" className="button-ghost" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button type="button" className="button-primary" data-modal-save disabled={!valid || saving} onClick={() => void save()}>
            {t("common.save")}
          </button>
        </div>
      }
    >
      <div className="grid mobile-sheet-body">
        <label className="field-stack">
          <span className="field-label">{t("events.fieldTitle")}</span>
          <input value={draft.title} onChange={(e) => update({ title: e.target.value })} placeholder={t("events.titlePlaceholder")} />
        </label>
        <div className="two-col">
          <label className="field-stack">
            <span className="field-label">{t("events.fieldStart")}</span>
            <DateInput value={draft.event_date} onChange={(value) => update({ event_date: value })} />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("events.fieldEnd")}</span>
            <DateInput value={draft.event_end_date} min={draft.event_date || undefined} onChange={(value) => update({ event_end_date: value })} />
          </label>
        </div>
        {tags.length > 0 ? (
          <div className="field-stack">
            <span className="field-label">{t("events.fieldTag")}</span>
            <div className="mobile-tag-wrap">
              {tags.map((tag) => (
                <MobileChip key={tag} active={draft.tag === tag} dotColor={tagColor(tag, tagConfig)} onClick={() => update({ tag: draft.tag === tag ? null : tag })}>
                  {tag}
                </MobileChip>
              ))}
            </div>
          </div>
        ) : null}
        <div className="mobile-stepper-row">
          <span className="field-label">{t("events.participantCount")}</span>
          <div className="mobile-stepper">
            <button type="button" aria-label={t("events.decrease")} onClick={() => update({ participant_count: Math.max(0, draft.participant_count - 1) })}>
              −
            </button>
            <span>{draft.participant_count}</span>
            <button type="button" aria-label={t("events.increase")} onClick={() => update({ participant_count: draft.participant_count + 1 })}>
              +
            </button>
          </div>
        </div>
        <label className="field-stack">
          <span className="field-label">{t("events.location")}</span>
          <input value={draft.location} onChange={(e) => update({ location: e.target.value })} placeholder={t("events.locationPlaceholder")} />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("events.description")}</span>
          <textarea rows={3} value={draft.description} onChange={(e) => update({ description: e.target.value })} placeholder={t("events.descriptionPlaceholder")} />
        </label>
        <div className="mobile-card mobile-group-card">
          <button type="button" className="mobile-list-row" aria-pressed={draft.is_cancelled} onClick={() => update({ is_cancelled: !draft.is_cancelled })}>
            <span className="mobile-list-row-label">{t("events.cancelledToggle")}</span>
            <MobileSwitch checked={draft.is_cancelled} danger />
          </button>
        </div>
        <p className="mobile-muted-sm">{t("events.formDesktopHint")}</p>
      </div>
    </Modal>
  );
}
