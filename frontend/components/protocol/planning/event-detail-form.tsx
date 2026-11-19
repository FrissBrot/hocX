"use client";

import { useParticipantSelectable } from "@/contexts/participant-date-context";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import type { Route } from "next";
import Link from "next/link";

import { Tabs } from "@/components/ui/tabs";
import { DateInput } from "@/components/ui/date-input";
import { LazyRichTextEditor as RichTextEditor } from "@/components/ui/rich-text-editor-lazy";
import { TimeInput } from "@/components/ui/time-input";
import { TagInput } from "@/components/ui/tag-input";
import { HelpPopover } from "@/components/ui/help-popover";
import { CycleAssignment, EventPatch, EventRoleField, EventSummary, ParticipantSummary } from "@/types/api";
import { toggleRolePatch } from "@/lib/utils/event-patch";
import { useCycleOptions } from "@/lib/hooks/use-cycle-options";
import { useEventFieldConfig } from "@/lib/hooks/use-event-field-config";
import { formatTimeValue } from "@/lib/utils/time";
import type { TagConfig } from "@/lib/hooks/use-tag-config";

type RoleField = EventRoleField;

/** Text- und Zahlenfelder speichern entprellt: erst nach dieser Tipp-Pause (oder beim Verlassen). */
export const EVENT_TEXT_SAVE_DELAY_MS = 600;

type DebouncedField = "title" | "description" | "program" | "location" | "spezial_text1" | "spezial_text2" | "spezial_text3" | "participant_count";

type TimeField = "start_time" | "end_time" | "spezial_time1" | "spezial_time2";

const SPECIAL_ROLE_FIELDS: readonly RoleField[] = ["spezial1_ids", "spezial2_ids", "spezial3_ids"];

type SaveState = "idle" | "saving" | "saved" | "error";

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

