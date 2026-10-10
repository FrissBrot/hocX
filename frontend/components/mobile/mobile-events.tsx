"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { CalendarLinkHint } from "@/components/connections/calendar-link-hint";
import { useAllEvents, useParticipants, useProtocolsByEvent } from "@/components/mobile/mobile-data";
import { EventDetailSheet, EventFormSheet } from "@/components/mobile/mobile-event-sheets";
import { MobileIcon } from "@/components/mobile/mobile-icons";
import { MobileChip, MobileChipRow, MobileDateTile, MobileEmpty, MobileFab, MobilePageHeader, MobileSegmented, MobileTagPill } from "@/components/mobile/mobile-ui";
import { dateParts, tagColor, todayIso } from "@/components/mobile/mobile-utils";
import { effectiveEndDate } from "@/components/events/event-utils";
import { useCycleOptions } from "@/lib/hooks/use-cycle-options";
import { TagConfig, useTagConfig } from "@/lib/hooks/use-tag-config";
import type { EventSummary, ParticipantSummary } from "@/types/api";

type Period = "upcoming" | "all" | "past";

export function MobileEventRow({
  event,
  tagConfig,
  tile,
  showTodayLine = false,
  onOpen,
}: {
  event: EventSummary;
  tagConfig: TagConfig;
  tile: "month" | "weekday";
  showTodayLine?: boolean;
  onOpen: () => void;
}) {
  const t = useTranslations("mobile");
  const locale = useLocale();
  const past = effectiveEndDate(event).slice(0, 10) < todayIso();
  const color = event.tag ? tagColor(event.tag, tagConfig) : "";
  const range =
    event.event_end_date && event.event_end_date > event.event_date
      ? `${dateParts.dayMonth(event.event_date, locale)} – ${dateParts.dayMonth(event.event_end_date, locale)}`
      : null;
  const meta = [range, event.location].filter(Boolean).join(" · ");

  return (
    <>
      {showTodayLine ? (
        <div className="mobile-today-line">
          <span className="mobile-today-line-dot" />
          <span className="mobile-today-line-label">{t("events.todayLine", { date: dateParts.dayMonth(todayIso(), locale) })}</span>
          <span className="mobile-today-line-rule" />
        </div>
      ) : null}
      <button type="button" className="mobile-event-row" onClick={onOpen}>
        <MobileDateTile iso={event.event_date} color={color} muted={past || event.is_cancelled || !event.tag} top={tile} />
        <span className="mobile-event-row-text">
          <span className={`mobile-event-row-title${event.is_cancelled ? " mobile-text-struck mobile-muted" : ""}`}>{event.title}</span>
          <span className="mobile-event-row-meta">
            {event.is_cancelled ? (
              <MobileTagPill label={t("events.cancelled")} color="" cancelled />
            ) : event.tag ? (
              <MobileTagPill label={event.tag} color={color} />
            ) : null}
            {meta ? <span className="mobile-ellipsis">{meta}</span> : null}
          </span>
        </span>
        <span className="mobile-event-row-count" aria-label={t("events.participantCount")}>
          <MobileIcon name="people" size={14} />
          {event.participant_count || "—"}
        </span>
      </button>
    </>
  );
}

