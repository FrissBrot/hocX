"use client";

import { createPortal } from "react-dom";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { NavIcon } from "@/components/ui/nav-icons";
import { CollaboratorAvatar } from "@/components/protocol/collaboration-presence";
import { ATTENDANCE_OPTIONS } from "@/components/protocol/protocol-editor-shared";
import type { CollaboratorInfo } from "@/lib/hooks/use-protocol-collaboration";
import type { AttendanceTally } from "@/components/protocol/protocol-editor-shared";

export type AttendanceRosterEntry = { id: number; name: string; status: string | null };

type CollaborationStatusPanelProps = {
  open: boolean;
  onClose: () => void;
  protocolNumber: string;
  modeLabel: string;
  attendanceTally: AttendanceTally | null;
  attendanceRoster: AttendanceRosterEntry[];
  otherPresence: CollaboratorInfo[];
  connected: boolean;
  ctaLabel?: string;
  onCta?: () => void;
  ctaBusy?: boolean;
};

const STATUS_BADGE_VARIANT: Record<string, "success" | "neutral" | "danger" | "warning"> = {
  present: "success",
  late: "warning",
  excused: "neutral",
  absent: "danger",
};

function statusLabel(status: string | null): string {
  if (!status) return "Offen";
  return ATTENDANCE_OPTIONS.find((option) => option.value === status)?.label ?? status;
}

export function CollaborationStatusPanel({
  open,
  onClose,
  protocolNumber,
  modeLabel,
  attendanceTally,
  attendanceRoster,
  otherPresence,
  connected,
  ctaLabel,
  onCta,
  ctaBusy,
}: CollaborationStatusPanelProps) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open || !mounted) return null;

  return createPortal(
    <>
      <div className="collab-status-backdrop" onClick={onClose} role="presentation" />
      <div className="quick-flyout quick-flyout-open" role="dialog" aria-modal="true" aria-label="Status & Zusammenarbeit">
        <div className="quick-flyout-header">
          <div className="quick-flyout-title">
            <span className="quick-flyout-title-icon"><NavIcon name="activity" /></span>
            <span className="eyebrow">Status &amp; Zusammenarbeit</span>
          </div>
          <button type="button" className="button-ghost quick-flyout-close" onClick={onClose} aria-label="Schliessen">
            ✕
          </button>
        </div>

        <div className="collab-status-chips">
          <span className="pill">{protocolNumber}</span>
          <span className="pill">{modeLabel}</span>
        </div>

        {attendanceTally && (
          <>
            <div className="eyebrow collab-status-section-label">Teilnehmer</div>
            <div className="collab-status-tiles">
              <div className="collab-status-tile collab-status-tile-success">
                <strong>{attendanceTally.present}</strong>
                <span>Anwesend</span>
              </div>
              <div className="collab-status-tile collab-status-tile-neutral">
                <strong>{attendanceTally.excused}</strong>
                <span>Entschuldigt</span>
              </div>
              <div className="collab-status-tile collab-status-tile-danger">
                <strong>{attendanceTally.absent}</strong>
                <span>Unentschuldigt</span>
              </div>
            </div>

            <div className="collab-status-roster">
              {attendanceRoster.map((entry) => (
                <div className="collab-status-roster-row" key={entry.id}>
                  <span className="collab-status-roster-avatar">{entry.name.trim().charAt(0)}</span>
                  <span className="collab-status-roster-name">{entry.name}</span>
                  <Badge variant={entry.status ? STATUS_BADGE_VARIANT[entry.status] ?? "neutral" : "neutral"}>
                    {statusLabel(entry.status)}
                  </Badge>
                </div>
              ))}
            </div>
          </>
        )}

        <div className="eyebrow collab-status-section-label">Gerade aktiv</div>
        {otherPresence.length > 0 ? (
          <div className="collab-status-active">
            <div className="collab-status-active-avatars">
              {otherPresence.map((user) => (
                <CollaboratorAvatar key={user.user_id} user={user} />
              ))}
            </div>
            <span className="muted">bearbeiten live mit</span>
          </div>
        ) : (
          <p className="muted collab-status-active-empty">
            {connected ? "Niemand sonst bearbeitet gerade live." : "Live-Kollaboration nicht verfügbar."}
          </p>
        )}

        {ctaLabel && onCta && (
          <button type="button" className="button-primary collab-status-cta" disabled={ctaBusy} onClick={onCta}>
            {ctaBusy ? "…" : ctaLabel}
          </button>
        )}

        <div className="eyebrow collab-status-section-label">Tastenkürzel</div>
        <div className="collab-status-shortcuts">
          <div className="collab-status-shortcut-row"><kbd>⌃⌥N</kbd><span>Sitzungsnotizen öffnen</span></div>
          <div className="collab-status-shortcut-row"><kbd>⌃⌥T</kbd><span>Schnelles Todo öffnen</span></div>
          <div className="collab-status-shortcut-row"><kbd>⌃⏎</kbd><span>Nächster Abschnitt</span></div>
          <div className="collab-status-shortcut-row"><kbd>⌃⇧⏎</kbd><span>Vorheriger Abschnitt</span></div>
        </div>
      </div>
    </>,
    document.body
  );
}
