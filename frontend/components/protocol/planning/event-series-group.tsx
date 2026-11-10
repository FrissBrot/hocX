"use client";

// Automatisch pro Termin erzeugte Blöcke eines Punkts (repeat_source_type=event) als eine
// Gruppe: Kopf mit Regel, Zeitraum und Zähler, darunter je Termin eine Karte mit Datums-Kachel
// und den Blöcken dieses Termins. Pro Termin: Vertagen (Blöcke löschen, im nächsten Protokoll
// wieder erzeugt) oder Entfernen (in Folgeprotokollen dieses Punkts nie mehr erzeugt). Entfernte
// Termine erscheinen hier nicht mehr; über «Termine wählen» lassen sie sich wieder anhaken.

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
  content: ReactNode;
};

type Props = {
  entries: EventSeriesEntry[];
  // Tag-Filter der Wiederholung, leer = ohne Tag
  tag: string;
  // Planung («geplant»): Termine wählen
  canChoose: boolean;
  // Bearbeitbar: Termin bearbeiten, vertagen, entfernen
  canEdit: boolean;
  onChoose: () => void;
  onEditEvent: (entry: EventSeriesEntry) => void;
  onPostpone: (entry: EventSeriesEntry) => void;
  onRemove: (entry: EventSeriesEntry) => void;
};

export function EventSeriesGroup({ entries, tag, canChoose, canEdit, onChoose, onEditEvent, onPostpone, onRemove }: Props) {
  const t = useTranslations("protocols");
  const locale = useLocale();
  const dates = entries.map((entry) => entry.event?.event_date).filter((date): date is string => Boolean(date)).sort();
  const range = dates.length === 0 ? "" : dates[0] === dates[dates.length - 1] ? formatDate(dates[0]) : `${formatDate(dates[0])} – ${formatDate(dates[dates.length - 1])}`;
  const count = t("eventSeries.count", { count: entries.length });

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
                    <button type="button" className="button-icon-soft" title={t("eventSeries.postpone")} aria-label={t("eventSeries.postpone")} onClick={() => onPostpone(entry)}>
                      <ActionIcon name="postpone" />
                    </button>
                    <button type="button" className="button-icon-soft button-icon-soft-danger" title={t("eventSeries.remove")} aria-label={t("eventSeries.remove")} onClick={() => onRemove(entry)}>
                      <ActionIcon name="close" />
                    </button>
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
