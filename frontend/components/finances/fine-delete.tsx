"use client";

import { FormEvent, ReactNode, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import type { AttendanceFine } from "@/types/api";

type DeletableFine = Pick<AttendanceFine, "id" | "participant_name_snapshot" | "delete_requires_reason">;
export type FineDeleteOutcome = "hard" | "soft" | null;

/**
 * Löschen einer offenen Busse (MAIN-BE-002). Im noch offenen Ursprungsprotokoll wird hart
 * gelöscht (Rückfrage), bei einer mitgeführten Busse aus einem abgeschlossenen Protokoll ist
 * eine Begründung Pflicht: die Busse bleibt als «gelöscht» im Protokoll `protocolId` (sonst im
 * nächsten offenen) sichtbar. Liefert, was passiert ist, damit der Aufrufer seine Liste anpasst.
 */
export function useFineDelete(protocolId?: string): {
  requestDelete: (fine: DeletableFine) => Promise<FineDeleteOutcome>;
  dialog: ReactNode;
} {
  const t = useTranslations("finances");
  const tCommon = useTranslations("common");
  const confirm = useConfirm();
  const showToast = useToast();
  const [target, setTarget] = useState<DeletableFine | null>(null);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const resolveRef = useRef<((outcome: FineDeleteOutcome) => void) | null>(null);

  function finish(outcome: FineDeleteOutcome) {
    resolveRef.current?.(outcome);
    resolveRef.current = null;
    setTarget(null);
    setReason("");
  }

  async function requestDelete(fine: DeletableFine): Promise<FineDeleteOutcome> {
    if (!fine.delete_requires_reason) {
      const ok = await confirm({
        message: t("deleteFineConfirm", { name: fine.participant_name_snapshot }),
        tone: "danger",
        confirmLabel: tCommon("delete"),
      });
      if (!ok) return null;
      try {
        await browserApiFetch(`/api/fines/${fine.id}`, { method: "DELETE" });
        return "hard";
      } catch (error) {
        showToast(error instanceof Error ? error.message : t("deleteFineFailed"), "error");
        return null;
      }
    }
    resolveRef.current?.(null);
    return new Promise<FineDeleteOutcome>((resolve) => {
      resolveRef.current = resolve;
      setReason("");
      setTarget(fine);
    });
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!target || !reason.trim()) return;
    setSaving(true);
    try {
      await browserApiFetch(`/api/fines/${target.id}`, {
        method: "DELETE",
        body: JSON.stringify({ reason: reason.trim(), protocol_id: protocolId ?? null }),
      });
      finish("soft");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("deleteFineFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  const dialog = (
    <Modal
      open={target !== null}
      onClose={() => finish(null)}
      title={t("deleteReasonTitle")}
      description={target ? t("deleteReasonDescription", { name: target.participant_name_snapshot }) : undefined}
    >
      <ModalSaveForm className="grid" onSubmit={submit}>
        <label className="field-stack">
          <span className="field-label">{t("deleteReasonLabel")}</span>
          <textarea value={reason} maxLength={1000} rows={3} autoFocus onChange={(event) => setReason(event.target.value)} />
          <span className="field-help">{t("deleteReasonHelp")}</span>
        </label>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={() => finish(null)}>{tCommon("cancel")}</button>
          <button data-modal-save type="submit" className="button-danger" disabled={!reason.trim() || saving}>{tCommon("delete")}</button>
        </div>
      </ModalSaveForm>
    </Modal>
  );

  return { requestDelete, dialog };
}

/** Macht ein Löschen mit Begründung rückgängig; liefert die wieder offene Busse. */
export function restoreFine(fineId: string): Promise<AttendanceFine> {
  return browserApiFetch<AttendanceFine>(`/api/fines/${fineId}/restore`, { method: "POST" });
}
