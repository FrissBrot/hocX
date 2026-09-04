"use client";

import { Modal } from "@/components/ui/modal";

type HistoricalViewBannerProps = {
  cycleConfigName: string;
  cycleYear: number;
  isEdited: boolean;
  editUnlocked: boolean;
  onRequestUnlock: () => void;
};

/** Persistent warning shown while a table overview is displaying a historical
 * snapshot instead of live data - read-only by default, editable only after the user
 * explicitly confirms HistoricalEditConfirmModal below (see useHistoricalSnapshot's
 * editUnlocked). */
export function HistoricalViewBanner({ cycleConfigName, cycleYear, isEdited, editUnlocked, onRequestUnlock }: HistoricalViewBannerProps) {
  return (
    <div className="historical-view-banner">
      <div>
        <strong>Historische Ansicht — {cycleConfigName} {cycleYear}</strong>
        <p className="muted">
          Diese Daten sind eingefroren und schreibgeschützt.
          {isEdited ? " Diese historische Ansicht wurde nachträglich bearbeitet." : ""}
        </p>
      </div>
      {!editUnlocked && (
        <button type="button" className="button-ghost button-inline" onClick={onRequestUnlock}>
          Bearbeitung freischalten
        </button>
      )}
    </div>
  );
}

type HistoricalEditConfirmModalProps = {
  open: boolean;
  onCancel: () => void;
  onConfirm: () => void;
};

/** The explicit warning gate itself - confirming is what flips useHistoricalSnapshot's
 * editUnlocked to true. Nothing on a historical view can be saved or deleted before
 * this has been confirmed once for the current cycle selection. */
export function HistoricalEditConfirmModal({ open, onCancel, onConfirm }: HistoricalEditConfirmModalProps) {
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title="Historische Daten bearbeiten?"
      description="Sie bearbeiten Daten aus einem vergangenen, abgeschlossenen Zyklus. Diese Änderung verändert den historischen Datenstand dauerhaft und wird protokolliert."
    >
      <div className="table-toolbar-actions">
        <button type="button" className="button-inline button-ghost" onClick={onCancel}>
          Abbrechen
        </button>
        <button type="button" className="button-inline button-danger" onClick={onConfirm}>
          Trotzdem bearbeiten
        </button>
      </div>
    </Modal>
  );
}
