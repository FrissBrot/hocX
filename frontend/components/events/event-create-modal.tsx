"use client";

import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { daySpan } from "@/components/events/event-utils";
import { DateInput } from "@/components/ui/date-input";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { getCycleYear } from "@/lib/utils/cycle";
import { CycleAssignment, CycleConfigSummary, CycleInfo, EventSummary, ParticipantSummary } from "@/types/api";

type ParticipantPickerField = "organizer_ids" | "leadership_ids" | "participant_ids" | "spezial1_ids" | "spezial2_ids" | "spezial3_ids";
type FlatCycle = CycleInfo & { cycle_config_id: string; config_name: string };

type FormState = {
  event_date: string;
  event_end_date: string;
  tag: string;
  title: string;
  description: string;
  location: string;
  participant_count: string;
  is_cancelled: boolean;
  cycle_assignments: CycleAssignment[];
  // false = Zyklen folgen dem Termindatum (Backend ordnet zu); true = manuell gewählt.
  cycle_assignments_touched: boolean;
} & Record<ParticipantPickerField, string[]>;

function emptyForm(date: string): FormState {
  return {
    event_date: date,
    event_end_date: "",
    tag: "",
    title: "",
    description: "",
    location: "",
    participant_count: "0",
    is_cancelled: false,
    cycle_assignments: [],
    cycle_assignments_touched: false,
    organizer_ids: [],
    leadership_ids: [],
    participant_ids: [],
    spezial1_ids: [],
    spezial2_ids: [],
    spezial3_ids: [],
  };
}

const FORM_ID = "event-create-form";

type Props = {
  open: boolean;
  onClose: () => void;
  /** ISO-Datum, mit dem der Termin vorbelegt wird (z. B. aus dem Kalender). */
  initialDate: string;
  knownTags: string[];
  availableParticipants: ParticipantSummary[];
  cycleConfigs: CycleConfigSummary[];
  tenantName?: string | null;
  onCreated: (event: EventSummary) => void;
};

