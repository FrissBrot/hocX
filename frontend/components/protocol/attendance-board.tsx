"use client";

// Anwesenheitskontrolle im Protokoll-Editor (Design «Protokoll-Editor v2», ohne Gruppen):
// Statusbalken, Zähl-Kacheln als Filter, Personensuche und je Person eine Karte, die ein
// Statusmenü öffnet. Tastatur: Über eine Person fahren (oder ihr Menü offen) + 1–4 setzt den
// Status; Enter in der Suche öffnet bei genau einem Treffer dessen Menü, Escape leert die Suche.
// Strg+F fokussiert die Suche, solange der Punkt aktiv ist (protocol-editor.tsx).

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { Menu, MenuItem, Popover } from "@/components/ui/popover";
import { SearchInput } from "@/components/ui/search-input";
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
  onChange: (participant: ParticipantSummary, status: AttendanceStatus) => Promise<void> | void;
  onMarkOpenPresent: (participants: ParticipantSummary[]) => Promise<void> | void;
};

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function isFormField(target: EventTarget | null) {
  const el = target as HTMLElement | null;
  return Boolean(el && (["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || el.isContentEditable));
}

export function AttendanceBoard({ participants, statusById, editable, fineAmountById, onChange, onMarkOpenPresent }: Props) {
  const t = useTranslations("protocols.attendanceBoard");
  const tStatus = useTranslations("protocols.attendance");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const hoveredRef = useRef<string | null>(null);
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

  // Hover/Menü + 1–4 setzt den Status (nicht beim Tippen in einem Feld)
  useEffect(() => {
    if (!editable) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.ctrlKey || event.metaKey || event.altKey || !/^[1-4]$/.test(event.key) || isFormField(event.target)) return;
      const id = menuFor ?? hoveredRef.current;
      const participant = id ? participants.find((p) => p.id === id) : null;
      if (!participant) return;
      event.preventDefault();
      setMenuFor(null);
      void onChange(participant, ATTENDANCE_STATUSES[Number(event.key) - 1]);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [editable, menuFor, participants, onChange]);

  function openMenu(participantId: string) {
    menuAnchorRef.current = cardRefs.current.get(participantId) ?? null;
    setMenuFor((current) => (current === participantId ? null : participantId));
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
                onClick={() => openMenu(participant.id)}
                onMouseEnter={() => {
                  hoveredRef.current = participant.id;
                }}
                onMouseLeave={() => {
                  if (hoveredRef.current === participant.id) hoveredRef.current = null;
                }}
              >
                <span className="attendance-card-avatar" aria-hidden="true">{initials(participant.display_name)}</span>
                <span className="attendance-card-text">
                  <span className="attendance-card-name">{participant.display_name}</span>
                  <span className="attendance-card-status">{statusLabel}</span>
                </span>
                {fineAmount != null ? (
                  <span className="attendance-card-fine" title={t("fineTitle")}>
                    {t("fine", { amount: fineAmount })}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
      )}

      <Popover open={Boolean(menuParticipant)} onOpenChange={(open) => !open && setMenuFor(null)} anchorRef={menuAnchorRef}>
        {menuParticipant ? (
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
        ) : null}
      </Popover>
    </div>
  );
}
