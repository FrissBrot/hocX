"use client";

import { useEffect } from "react";
import { NavIcon } from "@/components/ui/nav-icons";
import { CollaboratorAvatar } from "@/components/protocol/collaboration-presence";
import type { CollaboratorInfo } from "@/lib/hooks/use-protocol-collaboration";
import type { AttendanceTally } from "@/components/protocol/protocol-editor-shared";

type CollaborationStatusPanelProps = {
  open: boolean;
  onClose: () => void;
  protocolNumber: string;
  modeLabel: string;
  attendanceTally: AttendanceTally | null;
  otherPresence: CollaboratorInfo[];
  connected: boolean;
  ctaLabel?: string;
  onCta?: () => void;
  ctaBusy?: boolean;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
};

export function CollaborationStatusPanel({
  open,
  onClose,
  protocolNumber,
  modeLabel,
  attendanceTally,
  otherPresence,
  connected,
  ctaLabel,
  onCta,
  ctaBusy,
  onMouseEnter,
  onMouseLeave,
}: CollaborationStatusPanelProps) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open, onClose]);

  return (
      <div
        className={`quick-flyout${open ? " quick-flyout-open" : ""}`}
        role="dialog"
        aria-hidden={!open}
        aria-label="Status & Zusammenarbeit"
        onMouseEnter={onMouseEnter}
        onMouseLeave={onMouseLeave}
      >
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
                <span>Unent<wbr />schuldigt</span>
              </div>
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
  );
}
