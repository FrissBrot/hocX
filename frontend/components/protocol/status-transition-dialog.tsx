"use client";

import { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { Modal } from "@/components/ui/modal";

type Props = {
  open: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  /** Namen weiterer Personen, die das Protokoll gerade offen haben */
  otherEditors: string[];
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  /** Zusatz vor den Knöpfen, z. B. Traktanden-Änderungen für die Vorlage */
  children?: ReactNode;
};

/**
 * Rückfrage vor jedem Statuswechsel (Design «Protokoll-Editor 1a»): Folgen des Wechsels und im
 * selben Dialog der Hinweis, wer gerade mitarbeitet - der Wechsel gilt für alle sofort.
 */
export function StatusTransitionDialog({ open, title, message, confirmLabel, otherEditors, busy, onCancel, onConfirm, children }: Props) {
  const t = useTranslations("protocols.editor.transition");
  const tCommon = useTranslations("common");
  return (
    <Modal open={open} title={title} onClose={onCancel}>
      <div className="protocol-transition">
        <p className="protocol-transition-message">{message}</p>
        {otherEditors.length > 0 ? (
          <div className="protocol-transition-others" role="note">
            <strong>{t("othersTitle", { count: otherEditors.length })}</strong>
            <span>{t("othersText", { names: otherEditors.join(", "), count: otherEditors.length })}</span>
          </div>
        ) : null}
        {children}
      </div>
      <div className="modal-actions">
        <button type="button" className="button-ghost" onClick={onCancel}>
          {tCommon("cancel")}
        </button>
        <button type="button" className="button-primary" disabled={busy} onClick={onConfirm}>
          {busy ? "…" : confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
