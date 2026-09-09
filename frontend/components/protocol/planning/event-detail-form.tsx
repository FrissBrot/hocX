"use client";

import { useState } from "react";

import { Tabs } from "@/components/ui/tabs";
import { DateInput } from "@/components/ui/date-input";
import { TagInput } from "@/components/ui/tag-input";
import { EventSummary, ParticipantSummary } from "@/types/api";
import type { TagConfig } from "@/lib/hooks/use-tag-config";

type RoleField = "organizer_ids" | "leadership_ids" | "participant_ids" | "spezial1_ids" | "spezial2_ids" | "spezial3_ids";

const ROLE_FIELDS: { field: RoleField; label: string }[] = [
  { field: "organizer_ids", label: "Organisatoren" },
  { field: "leadership_ids", label: "Leitungsteam" },
  { field: "participant_ids", label: "Teilnehmer" },
  { field: "spezial1_ids", label: "Spezial 1" },
  { field: "spezial2_ids", label: "Spezial 2" },
  { field: "spezial3_ids", label: "Spezial 3" },
];

type EventDetailFormProps = {
  event: EventSummary;
  allowEndDate?: boolean;
  availableParticipants: ParticipantSummary[];
  knownEventTags: string[];
  tagConfig: TagConfig;
  onTagColorChange: (tag: string, color: string) => Promise<void>;
  onTagRename: (oldTag: string, newTag: string) => Promise<void>;
  onUpdate: (patch: Partial<EventSummary>) => void | Promise<void>;
};

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
}: EventDetailFormProps) {
  const [activeRoleField, setActiveRoleField] = useState<RoleField | null>(null);
  const [roleSearch, setRoleSearch] = useState("");

  function participantNames(ids: string[] | null | undefined) {
    const list = availableParticipants.filter((p) => (ids ?? []).includes(p.id));
    return list.length ? list.map((p) => p.display_name).join(", ") : "Niemand ausgewählt";
  }

  function toggleParticipant(field: RoleField, participantId: string) {
    const current = ((event[field] as string[] | null) ?? []) as string[];
    const next = current.includes(participantId)
      ? current.filter((id) => id !== participantId)
      : [...current, participantId];
    void onUpdate({ [field]: next } as Partial<EventSummary>);
  }

  const activeRoleLabel = ROLE_FIELDS.find((r) => r.field === activeRoleField)?.label ?? "";

  return (
    <div className="event-detail-form">
    <Tabs
      tabs={[
        {
          id: "overview",
          label: "Übersicht",
          content: (
            <div className="grid" style={{ gap: 14 }}>
              <div className="two-col">
                <label className="field-stack">
                  <span className="field-label">Datum</span>
                  <DateInput value={event.event_date} onChange={(value) => void onUpdate({ event_date: value })} />
                </label>
                {allowEndDate ? (
                  <label className="field-stack">
                    <span className="field-label">Enddatum</span>
                    <DateInput
                      value={event.event_end_date ?? ""}
                      onChange={(value) => void onUpdate({ event_end_date: value || null })}
                    />
                  </label>
                ) : null}
              </div>
              <label className="field-stack">
                <span className="field-label">Tag</span>
                <TagInput
                  value={event.tag ?? ""}
                  onChange={(v) => void onUpdate({ tag: v || null })}
                  suggestions={knownEventTags}
                  multi={false}
                  tagConfig={tagConfig}
                  onTagColorChange={onTagColorChange}
                  onTagRename={onTagRename}
                />
              </label>
              <label className="field-stack">
                <span className="field-label">Titel</span>
                <input value={event.title} onChange={(e) => void onUpdate({ title: e.target.value })} />
              </label>
              <label className="field-stack">
                <span className="field-label">Beschreibung</span>
                <textarea
                  rows={4}
                  value={event.description ?? ""}
                  onChange={(e) => void onUpdate({ description: e.target.value || null })}
                />
              </label>
            </div>
          ),
        },
        {
          id: "participants",
          label: "Teilnehmer & Status",
          content: (
            <div className="grid" style={{ gap: 14 }}>
              <label className="field-radio-option">
                <input
                  type="checkbox"
                  checked={event.is_cancelled}
                  onChange={(e) => void onUpdate({ is_cancelled: e.target.checked })}
                />
                <div>
                  <strong>Termin abgesagt</strong>
                  <div className="muted" style={{ fontSize: "0.82rem" }}>
                    Markiert den Termin als abgesagt, ohne ihn zu löschen.
                  </div>
                </div>
              </label>
              <label className="field-stack">
                <span className="field-label">Anzahl Teilnehmer</span>
                <input
                  type="number"
                  min="0"
                  value={event.participant_count ?? 0}
                  onChange={(e) => void onUpdate({ participant_count: Math.max(0, Number(e.target.value || "0")) })}
                  onFocus={(e) => e.target.select()}
                />
              </label>
              <div className="field-stack">
                <span className="field-label">Personen</span>
                <div className="two-col" style={{ rowGap: 8 }}>
                  {ROLE_FIELDS.map(({ field, label }) => (
                    <div key={field} className="field-stack" style={{ gap: 4 }}>
                      <span className="muted" style={{ fontSize: "0.78rem" }}>
                        {label}
                      </span>
                      <button
                        type="button"
                        className="button-ghost structured-list-picker"
                        style={{ textAlign: "left", minHeight: 36, padding: "6px 10px", fontSize: "0.85rem" }}
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
                      Fertig
                    </button>
                  </div>
                  <div className="grid">
                    <input
                      value={roleSearch}
                      onChange={(e) => setRoleSearch(e.target.value)}
                      placeholder="Suchen…"
                      autoFocus
                    />
                  </div>
                  <div className="participant-check-grid">
                    {availableParticipants
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
          ),
        },
        {
          id: "extra",
          label: "Weitere Felder",
          content: (
            <div className="grid" style={{ gap: 14 }}>
              <label className="field-stack">
                <span className="field-label">Standort</span>
                <input value={event.location ?? ""} onChange={(e) => void onUpdate({ location: e.target.value || null })} />
              </label>
              <div className="two-col">
                <label className="field-stack">
                  <span className="field-label">Spezial Text 1</span>
                  <input
                    value={event.spezial_text1 ?? ""}
                    onChange={(e) => void onUpdate({ spezial_text1: e.target.value || null })}
                  />
                </label>
                <label className="field-stack">
                  <span className="field-label">Spezial Text 2</span>
                  <input
                    value={event.spezial_text2 ?? ""}
                    onChange={(e) => void onUpdate({ spezial_text2: e.target.value || null })}
                  />
                </label>
              </div>
              <label className="field-stack">
                <span className="field-label">Spezial Text 3</span>
                <input
                  value={event.spezial_text3 ?? ""}
                  onChange={(e) => void onUpdate({ spezial_text3: e.target.value || null })}
                />
              </label>
            </div>
          ),
        },
      ]}
    />
    </div>
  );
}
