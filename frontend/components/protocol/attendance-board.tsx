"use client";

// Anwesenheitskontrolle im Protokoll-Editor (Design «Protokoll-Editor v2», ohne Gruppen):
// Statusbalken, Zähl-Kacheln als Filter, Personensuche und je Person eine Karte. Ein Klick
// schaltet den Status eine Stufe weiter (offen → anwesend → … → unentschuldigt → anwesend),
// langes Drücken oder Rechtsklick öffnet das Statusmenü. Tastatur: Person fokussiert (Tab),
// unter der Maus oder ihr Menü offen + 1–4 setzt den Status direkt; Enter in der Suche öffnet
// bei genau einem Treffer dessen Menü, Escape leert die Suche.
// Strg+F fokussiert die Suche, solange der Punkt aktiv ist (protocol-editor.tsx).

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { HelpPopover } from "@/components/ui/help-popover";
import { Menu, MenuItem, Popover } from "@/components/ui/popover";
import { SearchInput } from "@/components/ui/search-input";
import { useShortcut } from "@/lib/keyboard/use-shortcut";
import { ParticipantSummary } from "@/types/api";

export const ATTENDANCE_STATUSES = ["present", "late", "excused", "absent"] as const;
export type AttendanceStatus = (typeof ATTENDANCE_STATUSES)[number];
type StatusOrOpen = AttendanceStatus | "open";
type Filter = "all" | StatusOrOpen;

/** Markiert das Suchfeld, damit Strg+F es im aktiven Punkt findet. */
export const ATTENDANCE_SEARCH_ATTR = "data-attendance-search";

type Props = {
  participants: ParticipantSummary[];
  /** Status je Teilnehmer-ID; fehlt = noch nicht erfasst («offen») */
  statusById: Map<string, string>;
  editable: boolean;
  /** Offene Busse je Teilnehmer-ID (Betrag), nur wenn Bussen konfiguriert sind */
  fineAmountById: Map<string, number>;
  /** Vereinswährung (Mandanten-Einstellungen); leer = Betrag ohne Währung. */
  fineCurrency?: string;
  onChange: (participant: ParticipantSummary, status: AttendanceStatus) => Promise<void> | void;
  onMarkOpenPresent: (participants: ParticipantSummary[]) => Promise<void> | void;
};

/** Dauer, ab der ein Drücken als «lang» gilt und das Menü statt des Weiterschaltens öffnet. */
const LONG_PRESS_MS = 450;

