"use client";

// Automatisch pro Termin erzeugte Blöcke eines Punkts (repeat_source_type=event) als eine
// Gruppe: Kopf mit Regel, Zeitraum und Zähler, darunter je Termin eine Karte mit Datums-Kachel
// und den Blöcken dieses Termins. Ausgeblendete Termine erscheinen als schmale Zeile mit
// «Einblenden». Ersetzt den früheren roten Rahmen um die automatisch erzeugten Blöcke.

import { ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";

import { ActionIcon } from "@/components/ui/action-icons";
import { Badge } from "@/components/ui/badge";
import { formatDate, formatDateTileParts } from "@/lib/utils/format";
import { EventSummary } from "@/types/api";

export type EventSeriesEntry = {
  key: string;
  event: EventSummary | null;
  // Fallback-Titel, wenn der Termin nicht (mehr) geladen ist (repeat_source_label)
  label: string;
  hidden: boolean;
  content: ReactNode;
};

type Props = {
  entries: EventSeriesEntry[];
  // Tag-Filter der Wiederholung, leer = ohne Tag
  tag: string;
  // Planung («geplant»): Termine wählen und Blöcke entfernen
  canChoose: boolean;
  // Bearbeitbar: Termin bearbeiten, aus-/einblenden
  canEdit: boolean;
  onChoose: () => void;
  onEditEvent: (entry: EventSeriesEntry) => void;
  onHide: (entry: EventSeriesEntry) => void;
  onUnhide: (entry: EventSeriesEntry) => void;
  onRemove: (entry: EventSeriesEntry) => void;
};

export function EventSeriesGroup({ entries, tag, canChoose, canEdit, onChoose, onEditEvent, onHide, onUnhide, onRemove }: Props) {
  const t = useTranslations("protocols");
  const locale = useLocale();
  const dates = entries.map((entry) => entry.event?.event_date).filter((date): date is string => Boolean(date)).sort();
  const range = dates.length === 0 ? "" : dates[0] === dates[dates.length - 1] ? formatDate(dates[0]) : `${formatDate(dates[0])} – ${formatDate(dates[dates.length - 1])}`;
  const visible = entries.filter((entry) => !entry.hidden).length;
  const count = t("eventSeries.count", { visible, total: entries.length });

  return (
    <div className="event-series">
      <div className="event-series-head">
        <span className="event-series-icon" aria-hidden="true">↻</span>
        <div className="event-series-summary">
          <span className="event-series-rule">{tag ? t("eventSeries.ruleTag", { tag }) : t("eventSeries.ruleAny")}</span>
          <span className="event-series-meta">{range ? `${range} · ${count}` : count}</span>
        </div>
        {canChoose ? (
          <button type="button" className="button-secondary" onClick={onChoose}>
            {t("eventSeries.choose")}
          </button>
        ) : null}
      </div>
      <div className="event-series-list">
        {entries.length === 0 ? <div className="event-series-empty">{t("eventSeries.empty")}</div> : null}
        {entries.map((entry) => {
          const event = entry.event;
          const title = event?.title || entry.label;
          if (entry.hidden) {
            return (
              <div key={entry.key} className="event-series-hidden-row">
                <span className="event-series-hidden-date">{event ? formatDate(event.event_date) : ""}</span>
                <span className="event-series-hidden-title">{t("eventSeries.hiddenRow", { title })}</span>
                {canEdit ? (
                  <button type="button" className="button-secondary button-ghost" onClick={() => onUnhide(entry)}>
                    {t("eventSeries.unhide")}
                  </button>
                ) : null}
              </div>
            );
          }
          const tile = formatDateTileParts(event?.event_date, locale);
          const meta = event ? [`${tile.weekday}, ${formatDate(event.event_date)}`, event.location].filter(Boolean).join(" · ") : "";
          return (
            <section key={entry.key} className="event-series-card">
              <div className="event-series-card-head">
                {event ? (
                  <div className="event-series-tile" aria-hidden="true">
                    <span className="event-series-tile-day">{tile.day}</span>
                    <span className="event-series-tile-month">{tile.month}</span>
                  </div>
                ) : null}
                <div className="event-series-card-title">
                  <span className={event?.is_cancelled ? "event-series-title event-series-title-cancelled" : "event-series-title"}>
                    {title}
                    {event?.is_cancelled ? <Badge variant="danger">{t("cancelledLabel")}</Badge> : null}
                  </span>
                  {meta ? <span className="event-series-meta">{meta}</span> : null}
                </div>
                {canEdit ? (
                  <div className="event-series-actions">
                    {event ? (
                      <button type="button" className="button-icon-soft" title={t("eventSeries.edit")} aria-label={t("eventSeries.edit")} onClick={() => onEditEvent(entry)}>
                        <ActionIcon name="edit" />
                      </button>
                    ) : null}
                    <button type="button" className="button-icon-soft" title={t("eventSeries.hide")} aria-label={t("eventSeries.hide")} onClick={() => onHide(entry)}>
                      <ActionIcon name="hide" />
                    </button>
                    {canChoose ? (
                      <button type="button" className="button-icon-soft button-icon-soft-danger" title={t("eventSeries.remove")} aria-label={t("eventSeries.remove")} onClick={() => onRemove(entry)}>
                        <ActionIcon name="close" />
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </div>
              <div className="event-series-card-body">{entry.content}</div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
