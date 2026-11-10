"use client";

// «Termine wählen» für automatisch pro Termin erzeugte Blöcke: Termine nach Monat gruppiert,
// Reiter Kommend/Vergangen/Alle, «Alle kommenden» und «Keine». Jeder Klick wirkt sofort (wie
// CheckboxCandidateModal, DESIGN.md Abschnitt 8 «Reine Auswahl-Popups»), Termine ausserhalb des
// Filters stehen aufklappbar darunter. Bereits vorhandene Blöcke, deren Termin nicht geladen
// ist, erscheinen oben, damit sie sich weiterhin abwählen lassen.

import { ReactNode, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { ActionIcon } from "@/components/ui/action-icons";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal } from "@/components/ui/modal";
import { formatDateTileParts, formatMonthYear } from "@/lib/utils/format";
import { EventSummary } from "@/types/api";

type Tab = "upcoming" | "past" | "all";

export type UnknownPickedEvent = { key: string; label: string };

type Props = {
  open: boolean;
  onClose: () => void;
  // Tag-Filter der Wiederholung (für die Beschreibung), leer = ohne Tag
  tag: string;
  events: EventSummary[];
  // Termine mit sichtbarem Block
  selectedIds: Set<string>;
  unknownSelected: UnknownPickedEvent[];
  matchesFilter: (event: EventSummary) => boolean;
  protocolDate: string | null;
  loading: boolean;
  onToggle: (eventId: string, nextChecked: boolean) => void | Promise<void>;
  onRemoveUnknown: (key: string) => void | Promise<void>;
  onSelectAllUpcoming: () => void | Promise<void>;
  onSelectNone: () => void | Promise<void>;
  onEditEvent: (event: EventSummary) => void;
  // Zyklus-Umschalter und «Neuer Termin» (bestehende Funktionen des Editors)
  topActions?: ReactNode;
};

function isUpcoming(event: EventSummary, protocolDate: string | null) {
  if (!protocolDate) return true;
  return (event.event_end_date ?? event.event_date) >= protocolDate;
}