/** Nächster Status beim Klick: offen beginnt bei «anwesend», nach dem letzten wieder von vorn. */
export function nextAttendanceStatus(status: AttendanceStatus | "open"): AttendanceStatus {
  const index = status === "open" ? -1 : ATTENDANCE_STATUSES.indexOf(status);
  return ATTENDANCE_STATUSES[(index + 1) % ATTENDANCE_STATUSES.length];
}

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function AttendanceBoard({ participants, statusById, editable, fineAmountById, fineCurrency = "", onChange, onMarkOpenPresent }: Props) {
  const t = useTranslations("protocols.attendanceBoard");
  const tStatus = useTranslations("protocols.attendance");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [menuFor, setMenuFor] = useState<string | null>(null);
  // Zuletzt per Maus oder Tab angesteuerte Person, Ziel der Zifferntasten
  const targetRef = useRef<string | null>(null);
  const longPressTimerRef = useRef<number | undefined>(undefined);
  const longPressedRef = useRef(false);
  const cardRefs = useRef(new Map<string, HTMLButtonElement>());
  const menuAnchorRef = useRef<HTMLButtonElement | null>(null);

  const statusOf = (participantId: string): StatusOrOpen => {
    const status = statusById.get(participantId);
    return status && (ATTENDANCE_STATUSES as readonly string[]).includes(status) ? (status as AttendanceStatus) : "open";
  };

  const counts: Record<StatusOrOpen, number> = { open: 0, present: 0, late: 0, excused: 0, absent: 0 };
  for (const participant of participants) counts[statusOf(participant.id)] += 1;

  const needle = query.trim().toLowerCase();
  const visible = participants.filter(
    (participant) =>
      (!needle || participant.display_name.toLowerCase().includes(needle)) && (filter === "all" || statusOf(participant.id) === filter)
  );
  const total = participants.length;
  const deviations = counts.late + counts.excused + counts.absent;

  // Hover/Fokus auf einer Karte + 1–4 setzt den Status (Registry `protocol.attendanceStatus`;
  // nicht beim Tippen, nicht in fremden Dialogen). Im offenen Statusmenü übernimmt das Menü selbst
  // die Ziffern (onKeyDown unten), weil Tasten in Menüs dem Menü gehören.
  function setStatusByDigit(participantId: string | null, key: string) {
    const participant = participantId ? participants.find((p) => p.id === participantId) : null;
    if (!participant) return false;
    setMenuFor(null);
    void onChange(participant, ATTENDANCE_STATUSES[Number(key) - 1]);
    return true;
  }
  useShortcut("protocol.attendanceStatus", (event) => (setStatusByDigit(targetRef.current, event.key) ? undefined : false), { enabled: editable });

  useEffect(() => () => window.clearTimeout(longPressTimerRef.current), []);

  function openMenu(participantId: string) {
    menuAnchorRef.current = cardRefs.current.get(participantId) ?? null;
    setMenuFor(participantId);
  }

  function cancelLongPress() {
    window.clearTimeout(longPressTimerRef.current);
  }

  const filters: { value: Filter; count: number }[] = [
    { value: "all", count: total },
    ...(counts.open > 0 ? [{ value: "open" as const, count: counts.open }] : []),
    ...ATTENDANCE_STATUSES.map((status) => ({ value: status, count: counts[status] })),
  ];
  const filterLabel = (value: Filter) => (value === "all" ? t("filterAll") : value === "open" ? t("statusOpen") : tStatus(value));
  const menuParticipant = menuFor ? participants.find((p) => p.id === menuFor) ?? null : null;

  return (
    <div className="attendance-board">
      <div className="attendance-board-head">
        <span className="attendance-board-meta">
          {t("summary", { total, deviations })}
          {counts.open > 0 ? ` · ${t("openCount", { count: counts.open })}` : ""}
          {" "}
          <HelpPopover topic={t("helpTopic")} docs={{ page: "protokolle", anchor: "sitzung" }}>{t("help")}</HelpPopover>
        </span>
        {editable && counts.open > 0 ? (
          <button type="button" className="button-secondary" onClick={() => void onMarkOpenPresent(participants.filter((p) => statusOf(p.id) === "open"))}>
            {t("markOpenPresent")}
          </button>
        ) : null}
      </div>

      <div className="attendance-board-bar" aria-hidden="true">
        {(["present", "late", "excused", "absent"] as const).map((status) =>
          counts[status] > 0 ? (
            <span key={status} className={`attendance-board-bar-part attendance-status-${status}`} style={{ width: `${(counts[status] / Math.max(total, 1)) * 100}%` }} />
          ) : null
        )}
      </div>

      <div className="attendance-board-filters" role="group" aria-label={t("filterLabel")}>
        {filters.map(({ value, count }) => {
          const active = filter === value;
          return (
            <button
              key={value}
              type="button"
              aria-pressed={active}
              className={`attendance-board-filter attendance-status-${value}${active ? " attendance-board-filter-active" : ""}`}
              onClick={() => setFilter(active && value !== "all" ? "all" : value)}
            >
              <span className="attendance-board-filter-label">
                <span className="attendance-board-dot" aria-hidden="true" />
                {filterLabel(value)}
              </span>
              <span className="attendance-board-filter-count">{count}</span>
            </button>
          );
        })}
      </div>

      <div className="attendance-board-search">
        <SearchInput
          value={query}
          onChange={setQuery}
          placeholder={t("searchPlaceholder")}
          aria-label={t("searchPlaceholder")}
          {...{ [ATTENDANCE_SEARCH_ATTR]: "" }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && visible.length === 1 && editable) {
              event.preventDefault();
              openMenu(visible[0].id);
            } else if (event.key === "Escape" && query) {
              event.preventDefault();
              event.stopPropagation();
              setQuery("");
            }
          }}
        />
        {editable ? <span className="attendance-board-hint">{t.rich("keyHint", { key: (chunks) => <kbd>{chunks}</kbd> })}</span> : null}
      </div>

      {visible.length === 0 ? (
        <div className="attendance-board-empty">{needle ? t("emptySearch", { query: query.trim() }) : t("emptyFilter")}</div>
      ) : (
        <div className="attendance-board-grid">
          {visible.map((participant) => {
            const status = statusOf(participant.id);
            const statusLabel = status === "open" ? t("statusOpen") : tStatus(status);
            const fineAmount = fineAmountById.get(participant.id);
            return (
              <button
                key={participant.id}
                ref={(node) => {
                  if (node) cardRefs.current.set(participant.id, node);
                  else cardRefs.current.delete(participant.id);
                }}
                type="button"
                className={`attendance-card attendance-status-${status}${menuFor === participant.id ? " attendance-card-open" : ""}`}
                disabled={!editable}
                aria-haspopup="menu"
                aria-expanded={menuFor === participant.id}
                title={`${participant.display_name} · ${statusLabel}`}
                onPointerDown={(event) => {
                  if (event.button !== 0) return;
                  longPressedRef.current = false;
                  cancelLongPress();
                  longPressTimerRef.current = window.setTimeout(() => {
                    longPressedRef.current = true;
                    openMenu(participant.id);
                  }, LONG_PRESS_MS);
                }}
                onPointerUp={cancelLongPress}
                onPointerCancel={cancelLongPress}
                onClick={() => {
                  // Nach langem Drücken ist das Menü schon offen, der Klick schaltet nicht weiter
                  if (longPressedRef.current) {
                    longPressedRef.current = false;
                    return;
                  }
                  void onChange(participant, nextAttendanceStatus(status));
                }}
                onContextMenu={(event) => {
                  event.preventDefault();
                  cancelLongPress();
                  openMenu(participant.id);
                }}
                onMouseEnter={() => {
                  targetRef.current = participant.id;
                }}
                onMouseLeave={() => {
                  cancelLongPress();
                  if (targetRef.current === participant.id && document.activeElement !== cardRefs.current.get(participant.id)) targetRef.current = null;
                }}
                onFocus={() => {
                  targetRef.current = participant.id;
                }}
                onBlur={() => {
                  if (targetRef.current === participant.id) targetRef.current = null;
                }}
              >
                <span className="attendance-card-avatar" aria-hidden="true">{initials(participant.display_name)}</span>
                <span className="attendance-card-text">
                  <span className="attendance-card-name">{participant.display_name}</span>
                  <span className="attendance-card-status">{statusLabel}</span>
                </span>
                {fineAmount != null ? (
                  <span className="attendance-card-fine" title={t("fineTitle")}>
                    {fineCurrency ? t("fine", { amount: fineAmount, currency: fineCurrency }) : t("fineAmount", { amount: fineAmount })}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
      )}

      <Popover open={Boolean(menuParticipant)} onOpenChange={(open) => !open && setMenuFor(null)} anchorRef={menuAnchorRef}>
        {menuParticipant ? (
          <div
            onKeyDown={(event) => {
              if (/^[1-4]$/.test(event.key) && !event.ctrlKey && !event.metaKey && !event.altKey && setStatusByDigit(menuParticipant.id, event.key)) {
                event.preventDefault();
              }
            }}
          >
          <Menu>
            {ATTENDANCE_STATUSES.map((status, index) => (
              <MenuItem
                key={status}
                selected={statusOf(menuParticipant.id) === status}
                icon={<span className={`attendance-board-dot attendance-status-${status}`} />}
                onSelect={() => {
                  setMenuFor(null);
                  void onChange(menuParticipant, status);
                }}
              >
                <span className="attendance-menu-label">
                  {tStatus(status)}
                  <span className="dropdown-hint">{index + 1}</span>
                </span>
              </MenuItem>
            ))}
          </Menu>
          </div>
        ) : null}
      </Popover>
    </div>
  );
}