export function EventCreateModal({ open, onClose, initialDate, knownTags, availableParticipants, cycleConfigs, tenantName, onCreated }: Props) {
  const t = useTranslations("events");
  const showToast = useToast();
  const [form, setForm] = useState<FormState>(() => emptyForm(initialDate));
  const [saving, setSaving] = useState(false);
  const [extraTags, setExtraTags] = useState<string[]>([]);
  const [newTagDraft, setNewTagDraft] = useState<string | null>(null);
  const [pickerField, setPickerField] = useState<ParticipantPickerField | null>(null);
  const [pickerSearch, setPickerSearch] = useState("");
  const [availableCycles, setAvailableCycles] = useState<FlatCycle[]>([]);
  const [cyclesLoading, setCyclesLoading] = useState(false);
  const cyclesLoadedRef = useRef(false);
  const formRef = useRef<HTMLFormElement | null>(null);

  const roleFields = useMemo<{ field: ParticipantPickerField; label: string }[]>(
    () => [
      { field: "organizer_ids", label: t("columns.organizers") },
      { field: "leadership_ids", label: t("columns.leadership") },
      { field: "participant_ids", label: t("columns.participantsRole") },
      { field: "spezial1_ids", label: t("columns.special1") },
      { field: "spezial2_ids", label: t("columns.special2") },
      { field: "spezial3_ids", label: t("columns.special3") },
    ],
    [t]
  );

  useEffect(() => {
    if (!open) return;
    setForm(emptyForm(initialDate));
    setExtraTags([]);
    setNewTagDraft(null);
    void ensureCyclesLoaded();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialDate]);

  async function ensureCyclesLoaded() {
    if (cyclesLoadedRef.current) return;
    cyclesLoadedRef.current = true;
    setCyclesLoading(true);
    try {
      const configs = cycleConfigs.length > 0 ? cycleConfigs : await browserApiFetch<CycleConfigSummary[]>("/api/cycle-configs"); // i18n-ok: Vergleichsoperator, kein JSX
      const cycleGroups = await Promise.all(
        (configs ?? []).map((cfg) =>
          browserApiFetch<CycleInfo[]>(`/api/cycle-configs/${cfg.id}/cycles`)
            .then((cycles) => (cycles ?? []).map((c) => ({ ...c, cycle_config_id: cfg.id, config_name: cfg.name })))
            .catch(() => [] as FlatCycle[])
        )
      );
      setAvailableCycles(cycleGroups.flat());
    } catch (error) {
      cyclesLoadedRef.current = false;
      showToast(error instanceof Error ? error.message : t("toasts.cyclesLoadFailed"), "error");
    } finally {
      setCyclesLoading(false);
    }
  }

  function defaultCycleAssignments(eventDate: string): CycleAssignment[] {
    if (!eventDate) return [];
    return cycleConfigs.map((config) => ({
      cycle_config_id: config.id,
      cycle_year: getCycleYear(eventDate, config.reset_month, config.reset_day),
    }));
  }

  const cycleAssignments = form.cycle_assignments_touched ? form.cycle_assignments : defaultCycleAssignments(form.event_date);

  function toggleCycle(cycleConfigId: string, cycleYear: number) {
    setForm((current) => {
      const base = current.cycle_assignments_touched ? current.cycle_assignments : defaultCycleAssignments(current.event_date);
      const exists = base.some((a) => a.cycle_config_id === cycleConfigId && a.cycle_year === cycleYear);
      const next = exists
        ? base.filter((a) => !(a.cycle_config_id === cycleConfigId && a.cycle_year === cycleYear))
        : [...base, { cycle_config_id: cycleConfigId, cycle_year: cycleYear }];
      return { ...current, cycle_assignments: next, cycle_assignments_touched: true };
    });
  }

  function togglePickerParticipant(field: ParticipantPickerField, participantId: string) {
    setForm((current) => {
      const selected = current[field];
      return {
        ...current,
        [field]: selected.includes(participantId) ? selected.filter((id) => id !== participantId) : [...selected, participantId],
      };
    });
  }

  function participantNames(ids: string[]): string | null {
    if (ids.length === 0) return null;
    const names = ids.map((id) => availableParticipants.find((p) => p.id === id)?.display_name).filter(Boolean);
    return names.length ? names.join(", ") : t("selectedCount", { count: ids.length });
  }

  const tagOptions = useMemo(() => {
    const set = new Set([...knownTags, ...extraTags]);
    return Array.from(set);
  }, [extraTags, knownTags]);

  function commitNewTag() {
    const value = (newTagDraft ?? "").trim();
    setNewTagDraft(null);
    if (!value) return;
    if (!tagOptions.includes(value)) setExtraTags((current) => [...current, value]);
    setForm((current) => ({ ...current, tag: value }));
  }

  function onNewTagKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      commitNewTag();
    } else if (event.key === "Escape") {
      event.stopPropagation();
      setNewTagDraft(null);
    }
  }

  const isValid = form.title.trim().length > 0 && form.event_date.length > 0;
  const endAfterStart = form.event_end_date && form.event_end_date > form.event_date ? form.event_end_date : "";
  const filledRoles = roleFields.filter(({ field }) => form[field].length > 0).length;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isValid || saving) return;
    setSaving(true);
    try {
      const saved = await browserApiFetch<EventSummary>("/api/events", {
        method: "POST",
        body: JSON.stringify({
          event_date: form.event_date,
          event_end_date: endAfterStart || null,
          tag: form.tag || null,
          title: form.title.trim(),
          description: form.description || null,
          participant_count: Math.max(0, Number(form.participant_count || "0")),
          is_cancelled: form.is_cancelled,
          cycle_assignments: form.cycle_assignments_touched ? form.cycle_assignments : undefined,
          organizer_ids: form.organizer_ids,
          leadership_ids: form.leadership_ids,
          participant_ids: form.participant_ids,
          spezial1_ids: form.spezial1_ids,
          spezial2_ids: form.spezial2_ids,
          spezial3_ids: form.spezial3_ids,
          location: form.location || null,
        }),
      });
      onCreated(saved);
      showToast(t("toasts.eventCreated"), "success");
      onClose();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.saveFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <Modal
        open={open}
        onClose={onClose}
        // Escape speichert wie in allen Formular-Modals - ohne Titel gibt es nichts zu speichern.
        onEscape={() => (isValid ? formRef.current?.requestSubmit() : onClose())}
        title={t("form.createTitle")}
        size="wide"
        className="event-create-modal"
        header={
          <div className="event-create-header">
            <span className="event-create-eyebrow">
              {tenantName ? t("createModal.eyebrowTenant", { tenant: tenantName }) : t("createModal.eyebrow")}
            </span>
            <input
              className="event-create-title-input"
              value={form.title}
              onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
              placeholder={t("createModal.titlePlaceholder")}
              aria-label={t("form.title")}
              form={FORM_ID}
              required
              autoFocus
            />
          </div>
        }
        footer={
          <>
            <span className="muted event-create-footer-hint">{t("createModal.requiredHint")}</span>
            <div className="modal-footer-actions">
              <button type="button" className="button-secondary button-ghost" onClick={onClose}>
                {t("importModal.cancel")}
              </button>
              <button type="submit" form={FORM_ID} className="button-primary" disabled={!isValid || saving}>
                {t("form.create")}
              </button>
            </div>
          </>
        }
      >
        <ModalSaveForm id={FORM_ID} ref={formRef} className="event-create-body grid" onSubmit={submit}>
          <div className="event-create-main">
            <div className="field-stack">
              <span className="field-label">{t("createModal.period")}</span>
              <div className="event-range-field">
                <DateInput
                  value={form.event_date}
                  onChange={(value) => setForm((current) => ({ ...current, event_date: value }))}
                  aria-label={t("form.startDate")}
                  required
                />
                <span className="event-range-separator">{t("createModal.until")}</span>
                <DateInput
                  value={form.event_end_date}
                  onChange={(value) => setForm((current) => ({ ...current, event_end_date: value }))}
                  aria-label={t("form.endDate")}
                  min={form.event_date || undefined}
                />
                <span className="event-range-duration">
                  {endAfterStart ? t("createModal.days", { count: daySpan(form.event_date, endAfterStart) }) : t("createModal.singleDay")}
                </span>
              </div>
              <span className="field-help">{t("createModal.periodHint")}</span>
            </div>

            <label className="field-stack">
              <span className="field-label">{t("columns.description")}</span>
              <textarea
                rows={5}
                value={form.description}
                placeholder={t("createModal.descriptionPlaceholder")}
                onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              />
            </label>

            <label className="field-stack">
              <span className="field-label">{t("form.location")}</span>
              <input
                value={form.location}
                placeholder={t("form.locationPlaceholder")}
                onChange={(event) => setForm((current) => ({ ...current, location: event.target.value }))}
              />
            </label>

            {availableParticipants.length > 0 && (
              <div className="field-stack event-create-people">
                <div className="event-create-section-head">
                  <span className="field-label">{t("form.people")}</span>
                  <span className="muted">{t("createModal.rolesFilled", { filled: filledRoles, total: roleFields.length })}</span>
                </div>
                <div className="event-role-list">
                  {roleFields.map(({ field, label }) => {
                    const names = participantNames(form[field]);
                    return (
                      <button
                        key={field}
                        type="button"
                        className="event-role-row"
                        onClick={() => {
                          setPickerField(field);
                          setPickerSearch("");
                        }}
                      >
                        <span className="event-role-label">{label}</span>
                        <span className={names ? "event-role-names" : "event-role-names event-role-names-empty"}>
                          {names ?? t("detailForm.noneSelected")}
                        </span>
                        {form[field].length > 0 ? (
                          <span className="event-role-count">{form[field].length}</span>
                        ) : (
                          <span className="event-role-add" aria-hidden="true">+</span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          <div className="event-create-side">
            <div className="field-stack">
              <span className="field-label">{t("form.tag")}</span>
              <div className="event-tag-chip-list">
                {tagOptions.map((tag) => (
                  <button
                    key={tag}
                    type="button"
                    className={`event-tag-chip${form.tag === tag ? " event-tag-chip-active" : ""}`}
                    aria-pressed={form.tag === tag}
                    onClick={() => setForm((current) => ({ ...current, tag: current.tag === tag ? "" : tag }))}
                  >
                    {tag}
                  </button>
                ))}
                {newTagDraft === null ? (
                  <button type="button" className="event-tag-chip event-tag-chip-new" onClick={() => setNewTagDraft("")}>
                    {t("createModal.newTag")}
                  </button>
                ) : (
                  <input
                    className="event-tag-chip-input"
                    value={newTagDraft}
                    onChange={(event) => setNewTagDraft(event.target.value)}
                    onKeyDown={onNewTagKeyDown}
                    onBlur={commitNewTag}
                    placeholder={t("form.tagPlaceholder")}
                    aria-label={t("createModal.newTagLabel")}
                    autoFocus
                  />
                )}
              </div>
              <span className="field-help">{t("createModal.tagHint")}</span>
            </div>

            <div className="field-stack">
              <span className="field-label">{t("form.cycles")}</span>
              {cyclesLoading ? (
                <span className="muted">{t("form.cyclesLoading")}</span>
              ) : availableCycles.length === 0 ? (
                <span className="muted">{t("form.noCycles")}</span>
              ) : (
                <div className="event-check-card-list">
                  {availableCycles.map((cycle) => {
                    const active = cycleAssignments.some((a) => a.cycle_config_id === cycle.cycle_config_id && a.cycle_year === cycle.cycle_year);
                    return (
                      <label key={`${cycle.cycle_config_id}-${cycle.cycle_year}`} className={`event-check-card${active ? " event-check-card-active" : ""}`}>
                        <input type="checkbox" checked={active} onChange={() => toggleCycle(cycle.cycle_config_id, cycle.cycle_year)} />
                        <span>{cycle.name}</span>
                      </label>
                    );
                  })}
                </div>
              )}
              <span className="field-help">{t("createModal.cyclesHint")}</span>
            </div>

            <div className="field-stack">
              <span className="field-label">{t("createModal.status")}</span>
              <label className={`event-check-card event-check-card-end${form.is_cancelled ? " event-check-card-active" : ""}`}>
                <span>{t("form.cancelled")}</span>
                <input
                  type="checkbox"
                  checked={form.is_cancelled}
                  onChange={(event) => setForm((current) => ({ ...current, is_cancelled: event.target.checked }))}
                />
              </label>
              <span className="field-help">{t("createModal.cancelledHint")}</span>
            </div>

            <label className="field-stack">
              <span className="field-label">{t("form.participantCount")}</span>
              <input
                type="number"
                min="0"
                value={form.participant_count}
                onChange={(event) => setForm((current) => ({ ...current, participant_count: event.target.value }))}
              />
            </label>
          </div>
        </ModalSaveForm>
      </Modal>

      <Modal
        open={Boolean(pickerField)}
        onClose={() => setPickerField(null)}
        title={roleFields.find((r) => r.field === pickerField)?.label ?? t("pickerModal.fallbackTitle")}
        description={t("pickerModal.multiSelect")}
      >
        <div className="grid">
          <label className="field-stack">
            <span className="field-label">{t("pickerModal.search")}</span>
            <input value={pickerSearch} onChange={(e) => setPickerSearch(e.target.value)} placeholder={t("pickerModal.searchPlaceholder")} />
          </label>
          <div className="participant-check-grid">
            {availableParticipants
              .filter((p) => !pickerSearch.trim() || p.display_name.toLowerCase().includes(pickerSearch.toLowerCase()))
              .map((p) => {
                const checked = pickerField ? form[pickerField].includes(p.id) : false;
                return (
                  <label key={p.id} className={`participant-check-card${checked ? " participant-check-card-active" : ""}`}>
                    <input type="checkbox" checked={checked} onChange={() => pickerField && togglePickerParticipant(pickerField, p.id)} />
                    <span>{p.display_name}</span>
                  </label>
                );
              })}
          </div>
        </div>
      </Modal>
    </>
  );
}