export function MobileEvents({
  initialEvents,
  participants: initialParticipants,
}: {
  initialEvents: EventSummary[];
  participants: ParticipantSummary[];
}) {
  const t = useTranslations("mobile");
  const locale = useLocale();
  const searchParams = useSearchParams();
  const { tagConfig } = useTagConfig();
  const { options: cycleOptions } = useCycleOptions();
  const [events, setEvents] = useAllEvents(initialEvents);
  const participants = useParticipants(true, initialParticipants);
  const protocolsByEvent = useProtocolsByEvent(true);
  const [period, setPeriod] = useState<Period>("upcoming");
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>(searchParams.get("event"));
  // `null` = geschlossen, "new" = neuer Termin, sonst ID des bearbeiteten Termins.
  const [formFor, setFormFor] = useState<string | null>(null);

  const tags = useMemo(
    () => [...new Set([...events.map((event) => event.tag).filter((tag): tag is string => !!tag), ...Object.keys(tagConfig)])].sort((a, b) => a.localeCompare(b)),
    [events, tagConfig]
  );

  const groups = useMemo(() => {
    const today = todayIso();
    const needle = query.trim().toLowerCase();
    const filtered = events.filter((event) => {
      const past = effectiveEndDate(event).slice(0, 10) < today;
      if (period === "upcoming" && past) return false;
      if (period === "past" && !past) return false;
      if (tagFilter && event.tag !== tagFilter) return false;
      return !needle || `${event.title} ${event.location ?? ""}`.toLowerCase().includes(needle);
    });
    filtered.sort((a, b) => a.event_date.localeCompare(b.event_date) * (period === "past" ? -1 : 1));
    const result: { key: string; label: string; items: { event: EventSummary; todayLine: boolean }[] }[] = [];
    let todayPlaced = false;
    filtered.forEach((event) => {
      const key = event.event_date.slice(0, 7);
      let group = result[result.length - 1];
      if (!group || group.key !== key) {
        group = { key, label: dateParts.monthYear(event.event_date, locale), items: [] };
        result.push(group);
      }
      const todayLine = period === "all" && !todayPlaced && effectiveEndDate(event).slice(0, 10) >= today;
      if (todayLine) todayPlaced = true;
      group.items.push({ event, todayLine });
    });
    return result;
  }, [events, period, tagFilter, query, locale]);

  const openEvent = events.find((event) => event.id === openId) ?? null;
  const formEvent = formFor && formFor !== "new" ? events.find((event) => event.id === formFor) ?? null : null;

  return (
    <div className="mobile-page mobile-page-list">
      <MobilePageHeader
        title={t("tabs.events")}
        searchOpen={searchOpen}
        onToggleSearch={() => {
          setSearchOpen((open) => !open);
          setQuery("");
        }}
        searchValue={query}
        onSearchChange={setQuery}
        searchPlaceholder={t("events.searchPlaceholder")}
      />
      <div className="mobile-page-inset">
        <CalendarLinkHint kind="events" mobile />
        <MobileSegmented<Period>
          ariaLabel={t("events.period")}
          value={period}
          onChange={setPeriod}
          options={[
            { value: "upcoming", label: t("events.upcoming") },
            { value: "all", label: t("common.all") },
            { value: "past", label: t("events.past") },
          ]}
        />
      </div>
      {tags.length > 0 ? (
        <MobileChipRow>
          <MobileChip active={tagFilter === null} onClick={() => setTagFilter(null)}>
            {t("common.all")}
          </MobileChip>
          {tags.map((tag) => (
            <MobileChip key={tag} active={tagFilter === tag} dotColor={tagColor(tag, tagConfig)} onClick={() => setTagFilter((current) => (current === tag ? null : tag))}>
              {tag}
            </MobileChip>
          ))}
        </MobileChipRow>
      ) : null}

      {groups.map((group) => (
        <section key={group.key} className="mobile-list-group">
          <div className="mobile-list-group-header mobile-list-group-header-sticky">
            <span className="mobile-list-group-title">{group.label}</span>
            <span className="mobile-muted-sm">{t("events.count", { count: group.items.length })}</span>
          </div>
          <div className="mobile-card mobile-list-card">
            {group.items.map(({ event, todayLine }) => (
              <MobileEventRow key={event.id} event={event} tagConfig={tagConfig} tile="weekday" showTodayLine={todayLine} onOpen={() => setOpenId(event.id)} />
            ))}
          </div>
        </section>
      ))}
      {groups.length === 0 ? <MobileEmpty title={t("events.emptyTitle")} hint={t("events.emptyHint")} /> : null}

      <MobileFab label={t("events.fab")} onClick={() => setFormFor("new")} />

      {openEvent && !formFor ? (
        <EventDetailSheet
          event={openEvent}
          canEdit
          protocol={protocolsByEvent.get(openEvent.id) ?? null}
          participants={participants}
          cycleOptions={cycleOptions}
          tagConfig={tagConfig}
          onClose={() => setOpenId(null)}
          onEdit={() => setFormFor(openEvent.id)}
          onChange={(next) => setEvents((list) => list.map((item) => (item.id === next.id ? next : item)))}
          onDeleted={(id) => setEvents((list) => list.filter((item) => item.id !== id))}
        />
      ) : null}
      {formFor ? (
        <EventFormSheet
          event={formEvent}
          tags={tags}
          tagConfig={tagConfig}
          onClose={() => setFormFor(null)}
          onSaved={(saved, created) => {
            setEvents((list) => (created ? [saved, ...list] : list.map((item) => (item.id === saved.id ? saved : item))));
            setFormFor(null);
            setOpenId(saved.id);
            if (created) setPeriod("all");
          }}
        />
      ) : null}
    </div>
  );
}
