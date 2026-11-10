"use client";

import { useTranslations } from "next-intl";

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
  const t = useTranslations("protocols.historicalBanner");
  return (
    <div className="historical-view-banner">
      <div>
        <strong>{t("title", { name: cycleConfigName, year: cycleYear })}</strong>
        <p className="muted">
          {t("frozenNotice")}
          {isEdited ? t("editedNotice") : ""}
        </p>
      </div>
      {!editUnlocked && (
        <button type="button" className="button-ghost button-secondary" onClick={onRequestUnlock}>
          {t("unlockEdit")}
        </button>
      )}
    </div>
  );
}

type ReconstructionBannerProps = {
  cycleConfigName: string;
  cycleYear: number;
  source: { kind: "live" | "snapshot"; cycleYear: number | null } | null;
  isConfirming: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

/** Shown while reconstructing a genuine snapshot gap (a real, ended period with no
 * snapshot yet - see TableSnapshotCycleSummary.has_snapshot) for the selected list. The
 * table is directly editable here (not gated behind an unlock step like
 * HistoricalViewBanner) since nothing has been frozen yet - it's a fresh draft,
 * pre-filled from the nearest available source, until "Bestätigen" writes it. */
export function ReconstructionBanner({ cycleConfigName, cycleYear, source, isConfirming, onConfirm, onCancel }: ReconstructionBannerProps) {
  const t = useTranslations("protocols.historicalBanner");
  const sourceLabel = source ? (source.kind === "live" ? t("sourceLive") : t("sourceCycle", { year: source.cycleYear ?? "" })) : "…";
  return (
    <div className="historical-view-banner">
      <div>
        <strong>{t("missingSnapshotTitle", { name: cycleConfigName, year: cycleYear })}</strong>
        <p className="muted">
          {t("missingSnapshotBody", { source: sourceLabel })}
        </p>
      </div>
      <div className="table-toolbar-actions">
        <button type="button" className="button-ghost button-secondary" onClick={onCancel}>
          {t("cancel")}
        </button>
        <button type="button" className="button-secondary" onClick={onConfirm} disabled={isConfirming}>
          {isConfirming ? "…" : t("confirm")}
        </button>
      </div>
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
  const t = useTranslations("protocols.historicalBanner");
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={t("editConfirmTitle")}
      description={t("editConfirmDescription")}
    >
      <div className="table-toolbar-actions">
        <button type="button" className="button-secondary button-ghost" onClick={onCancel}>
          {t("cancel")}
        </button>
        <button type="button" className="button-secondary button-danger" onClick={onConfirm}>
          {t("editAnyway")}
        </button>
      </div>
    </Modal>
  );
}