function roleFields(t: TFunc): { field: RoleField; label: string }[] {
  return [
    { field: "organizer_ids", label: t("detailForm.organizersLabel") },
    { field: "leadership_ids", label: t("detailForm.leadershipLabel") },
    { field: "participant_ids", label: t("detailForm.participantsLabel") },
    { field: "spezial1_ids", label: t("detailForm.special1Label") },
    { field: "spezial2_ids", label: t("detailForm.special2Label") },
    { field: "spezial3_ids", label: t("detailForm.special3Label") },
  ];
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

type EventDetailFormProps = {
  event: EventSummary;
  allowEndDate?: boolean;
  availableParticipants: ParticipantSummary[];
  knownEventTags: string[];
  tagConfig: TagConfig;
  onTagColorChange: (tag: string, color: string) => Promise<void>;
  onTagRename: (oldTag: string, newTag: string) => Promise<void | boolean>;
  /** Rückgabe `false` oder eine Exception gelten als «nicht gespeichert». */
  onUpdate: (patch: EventPatch) => void | boolean | Promise<void | boolean>;
  /** Nur ansehen (Leserecht): Felder gesperrt, nichts wird gespeichert. */
  readOnly?: boolean;
  /** Hinweis auf die Einstellungen für Rollen-/Zusatzfelder (nur wer sie ändern darf). */
  fieldSettingsHref?: string | null;
  /** Darf Zyklen verwalten (Struktur → Zyklen) - steuert den Hinweis, wenn keine Zyklen existieren. */
  canManageCycles?: boolean;
};

/**
 * Speichert Änderungen eines Termins der Reihe nach (nie zwei PATCH gleichzeitig, damit keine
 * ältere Anfrage eine neuere überholt). Textfelder werden entprellt gesammelt und beim
 * Verlassen des Feldes, beim Wechsel des Termins, beim Schliessen und vor dem Verlassen der
 * Seite sofort gespeichert. Bis zur Bestätigung zeigt das Formular den lokalen Entwurf.
 */
export function useEventAutosave(eventId: string, onUpdate: EventDetailFormProps["onUpdate"]) {
  const [draft, setDraft] = useState<Partial<EventSummary>>({});
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const pendingRef = useRef<Partial<EventSummary>>({});
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const chainRef = useRef<Promise<void>>(Promise.resolve());
  const inFlightRef = useRef(0);
  const mountedRef = useRef(true);
  const onUpdateRef = useRef(onUpdate);
  useLayoutEffect(() => {
    onUpdateRef.current = onUpdate;
  });

  const send = useCallback((patch: EventPatch) => {
    // Ziel jetzt festhalten: der Aufruf gilt dem Termin, zu dem die Änderung gehört.
    const target = onUpdateRef.current;
    inFlightRef.current += 1;
    if (mountedRef.current) setSaveState("saving");
    chainRef.current = chainRef.current.then(async () => {
      let ok = true;
      try {
        ok = (await target(patch)) !== false;
      } catch {
        ok = false;
      }
      inFlightRef.current -= 1;
      if (!mountedRef.current) return;
      setDraft((current) => {
        const next = { ...current };
        let changed = false;
        for (const key of Object.keys(patch) as (keyof EventSummary)[]) {
          if (key in next && next[key] === patch[key]) {
            delete next[key];
            changed = true;
          }
        }
        return changed ? next : current;
      });
      const idle = inFlightRef.current === 0 && Object.keys(pendingRef.current).length === 0;
      if (!ok) setSaveState("error");
      else if (idle) setSaveState((current) => (current === "error" ? current : "saved"));
    });
  }, []);

  const flush = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    const patch = pendingRef.current;
    if (Object.keys(patch).length === 0) return;
    pendingRef.current = {};
    send(patch);
  }, [send]);

  /** Für Textfelder: sofort anzeigen, entprellt speichern. */
  const queue = useCallback(
    (patch: Partial<EventSummary>) => {
      setDraft((current) => ({ ...current, ...patch }));
      pendingRef.current = { ...pendingRef.current, ...patch };
      setSaveState("saving");
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(flush, EVENT_TEXT_SAVE_DELAY_MS);
    },
    [flush]
  );

  /** Für Klick-Felder (Checkbox, Datum, Auswahl): offene Texte zuerst, dann sofort speichern. */
  const commit = useCallback(
    (patch: EventPatch) => {
      flush();
      send(patch);
    },
    [flush, send]
  );

  // Termin gewechselt oder Formular geschlossen: Offenes sofort an den bisherigen Termin senden.
  useLayoutEffect(() => {
    mountedRef.current = true;
    return () => {
      flush();
      setDraft({});
    };
  }, [eventId, flush]);

  useEffect(
    () => () => {
      mountedRef.current = false;
    },
    []
  );

  // Seite verlassen/neu laden: offene Eingaben noch abschicken und den Browser nachfragen lassen.
  useEffect(() => {
    function onBeforeUnload(event: BeforeUnloadEvent) {
      const hasPending = Object.keys(pendingRef.current).length > 0;
      if (!hasPending && inFlightRef.current === 0) return;
      flush();
      event.preventDefault();
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [flush]);

  return { draft, saveState, queue, commit, flush };
}

/**
 * Full Termin-Karte with tabs — used for editing a Termin from inside planning-mode popups
 * (Termine-pro-Element checkbox popup, Terminübersicht). Every field wrapper uses
 * className="grid" (not inline display:grid) so inputs pick up the app's standard styled
 * look automatically via the global `.grid input/textarea/select` rule.
 */
export function EventDetailForm({
  event,
  allowEndDate = false,
  availableParticipants,
  knownEventTags,
  tagConfig,
  onTagColorChange,
  onTagRename,
  onUpdate,
  readOnly = false,
  fieldSettingsHref = null,
  canManageCycles = false,
}: EventDetailFormProps) {
  const isParticipantSelectable = useParticipantSelectable();
  const t = useTranslations("events");
  const tCommon = useTranslations("common");
  const [activeRoleField, setActiveRoleField] = useState<RoleField | null>(null);
  const [roleSearch, setRoleSearch] = useState("");
  // Spezialfelder: Alias und Ausblenden aus den Mandant-Einstellungen
  const eventFields = useEventFieldConfig();
  const ROLE_FIELDS = roleFields(t)
    .filter((role) => !eventFields.hidden(role.field))
    .map((role) => ({ ...role, label: eventFields.label(role.field, role.label) }));
  const specialTexts = (["spezial_text1", "spezial_text2", "spezial_text3"] as const)
    .map((field, index) => ({ field, label: eventFields.label(field, t(`detailForm.specialText${index + 1}Label`)) }))
    .filter(({ field }) => !eventFields.hidden(field));
  const specialTimes = (["spezial_time1", "spezial_time2"] as const)
    .map((field, index) => ({ field, label: eventFields.label(field, t(`detailForm.specialTime${index + 1}Label`)) }))
    .filter(({ field }) => !eventFields.hidden(field));
  const { options: cycleOptions, loading: cyclesLoading } = useCycleOptions();
  const { draft, saveState, queue, commit, flush } = useEventAutosave(event.id, onUpdate);
  const cycleAssignments: CycleAssignment[] = event.cycle_assignments ?? [];

  function textValue(field: DebouncedField): string {
    const value = field in draft ? draft[field] : event[field];
    return value === null || value === undefined ? "" : String(value);
  }

  function timeValue(field: TimeField): string {
    return formatTimeValue(event[field] ?? null);
  }

  function toggleCycle(cycleConfigId: string, cycleYear: number) {
    const exists = cycleAssignments.some((a) => a.cycle_config_id === cycleConfigId && a.cycle_year === cycleYear);
    const next = exists
      ? cycleAssignments.filter((a) => !(a.cycle_config_id === cycleConfigId && a.cycle_year === cycleYear))
      : [...cycleAssignments, { cycle_config_id: cycleConfigId, cycle_year: cycleYear }];
    commit({ cycle_assignments: next });
  }

  function participantNames(ids: string[] | null | undefined) {
    const list = availableParticipants.filter((p) => (ids ?? []).includes(p.id));
    return list.length ? list.map((p) => p.display_name).join(", ") : t("detailForm.noneSelected");
  }

  function toggleParticipant(field: RoleField, participantId: string) {
    commit(toggleRolePatch(event, field, participantId));
  }

  const activeRoleLabel = ROLE_FIELDS.find((r) => r.field === activeRoleField)?.label ?? "";

  return (
    <div className="event-detail-form">
    {readOnly ? (
      <p className="field-help">{t("detailForm.readOnlyHint")}</p>
    ) : (
      <p className="field-help event-detail-save-status" role="status" aria-live="polite">
        {saveState === "saving"
          ? t("detailForm.saveStatus.saving")
          : saveState === "saved"
            ? t("detailForm.saveStatus.saved")
            : saveState === "error"
              ? t("detailForm.saveStatus.error")
              : t("detailForm.saveStatus.idle")}
      </p>
    )}
    <Tabs
      tabs={[
        {
          id: "overview",
          label: t("detailForm.overviewTab"),
          content: (
            <fieldset className="event-detail-fieldset" disabled={readOnly}>
            <div className="grid" style={{ gap: "var(--space-4)" }}>
              <div className="two-col">
                <label className="field-stack">
                  <span className="field-label">{t("detailForm.dateLabel")}</span>
                  <DateInput value={event.event_date} onChange={(value) => value && commit({ event_date: value })} />
                </label>
                {allowEndDate ? (
                  <label className="field-stack">
                    <span className="field-label">{t("form.endDate")}</span>
                    <DateInput
                      value={event.event_end_date ?? ""}
                      onChange={(value) => commit({ event_end_date: value || null })}
                    />
                  </label>
                ) : null}
              </div>
              <div className="two-col">
                {(["start_time", "end_time"] as const).map((field) => (
                  <label key={field} className="field-stack">
                    <span className="field-label">{t(field === "start_time" ? "detailForm.startTimeLabel" : "detailForm.endTimeLabel")}</span>
                    <TimeInput value={timeValue(field)} onChange={(value) => commit({ [field]: value || null } as Partial<EventSummary>)} />
                  </label>
                ))}
              </div>
              <div className="field-stack">
                <span className="field-label">
                  {t("form.tag")}
                  <HelpPopover topic={t("form.tag")} docs={{ page: "termine", anchor: "tags" }}>
                    {t("help.tag")}
                  </HelpPopover>
                </span>
                <TagInput
                  value={event.tag ?? ""}
                  onChange={(v) => commit({ tag: v || null })}
                  suggestions={knownEventTags}
                  multi={false}
                  tagConfig={tagConfig}
                  onTagColorChange={onTagColorChange}
                  onTagRename={onTagRename}
                />
              </div>
              <label className="field-stack">
                <span className="field-label">{t("form.title")}</span>
                <input value={textValue("title")} onChange={(e) => queue({ title: e.target.value })} onBlur={flush} />
              </label>
              {/* Markdown-Felder: div statt label, sonst leitet ein Klick auf die Toolbar um */}
              <div className="field-stack" onBlur={flush}>
                <span className="field-label">{t("detailForm.descriptionLabel")}</span>
                <RichTextEditor value={textValue("description")} readOnly={readOnly} onChange={(markdown) => queue({ description: markdown || null })} />
              </div>
              <div className="field-stack" onBlur={flush}>
                <span className="field-label">{t("detailForm.programLabel")}</span>
                <RichTextEditor
                  value={textValue("program")}
                  readOnly={readOnly}
                  placeholder={t("detailForm.programPlaceholder")}
                  onChange={(markdown) => queue({ program: markdown || null })}
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
            </fieldset>
          ),
        },
        {
          id: "participants",
          label: t("detailForm.participantsTab"),
          content: (
            <fieldset className="event-detail-fieldset" disabled={readOnly}>
            <div className="grid" style={{ gap: "var(--space-4)" }}>
              <label className="field-radio-option">
                <input
                  type="checkbox"
                  checked={event.is_cancelled}
                  onChange={(e) => commit({ is_cancelled: e.target.checked })}
                />
                <div>
                  <strong>{t("form.cancelled")}</strong>
                  <div className="muted" style={{ fontSize: "var(--text-sm)" }}>
                    {t("detailForm.cancelledHint")}
                  </div>
                </div>
              </label>
              <label className="field-stack">
                <span className="field-label">{t("form.participantCount")}</span>
                <input
                  type="number"
                  min="0"
                  value={textValue("participant_count") || "0"}
                  onChange={(e) => queue({ participant_count: Math.max(0, Number(e.target.value || "0")) })}
                  onBlur={flush}
                  onFocus={(e) => e.target.select()}
                />
              </label>
              <div className="field-stack">
                <span className="field-label">
                  {t("form.people")}
                  <HelpPopover topic={t("form.people")} docs={{ page: "termine", anchor: "rollen-und-zusatzfelder" }}>
                    {t("help.roles")}
                  </HelpPopover>
                </span>
                <div className="two-col" style={{ rowGap: "var(--space-2)" }}>
                  {ROLE_FIELDS.map(({ field, label }) => (
                    <div key={field} className="field-stack" style={{ gap: "var(--space-1)" }}>
                      <span className="muted event-special-field-label">
                        {label}
                        {SPECIAL_ROLE_FIELDS.includes(field) ? <SpecialFieldTag href={readOnly ? null : fieldSettingsHref} t={t} /> : null}
                      </span>
                      <button
                        type="button"
                        className="button-ghost structured-list-picker"
                        style={{ textAlign: "left", minHeight: 36, padding: "var(--space-2) var(--space-3)", fontSize: "var(--text-base)" }}
                        onClick={() => {
                          setActiveRoleField(field);
                          setRoleSearch("");
                        }}
                      >
                        {participantNames(event[field] as string[])}
                      </button>
                    </div>
                  ))}
                </div>
              </div>
              {activeRoleField ? (
                <div className="event-detail-role-picker">
                  <div className="editor-planning-toolbar" style={{ justifyContent: "space-between" }}>
                    <strong>{activeRoleLabel}</strong>
                    <button type="button" className="button-ghost" onClick={() => setActiveRoleField(null)}>
                      {t("detailForm.doneButton")}
                    </button>
                  </div>
                  <div className="grid">
                    <input
                      value={roleSearch}
                      onChange={(e) => setRoleSearch(e.target.value)}
                      placeholder={tCommon("searchPlaceholder")}
                      autoFocus
                    />
                  </div>
                  <div className="participant-check-grid">
                    {availableParticipants.filter(isParticipantSelectable)
                      .filter((p) => p.display_name.toLowerCase().includes(roleSearch.trim().toLowerCase()))
                      .map((p) => {
                        const checked = ((event[activeRoleField] as string[] | null) ?? []).includes(p.id);
                        return (
                          <label
                            key={p.id}
                            className={`participant-check-card${checked ? " participant-check-card-active" : ""}`}
                          >
                            <input type="checkbox" checked={checked} onChange={() => toggleParticipant(activeRoleField, p.id)} />
                            <div>{p.display_name}</div>
                          </label>
                        );
                      })}
                  </div>
                </div>
              ) : null}
            </div>
            </fieldset>
          ),
        },
        {
          id: "extra",
          label: t("detailForm.extraFieldsTab"),
          content: (
            <fieldset className="event-detail-fieldset" disabled={readOnly}>
            <div className="grid" style={{ gap: "var(--space-4)" }}>
              <label className="field-stack">
                <span className="field-label">{t("form.location")}</span>
                <input value={textValue("location")} onChange={(e) => queue({ location: e.target.value || null })} onBlur={flush} />
              </label>
              {specialTimes.length ? (
                <div className="two-col">
                  {specialTimes.map(({ field, label }) => (
                    <label key={field} className="field-stack">
                      <span className="field-label event-special-field-label">
                        {label}
                        <SpecialFieldTag href={readOnly ? null : fieldSettingsHref} t={t} />
                      </span>
                      <TimeInput value={timeValue(field)} onChange={(value) => commit({ [field]: value || null } as Partial<EventSummary>)} />
                    </label>
                  ))}
                </div>
              ) : null}
              {specialTexts.map(({ field, label }) => (
                <div key={field} className="field-stack" onBlur={flush}>
                  <span className="field-label event-special-field-label">
                    {label}
                    <SpecialFieldTag href={readOnly ? null : fieldSettingsHref} t={t} />
                  </span>
                  <RichTextEditor value={textValue(field)} readOnly={readOnly} onChange={(markdown) => queue({ [field]: markdown || null })} />
                </div>
              ))}
              {fieldSettingsHref && !readOnly ? (
                <p className="field-help">
                  {t("detailForm.fieldSettingsHint")}{" "}
                  <Link href={`${fieldSettingsHref}#event-fields` as Route}>{t("detailForm.fieldSettingsLink")}</Link>
                </p>
              ) : null}
            </div>
            </fieldset>
          ),
        },
      ]}
    />
    </div>
  );
}