export function EventBlockPickerModal({
  open, onClose, tag, events, selectedIds, unknownSelected, matchesFilter, protocolDate, loading,
  onToggle, onRemoveUnknown, onSelectAllUpcoming, onSelectNone, onEditEvent, topActions,
}: Props) {
  const t = useTranslations("protocols");
  const tCommon = useTranslations("common");
  const locale = useLocale();
  const [tab, setTab] = useState<Tab>("upcoming");
  const [showOther, setShowOther] = useState(false);

  const inTab = useMemo(
    () => [...events]
      .filter((event) => tab === "all" || (tab === "upcoming" ? isUpcoming(event, protocolDate) : !isUpcoming(event, protocolDate)))
      .sort((a, b) => a.event_date.localeCompare(b.event_date)),
    [events, tab, protocolDate]
  );
  const matching = inTab.filter(matchesFilter);
  const other = inTab.filter((event) => !matchesFilter(event));
  const months = useMemo(() => {
    const map = new Map<string, EventSummary[]>();
    for (const event of matching) {
      const key = event.event_date.slice(0, 7);
      map.set(key, [...(map.get(key) ?? []), event]);
    }
    return [...map.entries()];
  }, [matching]);
  const selectedCount = selectedIds.size + unknownSelected.length;

  function renderCard(event: EventSummary) {
    const checked = selectedIds.has(event.id);
    const tile = formatDateTileParts(event.event_date, locale);
    const meta = [event.location, event.tag].filter(Boolean).join(" · ");
    return (
      <div
        key={event.id}
        role="button"
        tabIndex={0}
        aria-pressed={checked}
        className={`event-pick-card${checked ? " event-pick-card-checked" : ""}`}
        onClick={() => void onToggle(event.id, !checked)}
        onKeyDown={(keyEvent) => {
          if (keyEvent.key === "Enter" || keyEvent.key === " ") {
            keyEvent.preventDefault();
            void onToggle(event.id, !checked);
          }
        }}
      >
        <div className="event-pick-tile" aria-hidden="true">
          <span className="event-series-tile-day">{tile.day}</span>
          <span className="event-series-tile-month">{tile.weekday}</span>
        </div>
        <div className="event-pick-body">
          <span className={event.is_cancelled ? "event-pick-title event-series-title-cancelled" : "event-pick-title"}>{event.title}</span>
          {meta ? <span className="event-pick-meta">{meta}</span> : null}
        </div>
        <button
          type="button"
          className="button-icon-soft"
          title={t("eventSeries.edit")}
          aria-label={t("eventSeries.edit")}
          onClick={(clickEvent) => {
            clickEvent.stopPropagation();
            onEditEvent(event);
          }}
        >
          <ActionIcon name="edit" />
        </button>
        <span className="event-pick-check" aria-hidden="true">✓</span>
      </div>
    );
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="wide"
      title={t("eventSeries.pickerTitle")}
      description={tag ? t("eventSeries.pickerDescriptionTag", { tag }) : t("eventSeries.pickerDescription")}
    >
      <div className="event-picker">
        {topActions ? <div className="event-picker-top">{topActions}</div> : null}
        <div className="event-picker-toolbar">
          <FilterTabs<Tab>
            value={tab}
            onChange={setTab}
            options={[
              { value: "upcoming", label: t("eventSeries.tabUpcoming") },
              { value: "past", label: t("eventSeries.tabPast") },
              { value: "all", label: t("eventSeries.tabAll") },
            ]}
          />
          <span className="event-picker-spacer" />
          <button type="button" className="button-secondary" onClick={() => void onSelectAllUpcoming()}>
            {t("eventSeries.allUpcoming")}
          </button>
          <button type="button" className="button-ghost" disabled={selectedCount === 0} onClick={() => void onSelectNone()}>
            {t("eventSeries.none")}
          </button>
        </div>

        {loading ? (
          <p className="muted">{tCommon("loading")}</p>
        ) : (
          <div className="event-picker-groups">
            {unknownSelected.length > 0 ? (
              <div className="event-picker-group">
                <div className="candidate-group-heading">
                  <span>{t("alreadyPresentGroup")}</span>
                  <span className="candidate-group-count">{unknownSelected.length}</span>
                </div>
                <div className="event-picker-grid">
                  {unknownSelected.map((item) => (
                    <div
                      key={item.key}
                      role="button"
                      tabIndex={0}
                      aria-pressed
                      className="event-pick-card event-pick-card-checked"
                      onClick={() => void onRemoveUnknown(item.key)}
                      onKeyDown={(keyEvent) => {
                        if (keyEvent.key === "Enter" || keyEvent.key === " ") {
                          keyEvent.preventDefault();
                          void onRemoveUnknown(item.key);
                        }
                      }}
                    >
                      <div className="event-pick-body">
                        <span className="event-pick-title">{item.label}</span>
                      </div>
                      <span className="event-pick-check" aria-hidden="true">✓</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
            {months.map(([month, monthEvents]) => (
              <div key={month} className="event-picker-group">
                <div className="candidate-group-heading">
                  <span>{formatMonthYear(month, locale)}</span>
                  <span className="candidate-group-count">{monthEvents.length}</span>
                </div>
                <div className="event-picker-grid">{monthEvents.map(renderCard)}</div>
              </div>
            ))}
            {months.length === 0 ? <p className="muted">{t("eventSeries.emptyRange")}</p> : null}
            {other.length > 0 ? (
              <div className="event-picker-group">
                <button type="button" className="button-secondary button-ghost event-picker-other-toggle" aria-expanded={showOther} onClick={() => setShowOther((value) => !value)}>
                  {showOther ? t("eventSeries.hideOther") : t("eventSeries.showOther", { count: other.length })}
                </button>
                {showOther ? <div className="event-picker-grid">{other.map(renderCard)}</div> : null}
              </div>
            ) : null}
          </div>
        )}
        <p className="event-picker-result muted">{t("eventSeries.result", { count: selectedCount })}</p>
      </div>
    </Modal>
  );
}
