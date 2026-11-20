"use client";

import { CSSProperties, useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import type { Route } from "next";
import Link from "next/link";

import { EventIcon } from "@/components/events/event-icons";
import { fallbackTagColor } from "@/components/events/event-utils";
import { EventUpdateHandler, useEventAutosave } from "@/components/events/use-event-autosave";
import { ActionMenu, ActionMenuItem } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { DateInput } from "@/components/ui/date-input";
import { HelpPopover } from "@/components/ui/help-popover";
import { Modal } from "@/components/ui/modal";
import { LazyRichTextEditor as RichTextEditor } from "@/components/ui/rich-text-editor-lazy";
import { SearchInput } from "@/components/ui/search-input";
import { StatusBanner } from "@/components/ui/status-banner";
import { Tabs } from "@/components/ui/tabs";
import { TagInput } from "@/components/ui/tag-input";
import { TimeInput } from "@/components/ui/time-input";
import { useParticipantSelectable } from "@/contexts/participant-date-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { useCycleOptions } from "@/lib/hooks/use-cycle-options";
import { useEventFieldConfig } from "@/lib/hooks/use-event-field-config";
import type { TagConfig } from "@/lib/hooks/use-tag-config";
import { avatarTone, participantInitials } from "@/lib/utils/avatar";
import { getCycleYear } from "@/lib/utils/cycle";
import { toggleRolePatch } from "@/lib/utils/event-patch";
import { formatDateTileParts, formatWeekdayDate } from "@/lib/utils/format";
import { formatTimeValue } from "@/lib/utils/time";
import type { CycleAssignment, CycleConfigSummary, EventPatch, EventRoleField, EventSummary, ParticipantSummary } from "@/types/api";

/** Gültiger Datumsbereich wie im Backend (`EVENT_DATE_MIN`/`EVENT_DATE_MAX`, schemas/event.py). */
export const EVENT_DATE_MIN = "1900-01-01";
export const EVENT_DATE_MAX = "2999-12-31";
/** Spalte `event.participant_count` ist INTEGER (`EVENT_PARTICIPANT_COUNT_MAX` im Backend). */
export const EVENT_PARTICIPANT_COUNT_MAX = 2_147_483_647;

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;
type TextField = "title" | "description" | "program" | "location" | "spezial_text1" | "spezial_text2" | "spezial_text3";
type TimeField = "start_time" | "end_time" | "spezial_time1" | "spezial_time2";
type TabId = "overview" | "participants" | "extra";

const SPECIAL_ROLE_FIELDS: readonly EventRoleField[] = ["spezial1_ids", "spezial2_ids", "spezial3_ids"];

function roleFields(t: TFunc): { field: EventRoleField; label: string }[] {
  return [
    { field: "organizer_ids", label: t("detailForm.organizersLabel") },
    { field: "leadership_ids", label: t("detailForm.leadershipLabel") },
    { field: "participant_ids", label: t("detailForm.participantsLabel") },
    { field: "spezial1_ids", label: t("detailForm.special1Label") },
    { field: "spezial2_ids", label: t("detailForm.special2Label") },
    { field: "spezial3_ids", label: t("detailForm.special3Label") },
  ];
}

/** Leerer Termin für den Anlege-Modus (lokaler Entwurf, bis «Termin erstellen»). */
export function blankEvent(date: string): EventSummary {
  return {
    id: "",
    tenant_id: "",
    event_date: date,
    event_end_date: null,
    event_category_id: 0,
    tag: null,
    title: "",
    description: null,
    participant_count: 0,
    is_cancelled: false,
    organizer_ids: [],
    leadership_ids: [],
    participant_ids: [],
    spezial1_ids: [],
    spezial2_ids: [],
    spezial3_ids: [],
    location: null,
    spezial_text1: null,
    spezial_text2: null,
    spezial_text3: null,
    start_time: null,
    end_time: null,
    spezial_time1: null,
    spezial_time2: null,
    program: null,
    cycle_assignments: [],
    created_at: "",
    updated_at: "",
  };
}

/** Body für POST /api/events aus dem Entwurf (Enddatum nur, wenn es nach dem Start liegt). */
export function createEventBody(draft: EventSummary, cycleAssignments: CycleAssignment[] | undefined) {
  const endDate = draft.event_end_date && draft.event_end_date > draft.event_date ? draft.event_end_date : null;
  return {
    event_date: draft.event_date,
    event_end_date: endDate,
    tag: draft.tag || null,
    title: draft.title.trim(),
    description: draft.description || null,
    program: draft.program || null,
    location: draft.location || null,
    start_time: draft.start_time || null,
    end_time: draft.end_time || null,
    spezial_time1: draft.spezial_time1 || null,
    spezial_time2: draft.spezial_time2 || null,
    spezial_text1: draft.spezial_text1 || null,
    spezial_text2: draft.spezial_text2 || null,
    spezial_text3: draft.spezial_text3 || null,
    participant_count: clampParticipantCount(draft.participant_count),
    is_cancelled: draft.is_cancelled,
    cycle_assignments: cycleAssignments,
    organizer_ids: draft.organizer_ids ?? [],
    leadership_ids: draft.leadership_ids ?? [],
    participant_ids: draft.participant_ids ?? [],
    spezial1_ids: draft.spezial1_ids ?? [],
    spezial2_ids: draft.spezial2_ids ?? [],
    spezial3_ids: draft.spezial3_ids ?? [],
  };
}

export function clampParticipantCount(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(EVENT_PARTICIPANT_COUNT_MAX, Math.max(0, Math.trunc(value)));
}

function isValidIsoDate(value: string | null | undefined): boolean {
  return !!value && /^\d{4}-\d{2}-\d{2}$/.test(value) && value >= EVENT_DATE_MIN && value <= EVENT_DATE_MAX; // i18n-ok: Vergleichsoperator, kein JSX
}

/** Kleiner Hinweis an Spezialfeldern: frei benennbar, mit Link zu den Einstellungen (wer sie ändern darf). */
function SpecialFieldTag({ href, t }: { href: string | null; t: TFunc }) {
  const title = t("detailForm.specialFieldTitle");
  return href ? (
    <Link href={`${href}#event-fields` as Route} className="event-special-field-tag" title={title}>
      {t("detailForm.specialFieldTag")}
    </Link>
  ) : (
    <span className="event-special-field-tag" title={title}>{t("detailForm.specialFieldTag")}</span>
  );
}

export type EventDialogProps = {
  open: boolean;
  onClose: () => void;
  /** Bestehender Termin: Bearbeiten mit Autosave. `null`: neuer Termin (Anlegen). */
  event: EventSummary | null;
  /** Vorbelegtes Datum beim Anlegen (ISO). */
  initialDate?: string;
  /** Vorbelegter Tag beim Anlegen. */
  initialTag?: string | null;
  allowEndDate?: boolean;
  availableParticipants: ParticipantSummary[];
  knownEventTags: string[];
  tagConfig?: TagConfig;
  onTagColorChange?: (tag: string, color: string) => Promise<void>;
  onTagRename?: (oldTag: string, newTag: string) => Promise<void | boolean>;
  /** Bearbeiten: speichert eine Änderung. Rückgabe `false` oder Exception = nicht gespeichert. */
  onUpdate?: EventUpdateHandler;
  /** Anlegen: der Termin wurde erstellt. Der Aufrufer reicht ihn als `event` zurück (weiter mit Autosave). */
  onCreated?: (event: EventSummary) => void;
  /** Löschen im Menü «⋯» (nur Bearbeiten). Fragt selbst nach (useConfirmEventDelete) und schliesst. */
  onDelete?: () => void | Promise<void>;
  /** Zyklus-Definitionen für die Standardzuordnung beim Anlegen (sonst selbst geladen). */
  cycleConfigs?: CycleConfigSummary[];
  /** Nur ansehen (Leserecht): Felder gesperrt, nichts wird gespeichert. */
  readOnly?: boolean;
  /** Hinweis auf die Einstellungen für Rollen-/Zusatzfelder (nur wer sie ändern darf). */
  fieldSettingsHref?: string | null;
  /** Darf Zyklen verwalten (Struktur → Zyklen) - steuert den Hinweis, wenn keine Zyklen existieren. */
  canManageCycles?: boolean;
};

const NOOP_UPDATE: EventUpdateHandler = () => true;

/**
 * Termin-Dialog (Design «hocX Termin Dialog v3»): ein Dialog für Anlegen und Bearbeiten.
 * Bearbeiten speichert jedes Feld automatisch (useEventAutosave). Anlegen sieht gleich aus, hält
 * die Eingaben lokal und legt den Termin mit «Termin erstellen» an, sobald Titel und Datum gültig
 * sind; danach arbeitet derselbe Dialog mit Autosave weiter.
 */
export function EventDialog({
  open,
  onClose,
  event,
  initialDate = "",
  initialTag = null,
  allowEndDate = true,
  availableParticipants,
  knownEventTags,
  tagConfig,
  onTagColorChange,
  onTagRename,
  onUpdate,
  onCreated,
  onDelete,
  cycleConfigs,
  readOnly = false,
  fieldSettingsHref = null,
  canManageCycles = false,
}: EventDialogProps) {
  const t = useTranslations("events");
  const locale = useLocale();
  const showToast = useToast();
  const isParticipantSelectable = useParticipantSelectable();
  const eventFields = useEventFieldConfig();
  const { options: cycleOptions, loading: cyclesLoading } = useCycleOptions();
  const creating = event === null;

  const [activeTab, setActiveTab] = useState<TabId>("overview");
  const [activeRole, setActiveRole] = useState<EventRoleField | null>(null);
  const [roleSearch, setRoleSearch] = useState("");
  const [createDraft, setCreateDraft] = useState<EventSummary>(() => ({ ...blankEvent(initialDate), tag: initialTag || null }));
  // false = Zyklen folgen dem Termindatum (Backend ordnet zu); true = manuell gewählt.
  const [cyclesTouched, setCyclesTouched] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [loadedCycleConfigs, setLoadedCycleConfigs] = useState<CycleConfigSummary[] | null>(null);

  const autosave = useEventAutosave(event?.id ?? "", onUpdate ?? NOOP_UPDATE);

  // Neuer Termin: Entwurf bei jedem Öffnen frisch.
  useEffect(() => {
    if (!open || !creating) return;
    setCreateDraft({ ...blankEvent(initialDate), tag: initialTag || null });
    setCyclesTouched(false);
    setActiveTab("overview");
    setActiveRole(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, creating, initialDate]);

  // Standardzuordnung der Zyklen beim Anlegen braucht die Stichtage der Zyklus-Definitionen.
  useEffect(() => {
    if (!open || !creating || cycleConfigs || loadedCycleConfigs) return;
    let cancelled = false;
    browserApiFetch<CycleConfigSummary[]>("/api/cycle-configs")
      .then((configs) => {
        if (!cancelled) setLoadedCycleConfigs(configs ?? []);
      })
      .catch(() => {
        if (!cancelled) setLoadedCycleConfigs([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open, creating, cycleConfigs, loadedCycleConfigs]);

  const current: EventSummary = creating ? createDraft : ({ ...event, ...autosave.draft } as EventSummary);

  function updateDraft(patch: EventPatch) {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { role_ids_base, ...rest } = patch;
    setCreateDraft((draft) => ({ ...draft, ...rest }));
  }
  /** Textfelder: sofort anzeigen, entprellt speichern. */
  const queue = creating ? updateDraft : autosave.queue;
  /** Klick-Felder: sofort speichern. */
  const commit = creating ? updateDraft : autosave.commit;
  const flush = creating ? () => undefined : autosave.flush;

  const ROLE_FIELDS = roleFields(t)
    .filter((role) => !eventFields.hidden(role.field))
    .map((role) => ({ ...role, label: eventFields.label(role.field, role.label) }));
  const specialTexts = (["spezial_text1", "spezial_text2", "spezial_text3"] as const)
    .map((field, index) => ({ field, label: eventFields.label(field, t(`detailForm.specialText${index + 1}Label`)) }))
    .filter(({ field }) => !eventFields.hidden(field));
  const specialTimes = (["spezial_time1", "spezial_time2"] as const)
    .map((field, index) => ({ field, label: eventFields.label(field, t(`detailForm.specialTime${index + 1}Label`)) }))
    .filter(({ field }) => !eventFields.hidden(field));
  const settingsHref = readOnly ? null : fieldSettingsHref;

  const effectiveCycleConfigs = cycleConfigs ?? loadedCycleConfigs ?? [];
  const defaultCycles = useMemo<CycleAssignment[]>(
    () =>
      createDraft.event_date
        ? effectiveCycleConfigs.map((config) => ({
            cycle_config_id: config.id,
            cycle_year: getCycleYear(createDraft.event_date, config.reset_month, config.reset_day),
          }))
        : [],
    [createDraft.event_date, effectiveCycleConfigs]
  );
  const cycleAssignments: CycleAssignment[] = creating
    ? cyclesTouched
      ? createDraft.cycle_assignments
      : defaultCycles
    : current.cycle_assignments ?? [];

  function textValue(field: TextField): string {
    const value = current[field];
    return value === null || value === undefined ? "" : String(value);
  }

  function timeValue(field: TimeField): string {
    return formatTimeValue(current[field] ?? null);
  }

  function toggleCycle(cycleConfigId: string, cycleYear: number) {
    const exists = cycleAssignments.some((a) => a.cycle_config_id === cycleConfigId && a.cycle_year === cycleYear);
    const next = exists
      ? cycleAssignments.filter((a) => !(a.cycle_config_id === cycleConfigId && a.cycle_year === cycleYear))
      : [...cycleAssignments, { cycle_config_id: cycleConfigId, cycle_year: cycleYear }];
    if (creating) setCyclesTouched(true);
    commit({ cycle_assignments: next });
  }

  function toggleParticipant(field: EventRoleField, participantId: string) {
    commit(toggleRolePatch(current, field, participantId));
  }

  function setParticipantCount(value: number) {
    queue({ participant_count: clampParticipantCount(value) });
  }

  const titleValid = current.title.trim().length > 0;
  const dateValid = isValidIsoDate(current.event_date);
  const canCreate = creating && titleValid && dateValid && !submitting;

  /** Legt den Termin an. `closeAfter`: danach schliessen (Escape), sonst weiter mit Autosave. */
  async function create(closeAfter = false) {
    if (!canCreate) return;
    setSubmitting(true);
    try {
      const saved = await browserApiFetch<EventSummary>("/api/events", {
        method: "POST",
        body: JSON.stringify(createEventBody(createDraft, cyclesTouched ? createDraft.cycle_assignments : undefined)),
      });
      showToast(t("toasts.eventCreated"), "success");
      onCreated?.(saved);
      if (closeAfter) onClose();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.saveFailed"), "error");
    } finally {
      setSubmitting(false);
    }
  }

  // ── Kopf ──────────────────────────────────────────────────────────
  const tile = formatDateTileParts(dateValid ? current.event_date : null, locale);
  const startTime = timeValue("start_time");
  const endTime = timeValue("end_time");
  const multiDay = allowEndDate && !!current.event_end_date && current.event_end_date > current.event_date;
  const dateText = dateValid
    ? multiDay
      ? t("dialog.dateRange", { start: formatWeekdayDate(current.event_date, locale), end: formatWeekdayDate(current.event_end_date, locale) })
      : formatWeekdayDate(current.event_date, locale)
    : "";
  const timeText =
    startTime && endTime
      ? t("dialog.timeRange", { start: startTime, end: endTime })
      : startTime
        ? t("dialog.timeFrom", { start: startTime })
        : endTime
          ? t("dialog.timeUntil", { end: endTime })
          : "";
  const metaText = dateText && timeText ? t("dialog.dateWithTime", { date: dateText, time: timeText }) : dateText || timeText;
  const tagColor = current.tag ? tagConfig?.[current.tag]?.color ?? fallbackTagColor(current.tag) : "";

  const saveState = creating ? null : autosave.saveState;
  const statusText = creating
    ? t("dialog.createHint")
    : saveState === "saving"
      ? t("detailForm.saveStatus.saving")
      : saveState === "saved"
        ? t("detailForm.saveStatus.saved")
        : saveState === "error"
          ? t("detailForm.saveStatus.error")
          : t("detailForm.saveStatus.idle");

  const menuItems: ActionMenuItem[] = [
    {
      label: current.is_cancelled ? t("contextMenu.uncancel") : t("contextMenu.markCancelled"),
      onClick: () => commit({ is_cancelled: !current.is_cancelled }),
    },
  ];
  if (!creating && onDelete) {
    menuItems.push({ label: t("toasts.deleteConfirmLabel"), danger: true, onClick: () => void Promise.resolve(onDelete()).catch(() => undefined) });
  }

  const header = (
    <div className="event-dialog-head">
      <div className={`event-dialog-tile${dateValid ? "" : " event-dialog-tile-empty"}`} aria-hidden="true">
        <span className="event-dialog-tile-month">{tile.month}</span>
        <span className="event-dialog-tile-day">{tile.day}</span>
        <span className="event-dialog-tile-weekday">{tile.weekday}</span>
      </div>
      <div className="event-dialog-head-text">
        <input
          className={`event-dialog-title-input${current.is_cancelled ? " event-dialog-title-cancelled" : ""}`}
          value={current.title}
          onChange={(e) => queue({ title: e.target.value })}
          onBlur={flush}
          onKeyDown={(e) => {
            if (e.key === "Enter" && creating) {
              e.preventDefault();
              void create();
            }
          }}
          placeholder={t("createModal.titlePlaceholder")}
          aria-label={t("form.title")}
          readOnly={readOnly}
          required
          autoFocus={creating}
        />
        <div className="event-dialog-meta">
          {metaText ? <span>{metaText}</span> : null}
          {current.tag ? (
            <span className="badge event-tag-badge" style={{ "--tag-color": tagColor } as CSSProperties}>
              <span className="badge-dot" />
              {current.tag}
            </span>
          ) : null}
          {current.is_cancelled ? <Badge variant="danger">{t("dialog.cancelledChip")}</Badge> : null}
        </div>
      </div>
    </div>
  );

  const headerActions = readOnly ? null : (
    <div className="event-dialog-actions">
      <span
        className={`event-dialog-status${saveState ? ` event-dialog-status-${saveState}` : ""}`}
        role="status"
        aria-live="polite"
      >
        {statusText}
      </span>
      {creating ? (
        <button type="button" className="button-primary" disabled={!canCreate} onClick={() => void create()}>
          {t("form.create")}
        </button>
      ) : null}
      <ActionMenu ariaLabel={t("dialog.moreActions")} items={menuItems} />
    </div>
  );

  // ── Reiter Übersicht ─────────────────────────────────────────────
  const overview = (
    <fieldset className="event-detail-fieldset" disabled={readOnly}>
      <div className="event-dialog-overview">
        <div className="event-dialog-main">
          {/* Markdown-Felder: div statt label, sonst leitet ein Klick auf die Toolbar um */}
          <div className="field-stack event-dialog-rte" onBlur={flush}>
            <span className="field-label">{t("detailForm.descriptionLabel")}</span>
            <RichTextEditor
              value={textValue("description")}
              readOnly={readOnly}
              placeholder={t("createModal.descriptionPlaceholder")}
              onChange={(markdown) => queue({ description: markdown || null })}
            />
          </div>
          <div className="field-stack event-dialog-rte" onBlur={flush}>
            <span className="field-label">{t("detailForm.programLabel")}</span>
            <RichTextEditor
              value={textValue("program")}
              readOnly={readOnly}
              placeholder={t("detailForm.programPlaceholder")}
              onChange={(markdown) => queue({ program: markdown || null })}
            />
          </div>
        </div>
        <div className="event-dialog-side">
          <div className="field-stack">
            <span className="field-label">{t("createModal.period")}</span>
            <div className="event-dialog-period">
              <span className="event-dialog-period-label">{t("dialog.from")}</span>
              <DateInput
                value={current.event_date}
                onChange={(value) => value && commit({ event_date: value })}
                aria-label={t("form.startDate")}
                min={EVENT_DATE_MIN}
                max={EVENT_DATE_MAX}
                required
              />
              <TimeInput
                className="event-dialog-time"
                value={startTime}
                aria-label={t("detailForm.startTimeLabel")}
                onChange={(value) => commit({ start_time: value || null })}
              />
              <span className="event-dialog-period-label">{t("dialog.until")}</span>
              {allowEndDate ? (
                <div className={current.event_end_date ? "event-dialog-end" : "event-dialog-end event-dialog-end-empty"}>
                  <DateInput
                    value={current.event_end_date ?? ""}
                    onChange={(value) => commit({ event_end_date: value || null })}
                    aria-label={t("form.endDate")}
                    placeholder={t("createModal.singleDay")}
                    min={current.event_date && current.event_date >= EVENT_DATE_MIN ? current.event_date : EVENT_DATE_MIN}
                    max={EVENT_DATE_MAX}
                  />
                </div>
              ) : (
                <span className="event-dialog-same-day">{t("dialog.sameDay")}</span>
              )}
              <TimeInput
                className="event-dialog-time"
                value={endTime}
                aria-label={t("detailForm.endTimeLabel")}
                onChange={(value) => commit({ end_time: value || null })}
              />
            </div>
            <span className="field-help">{t("dialog.periodHint")}</span>
          </div>

          <label className="field-stack">
            <span className="field-label">{t("form.location")}</span>
            <span className="event-dialog-location">
              <EventIcon name="pin" aria-hidden="true" />
              <input
                value={textValue("location")}
                placeholder={t("form.locationPlaceholder")}
                onChange={(e) => queue({ location: e.target.value || null })}
                onBlur={flush}
              />
            </span>
          </label>

          <div className="field-stack">
            <span className="event-dialog-label-row">
              <span className="field-label">
                {t("form.tag")}
                <HelpPopover topic={t("form.tag")} docs={{ page: "termine", anchor: "tags" }}>
                  {t("help.tag")}
                </HelpPopover>
              </span>
              <span className="field-help">{t("dialog.exactlyOneTag")}</span>
            </span>
            <TagInput
              value={current.tag ?? ""}
              onChange={(value) => commit({ tag: value || null })}
              suggestions={knownEventTags}
              multi={false}
              readOnly={readOnly}
              tagConfig={tagConfig}
              onTagColorChange={onTagColorChange}
              onTagRename={onTagRename}
              placeholder={t("form.tagPlaceholder")}
            />
          </div>

          <div className="field-stack">
            <span className="field-label">
              {t("form.cycles")}
              <HelpPopover topic={t("form.cycles")} docs={{ page: "termine", anchor: "zyklen" }}>
                {t("help.cycles")}
              </HelpPopover>
            </span>
            {cyclesLoading ? (
              <span className="muted">{t("form.cyclesLoading")}</span>
            ) : cycleOptions.length === 0 ? (
              <span className="muted">{canManageCycles ? t("form.noCycles") : t("form.noCyclesAskAdmin")}</span>
            ) : (
              <div className="cycle-chip-list">
                {cycleOptions.map((cycle) => {
                  const active = cycleAssignments.some(
                    (a) => a.cycle_config_id === cycle.cycle_config_id && a.cycle_year === cycle.cycle_year
                  );
                  return (
                    <button
                      key={`${cycle.cycle_config_id}-${cycle.cycle_year}`}
                      type="button"
                      className={`cycle-chip${active ? " cycle-chip-active" : ""}`}
                      aria-pressed={active}
                      onClick={() => toggleCycle(cycle.cycle_config_id, cycle.cycle_year)}
                    >
                      {cycle.name}
                    </button>
                  );
                })}
              </div>
            )}
            <span className="field-help">{t("form.cyclesHint")}</span>
          </div>
        </div>
      </div>
    </fieldset>
  );

  // ── Reiter Teilnehmer & Status ───────────────────────────────────
  const activeRoleLabel = ROLE_FIELDS.find((role) => role.field === activeRole)?.label ?? "";
  const nameById = new Map(availableParticipants.map((participant) => [participant.id, participant]));
  const people = (
    <fieldset className="event-detail-fieldset" disabled={readOnly}>
      <div className="event-dialog-pane">
        <div className="event-dialog-status-cards">
          <label className={`event-dialog-card event-dialog-cancel-card${current.is_cancelled ? " event-dialog-cancel-card-active" : ""}`}>
            <input type="checkbox" checked={current.is_cancelled} onChange={(e) => commit({ is_cancelled: e.target.checked })} />
            <span className="event-dialog-card-text">
              <strong>{t("form.cancelled")}</strong>
              <span className="field-help">{t("detailForm.cancelledHint")}</span>
            </span>
          </label>
          <div className="event-dialog-card event-dialog-count-card">
            <span className="event-dialog-card-text">
              <strong id="event-dialog-count-label">{t("form.participantCount")}</strong>
              <span className="field-help">{t("dialog.participantCountHint")}</span>
            </span>
            <div className="event-dialog-stepper">
              <button
                type="button"
                className="button-icon-soft"
                aria-label={t("dialog.decrease")}
                disabled={current.participant_count <= 0}
                onClick={() => setParticipantCount(current.participant_count - 1)}
              >
                −
              </button>
              <input
                type="number"
                inputMode="numeric"
                min={0}
                max={EVENT_PARTICIPANT_COUNT_MAX}
                aria-labelledby="event-dialog-count-label"
                value={String(current.participant_count ?? 0)}
                onChange={(e) => setParticipantCount(Number(e.target.value || "0"))}
                onBlur={flush}
                onFocus={(e) => e.target.select()}
              />
              <button
                type="button"
                className="button-icon-soft"
                aria-label={t("dialog.increase")}
                disabled={current.participant_count >= EVENT_PARTICIPANT_COUNT_MAX}
                onClick={() => setParticipantCount(current.participant_count + 1)}
              >
                +
              </button>
            </div>
          </div>
        </div>

        <div className="field-stack">
          <span className="field-label">
            {t("form.people")}
            <HelpPopover topic={t("form.people")} docs={{ page: "termine", anchor: "rollen-und-zusatzfelder" }}>
              {t("help.roles")}
            </HelpPopover>
          </span>
          <div className="event-dialog-role-grid">
            {ROLE_FIELDS.map(({ field, label }) => {
              const ids = (current[field] as string[] | null) ?? [];
              const selected = ids.map((id) => nameById.get(id)).filter((p): p is ParticipantSummary => !!p);
              return (
                <div key={field} className={`event-dialog-role-card${activeRole === field ? " event-dialog-role-card-active" : ""}`}>
                  <div className="event-dialog-role-head">
                    <span className="event-dialog-role-name">
                      {label}
                      {SPECIAL_ROLE_FIELDS.includes(field) ? <SpecialFieldTag href={settingsHref} t={t} /> : null}
                    </span>
                    <span className="event-dialog-role-count">{ids.length}</span>
                  </div>
                  {selected.length > 0 ? (
                    <ul className="event-dialog-person-list">
                      {selected.map((participant) => (
                        <li key={participant.id} className="event-dialog-person">
                          <span className={`participant-avatar participant-avatar-tone-${avatarTone(participant.id)} event-dialog-avatar`} aria-hidden="true">
                            {participantInitials(participant)}
                          </span>
                          {participant.display_name}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <span className="muted event-dialog-role-empty">{t("detailForm.noneSelected")}</span>
                  )}
                  {!readOnly ? (
                    <button
                      type="button"
                      className="event-dialog-role-add"
                      aria-expanded={activeRole === field}
                      onClick={() => {
                        setActiveRole((currentRole) => (currentRole === field ? null : field));
                        setRoleSearch("");
                      }}
                    >
                      {ids.length > 0 ? t("dialog.editPeople") : t("dialog.addPeople")}
                    </button>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>

        {activeRole && !readOnly ? (
          <div className="event-dialog-picker">
            <div className="event-dialog-picker-head">
              <strong>{t("dialog.chooseRole", { role: activeRoleLabel })}</strong>
              <button type="button" className="button-secondary" onClick={() => setActiveRole(null)}>
                {t("detailForm.doneButton")}
              </button>
            </div>
            <SearchInput value={roleSearch} onChange={setRoleSearch} placeholder={t("dialog.searchPlaceholder")} aria-label={t("pickerModal.search")} autoFocus />
            <div className="participant-check-grid">
              {availableParticipants
                .filter((participant) => isParticipantSelectable(participant) || ((current[activeRole] as string[] | null) ?? []).includes(participant.id))
                .filter((participant) => participant.display_name.toLowerCase().includes(roleSearch.trim().toLowerCase()))
                .map((participant) => {
                  const checked = ((current[activeRole] as string[] | null) ?? []).includes(participant.id);
                  return (
                    <label key={participant.id} className={`participant-check-card${checked ? " participant-check-card-active" : ""}`}>
                      <input type="checkbox" checked={checked} onChange={() => toggleParticipant(activeRole, participant.id)} />
                      <span>{participant.display_name}</span>
                    </label>
                  );
                })}
            </div>
          </div>
        ) : null}
      </div>
    </fieldset>
  );

  // ── Reiter Weitere Felder ────────────────────────────────────────
  const extra = (
    <fieldset className="event-detail-fieldset" disabled={readOnly}>
      <div className="event-dialog-pane">
        {specialTimes.length ? (
          <div className="event-dialog-special-times">
            {specialTimes.map(({ field, label }) => (
              <label key={field} className="field-stack">
                <span className="field-label event-special-field-label">
                  {label}
                  <SpecialFieldTag href={settingsHref} t={t} />
                </span>
                <TimeInput value={timeValue(field)} onChange={(value) => commit({ [field]: value || null } as EventPatch)} />
              </label>
            ))}
          </div>
        ) : null}
        {specialTexts.map(({ field, label }) => (
          <div key={field} className="field-stack event-dialog-rte event-dialog-rte-sm" onBlur={flush}>
            <span className="field-label event-special-field-label">
              {label}
              <SpecialFieldTag href={settingsHref} t={t} />
            </span>
            <RichTextEditor value={textValue(field)} readOnly={readOnly} onChange={(markdown) => queue({ [field]: markdown || null } as EventPatch)} />
          </div>
        ))}
        {specialTimes.length === 0 && specialTexts.length === 0 ? <p className="muted">{t("dialog.noExtraFields")}</p> : null}
        {settingsHref ? (
          <p className="field-help event-dialog-extra-foot">
            {t("detailForm.fieldSettingsHint")}{" "}
            <Link href={`${settingsHref}#event-fields` as Route}>{t("detailForm.fieldSettingsLink")}</Link>
          </p>
        ) : null}
      </div>
    </fieldset>
  );

  const participantCount = (current.participant_ids ?? []).length;

  return (
    <Modal
      open={open}
      onClose={onClose}
      // Anlegen: Escape erstellt wie in allen Formular-Modals (sofern gültig), sonst schliessen.
      // Bearbeiten: offene Eingaben speichert useEventAutosave beim Schliessen.
      onEscape={() => (canCreate ? create(true) : onClose())}
      title={current.title || (creating ? t("form.createTitle") : t("detailModal.fallbackTitle"))}
      size="wide"
      className="event-dialog"
      header={header}
      headerActions={headerActions}
    >
      {readOnly ? <StatusBanner tone="warning" message={t("detailForm.readOnlyHint")} /> : null}
      <Tabs
        activeId={activeTab}
        onChange={(id) => setActiveTab(id as TabId)}
        tabs={[
          { id: "overview", label: t("detailForm.overviewTab"), content: overview },
          { id: "participants", label: t("detailForm.participantsTab"), count: participantCount, content: people },
          { id: "extra", label: t("detailForm.extraFieldsTab"), content: extra },
        ]}
      />
    </Modal>
  );
}
